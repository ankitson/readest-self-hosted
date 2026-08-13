#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Dry-run or apply a Readest Apple Books full-library migration plan."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


MIGRATION_FORMAT = "readest-apple-books-library-plan"
MIGRATION_VERSION = 1


def read_environment_file(path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE environment file without printing credential values."""
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def partial_md5(path: Path) -> str:
    """Compute Readest's sampled partial MD5 over head/exponential file ranges."""
    file_size = path.stat().st_size
    ranges: list[tuple[int, int]] = []
    for exponent in range(-1, 11):
        # JavaScript's `1024 << -2` masks the shift count and overflows to zero;
        # spell that first head sample explicitly instead of relying on language quirks.
        start = 0 if exponent == -1 else min(file_size, 1024 << (2 * exponent))
        end = min(start + 1024, file_size)
        if start >= file_size:
            break
        ranges.append((start, end))
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for start, end in ranges:
            source.seek(start)
            digest.update(source.read(end - start))
    return digest.hexdigest()


def run_postgres_query(sql: str) -> list[str]:
    """Run a read-only PostgreSQL query inside the dedicated Readest database container."""
    result = subprocess.run(
        [
            "docker",
            "exec",
            "readest-db",
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-Atc",
            sql,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def apply_postgres_sql(sql: str) -> None:
    """Apply one transactional SQL migration through psql without exposing row contents."""
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "readest-db",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
        ],
        input=sql,
        check=True,
        text=True,
        stdout=subprocess.DEVNULL,
    )


def sql_text(value: str) -> str:
    """Encode arbitrary UTF-8 text as a safe PostgreSQL expression."""
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"convert_from(decode('{encoded}', 'base64'), 'UTF8')"


def sql_timestamp(milliseconds: int | None) -> str:
    """Render Unix epoch milliseconds as a PostgreSQL timestamptz expression."""
    return (
        "NULL"
        if milliseconds is None
        else f"to_timestamp({int(milliseconds)} / 1000.0)"
    )


def sql_nullable_text(value: str | None) -> str:
    """Render nullable text with base64-safe SQL encoding."""
    return "NULL" if value is None else sql_text(value)


def sql_progress(progress: list[int] | None, postgres_type: str) -> str:
    """Render Readest progress as either a Postgres int array or its JSON-string wire form."""
    if not progress:
        return "NULL"
    current, total = int(progress[0]), int(progress[1])
    if postgres_type == "array":
        return f"ARRAY[{current},{total}]::integer[]"
    return f"to_jsonb({sql_text(json.dumps([current, total], separators=(',', ':')))})"


@dataclass(frozen=True)
class ExistingReadestBook:
    """Existing Readest cloud state needed for conflict-safe migration decisions."""

    book_hash: str
    meta_hash: str | None
    updated_at: int
    config_updated_at: int
    has_book_file: bool
    has_cover_file: bool


def load_existing_readest_books(user_id: str) -> dict[str, ExistingReadestBook]:
    """Load exact-hash Readest books and whether their cloud file objects are already indexed."""
    user = sql_text(user_id)
    rows = run_postgres_query(
        "SELECT json_build_object("
        "'bookHash', b.book_hash, 'metaHash', b.meta_hash, "
        "'updatedAt', round(extract(epoch from b.updated_at) * 1000), "
        "'configUpdatedAt', COALESCE((SELECT round(extract(epoch from c.updated_at) * 1000) "
        "FROM public.book_configs c WHERE c.user_id=b.user_id AND c.book_hash=b.book_hash), 0), "
        "'hasBookFile', EXISTS (SELECT 1 FROM public.files f WHERE f.user_id=b.user_id "
        "AND f.book_hash=b.book_hash AND f.deleted_at IS NULL AND f.file_key !~ '/cover\\.png$'), "
        "'hasCoverFile', EXISTS (SELECT 1 FROM public.files f WHERE f.user_id=b.user_id "
        "AND f.book_hash=b.book_hash AND f.deleted_at IS NULL AND f.file_key ~ '/cover\\.png$')) "
        f"FROM public.books b WHERE b.user_id={user}::uuid AND b.deleted_at IS NULL"
    )
    result: dict[str, ExistingReadestBook] = {}
    for line in rows:
        value = json.loads(line)
        result[value["bookHash"]] = ExistingReadestBook(
            book_hash=value["bookHash"],
            meta_hash=value.get("metaHash"),
            updated_at=int(value.get("updatedAt") or 0),
            config_updated_at=int(value.get("configUpdatedAt") or 0),
            has_book_file=bool(value.get("hasBookFile")),
            has_cover_file=bool(value.get("hasCoverFile")),
        )
    return result


def remap_matching_readest_editions(
    books: list[dict[str, Any]],
    existing: dict[str, ExistingReadestBook],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Route Apple state into an existing same-metadata Readest edition instead of duplicating it."""
    by_meta_hash: dict[str, list[ExistingReadestBook]] = {}
    for state in existing.values():
        if state.meta_hash:
            by_meta_hash.setdefault(state.meta_hash, []).append(state)
    remapped: list[dict[str, Any]] = []
    resolutions: list[dict[str, str]] = []
    for source_book in books:
        book = copy.deepcopy(source_book)
        if book["bookHash"] not in existing and book.get("metaHash"):
            candidates = by_meta_hash.get(book["metaHash"], [])
            if len(candidates) == 1:
                target = candidates[0]
                resolutions.append(
                    {
                        "assetId": book["assetId"],
                        "sourceBookHash": book["bookHash"],
                        "targetBookHash": target.book_hash,
                    }
                )
                book["sourceBookHash"] = book["bookHash"]
                book["bookHash"] = target.book_hash
                for note in book["notes"]:
                    note["bookHash"] = target.book_hash
        remapped.append(book)
    return remapped, resolutions


def discover_single_readest_user() -> str:
    """Return the only Readest auth user, refusing to guess in a multi-user installation."""
    users = run_postgres_query("SELECT id::text FROM auth.users ORDER BY id")
    if len(users) != 1:
        raise RuntimeError(
            f"Apple Books library migration expected one Readest user, found {len(users)}"
        )
    return users[0]


def object_exists_with_size(s3_client: Any, bucket: str, key: str, size: int) -> bool:
    """Return true only when an S3 object exists at the expected byte size."""
    try:
        response = s3_client.head_object(Bucket=bucket, Key=key)
        return int(response.get("ContentLength", -1)) == size
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def build_migration_sql(
    books: list[dict[str, Any]],
    user_id: str,
    exported_at: int,
    uploaded_files: list[tuple[str, str, int]],
) -> str:
    """Build one idempotent transaction for Readest books, configs, notes, stats, and file indexes."""
    user = f"{sql_text(user_id)}::uuid"
    statements = ["BEGIN;"]
    for book in books:
        book_hash = sql_text(book["bookHash"])
        meta_hash = sql_nullable_text(book.get("metaHash"))
        metadata_json = json.dumps(
            book["metadata"], ensure_ascii=False, separators=(",", ":")
        )
        progress_array = sql_progress(book.get("progress"), "array")
        created_at = sql_timestamp(book["createdAt"])
        updated_at = sql_timestamp(book["updatedAt"])
        uploaded_at = sql_timestamp(book["uploadedAt"])
        reading_status_updated_at = sql_timestamp(book["readingStatusUpdatedAt"])
        metadata_updated_at = sql_timestamp(book["metadataUpdatedAt"])
        cover_hash = sql_nullable_text(book.get("coverHash"))
        statements.append(
            "INSERT INTO public.books "
            "(user_id,book_hash,meta_hash,format,title,source_title,author,created_at,updated_at,"
            "deleted_at,uploaded_at,progress,reading_status,reading_status_updated_at,cover_hash,"
            "cover_updated_at,metadata_updated_at,metadata) VALUES ("
            f"{user},{book_hash},{meta_hash},{sql_text(book['format'])},{sql_text(book['title'])},"
            f"{sql_text(book['sourceTitle'])},{sql_text(book['author'])},{created_at},{updated_at},"
            f"NULL,{uploaded_at},{progress_array},{sql_text(book['readingStatus'])},"
            f"{reading_status_updated_at},{cover_hash},{metadata_updated_at},{metadata_updated_at},"
            f"to_json({sql_text(metadata_json)})) "
            "ON CONFLICT (user_id,book_hash) DO UPDATE SET "
            "deleted_at=NULL, created_at=LEAST(books.created_at,EXCLUDED.created_at), "
            "uploaded_at=COALESCE(books.uploaded_at,EXCLUDED.uploaded_at), "
            "title=CASE WHEN books.updated_at>EXCLUDED.updated_at THEN books.title ELSE EXCLUDED.title END, "
            "source_title=CASE WHEN books.updated_at>EXCLUDED.updated_at THEN books.source_title ELSE EXCLUDED.source_title END, "
            "author=CASE WHEN books.updated_at>EXCLUDED.updated_at THEN books.author ELSE EXCLUDED.author END, "
            "progress=CASE WHEN books.updated_at>EXCLUDED.updated_at THEN books.progress ELSE COALESCE(EXCLUDED.progress,books.progress) END, "
            "updated_at=GREATEST(books.updated_at,EXCLUDED.updated_at), "
            "reading_status=CASE WHEN COALESCE(books.reading_status_updated_at,'epoch')>"
            "COALESCE(EXCLUDED.reading_status_updated_at,'epoch') THEN books.reading_status ELSE EXCLUDED.reading_status END, "
            "reading_status_updated_at=GREATEST(books.reading_status_updated_at,EXCLUDED.reading_status_updated_at), "
            "cover_hash=COALESCE(books.cover_hash,EXCLUDED.cover_hash), "
            "cover_updated_at=COALESCE(books.cover_updated_at,EXCLUDED.cover_updated_at), "
            "metadata=CASE WHEN COALESCE(books.metadata_updated_at,'epoch')>"
            "COALESCE(EXCLUDED.metadata_updated_at,'epoch') THEN books.metadata ELSE EXCLUDED.metadata END, "
            "metadata_updated_at=GREATEST(books.metadata_updated_at,EXCLUDED.metadata_updated_at);"
        )

        config = book["config"]
        if not book.get("preserveExistingConfig"):
            statements.append(
                "INSERT INTO public.book_configs "
                "(user_id,book_hash,meta_hash,location,progress,search_config,view_settings,created_at,updated_at,deleted_at) VALUES ("
                f"{user},{book_hash},{meta_hash},{sql_nullable_text(config.get('location'))},"
                f"{sql_progress(config.get('progress'), 'json')},to_jsonb({sql_text('{}')}),"
                f"to_jsonb({sql_text('{}')}),{created_at},{sql_timestamp(exported_at)},NULL) "
                "ON CONFLICT (user_id,book_hash) DO UPDATE SET "
                "meta_hash=EXCLUDED.meta_hash,location=EXCLUDED.location,progress=EXCLUDED.progress,"
                "updated_at=EXCLUDED.updated_at,deleted_at=NULL "
                "WHERE book_configs.updated_at<=EXCLUDED.updated_at;"
            )

        for note in book["notes"]:
            statements.append(
                "INSERT INTO public.book_notes "
                "(user_id,book_hash,meta_hash,id,type,cfi,text,style,color,note,page,global,created_at,updated_at,deleted_at) VALUES ("
                f"{user},{book_hash},{meta_hash},{sql_text(note['id'])},{sql_text(note['type'])},"
                f"{sql_text(note['cfi'])},{sql_nullable_text(note.get('text'))},{sql_nullable_text(note.get('style'))},"
                f"{sql_nullable_text(note.get('color'))},{sql_text(note.get('note') or '')},"
                f"{int(note['page']) if note.get('page') is not None else 'NULL'},"
                f"{'TRUE' if note.get('global') else 'FALSE'},{sql_timestamp(note['createdAt'])},"
                f"{sql_timestamp(note['updatedAt'])},NULL) "
                "ON CONFLICT (user_id,book_hash,id) DO UPDATE SET "
                "meta_hash=EXCLUDED.meta_hash,type=EXCLUDED.type,cfi=EXCLUDED.cfi,text=EXCLUDED.text,"
                "style=EXCLUDED.style,color=EXCLUDED.color,note=EXCLUDED.note,page=EXCLUDED.page,"
                "global=EXCLUDED.global,created_at=EXCLUDED.created_at,updated_at=EXCLUDED.updated_at,deleted_at=NULL "
                "WHERE book_notes.updated_at<=EXCLUDED.updated_at;"
            )

        statements.append(
            "INSERT INTO public.stat_books (user_id,book_hash,title,authors,updated_at,deleted_at) VALUES ("
            f"{user},{book_hash},{sql_text(book['title'])},{sql_text(book['author'])},"
            f"{sql_timestamp(exported_at)},NULL) ON CONFLICT (user_id,book_hash) DO UPDATE SET "
            "title=EXCLUDED.title,authors=EXCLUDED.authors,updated_at=EXCLUDED.updated_at,deleted_at=NULL "
            "WHERE stat_books.updated_at<=EXCLUDED.updated_at;"
        )
        if (
            book["readingStatus"] != "unread"
            and book.get("progress")
            and book["updatedAt"] > 0
        ):
            page, total_pages = map(int, book["progress"])
            start_time = int(book["updatedAt"] // 1000)
            ext = json.dumps(
                {"source": "apple-books-library-migration", "lastReadOnly": True},
                separators=(",", ":"),
            )
            statements.append(
                "INSERT INTO public.stat_pages "
                "(user_id,book_hash,page,start_time,duration,total_pages,ext,updated_at,deleted_at) VALUES ("
                f"{user},{book_hash},{page},{start_time},0,{total_pages},{sql_text(ext)}::jsonb,"
                f"{sql_timestamp(exported_at)},NULL) ON CONFLICT (user_id,book_hash,page,start_time) DO UPDATE SET "
                "total_pages=EXCLUDED.total_pages,ext=EXCLUDED.ext,updated_at=EXCLUDED.updated_at,deleted_at=NULL;"
            )

    for book_hash_value, file_key, file_size in uploaded_files:
        statements.append(
            "INSERT INTO public.files (user_id,book_hash,file_key,file_size,created_at,updated_at,deleted_at) VALUES ("
            f"{user},{sql_text(book_hash_value)},{sql_text(file_key)},{file_size},"
            f"{sql_timestamp(exported_at)},{sql_timestamp(exported_at)},NULL) "
            "ON CONFLICT (file_key) DO UPDATE SET file_size=EXCLUDED.file_size,"
            "updated_at=EXCLUDED.updated_at,deleted_at=NULL;"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def main() -> int:
    """Validate a migration plan, report changes, and apply only when explicitly requested."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--covers-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--user-id")
    parser.add_argument("--asset-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text())
    if (
        plan.get("format") != MIGRATION_FORMAT
        or plan.get("version") != MIGRATION_VERSION
    ):
        raise RuntimeError("Apple Books library migration plan format/version mismatch")
    selected = [
        book
        for book in plan["books"]
        if not args.asset_id or book["assetId"] in args.asset_id
    ]
    user_id = args.user_id or discover_single_readest_user()
    existing = load_existing_readest_books(user_id)
    hash_mismatches: list[str] = []
    missing_files: list[str] = []
    for book in selected:
        source = args.stage_dir / book["stagedFilename"]
        if not source.is_file() or source.stat().st_size != int(book["fileSize"]):
            missing_files.append(book["assetId"])
            continue
        if partial_md5(source) != book["bookHash"]:
            hash_mismatches.append(book["assetId"])
    if missing_files or hash_mismatches:
        raise RuntimeError(
            f"Apple Books library migration validation failed: {len(missing_files)} missing/size mismatch, "
            f"{len(hash_mismatches)} hash mismatch"
        )

    selected, edition_resolutions = remap_matching_readest_editions(selected, existing)
    preserved_existing_configs = 0
    for book in selected:
        state = existing.get(book["bookHash"])
        if state and state.config_updated_at > int(book["config"]["updatedAt"]):
            book["preserveExistingConfig"] = True
            preserved_existing_configs += 1
    unresolved_meta_collisions = [
        book["assetId"]
        for book in selected
        if book["bookHash"] not in existing
        and book.get("metaHash")
        and sum(state.meta_hash == book["metaHash"] for state in existing.values()) > 1
    ]
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "selectedBooks": len(selected),
        "newBooks": sum(book["bookHash"] not in existing for book in selected),
        "existingExactBooks": sum(book["bookHash"] in existing for book in selected),
        "preservedNewerReadestConfigs": preserved_existing_configs,
        "existingEditionMatches": len(edition_resolutions),
        "unresolvedMetadataHashCollisions": len(unresolved_meta_collisions),
        "notes": sum(len(book["notes"]) for book in selected),
        "covers": sum(bool(book.get("coverRelativePath")) for book in selected),
        "sourceBytes": sum(int(book["fileSize"]) for book in selected),
        "planParseFailures": int(plan["summary"]["parseFailures"]),
        "planCloudOnlyItems": int(plan["summary"]["cloudOnlyItems"]),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if edition_resolutions:
        print(json.dumps({"existingEditionMatches": edition_resolutions}, indent=2))
    if unresolved_meta_collisions:
        print(
            json.dumps(
                {"unresolvedMetadataHashCollisions": unresolved_meta_collisions},
                indent=2,
            )
        )
    if not args.apply:
        return 0

    environment = read_environment_file(args.env_file)
    required_keys = ("S3_BUCKET_NAME", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    missing_keys = [key for key in required_keys if not environment.get(key)]
    if missing_keys:
        raise RuntimeError(
            f"Apple Books library migration env file missing keys: {', '.join(missing_keys)}"
        )
    s3 = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:39000",
        aws_access_key_id=environment["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=environment["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )
    bucket = environment["S3_BUCKET_NAME"]
    uploaded_files: list[tuple[str, str, int]] = []
    for index, book in enumerate(selected, start=1):
        state = existing.get(book["bookHash"])
        extension = book["format"].lower()
        book_key = (
            f"{user_id}/Readest/Books/{book['bookHash']}/{book['bookHash']}.{extension}"
        )
        source = args.stage_dir / book["stagedFilename"]
        if not (state and state.has_book_file):
            if not object_exists_with_size(s3, bucket, book_key, source.stat().st_size):
                s3.upload_file(str(source), bucket, book_key)
            uploaded_files.append((book["bookHash"], book_key, source.stat().st_size))
        cover_name = book.get("coverRelativePath")
        if cover_name and not (state and state.has_cover_file):
            cover = args.covers_dir / cover_name
            cover_key = f"{user_id}/Readest/Books/{book['bookHash']}/cover.png"
            if not object_exists_with_size(s3, bucket, cover_key, cover.stat().st_size):
                s3.upload_file(str(cover), bucket, cover_key)
            uploaded_files.append((book["bookHash"], cover_key, cover.stat().st_size))
        if index % 25 == 0 or index == len(selected):
            print(f"Uploaded/indexed {index}/{len(selected)} planned book(s).")

    sql = build_migration_sql(
        selected, user_id, int(plan["exportedAt"]), uploaded_files
    )
    apply_postgres_sql(sql)
    print(
        json.dumps(
            {
                "result": "applied",
                "books": len(selected),
                "uploadedObjects": len(uploaded_files),
                "notes": sum(len(book["notes"]) for book in selected),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
