#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3>=1.40,<2", "pillow>=11,<12"]
# ///
"""Validate, apply, and verify the one-off Calibre Book staging import."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import subprocess
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from PIL import Image, ImageOps

PLAN_FORMAT = "readest-calibre-book-plan"
PLAN_VERSION = 1
EXPECTED_GROUP_NAME = "Calibre Staging"
UNTOUCHED_TABLES = ("book_configs", "book_notes", "stat_books", "stat_pages")


def read_environment_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE settings without ever displaying credential values."""
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def run_postgres_query(sql: str) -> list[str]:
    """Run a read-only query against the dedicated local Readest Postgres."""
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
    return [line for line in result.stdout.split("\n") if line]


def apply_postgres_sql(sql: str) -> None:
    """Apply a single transaction while keeping personal book metadata out of logs."""
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
    """Encode arbitrary Unicode as a safe PostgreSQL text expression."""
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"convert_from(decode('{encoded}', 'base64'), 'UTF8')"


def sql_nullable_text(value: str | None) -> str:
    """Render nullable text using the same safe encoding as required strings."""
    return "NULL" if value is None else sql_text(value)


def sql_timestamp(milliseconds: int | None) -> str:
    """Render Unix epoch milliseconds as a PostgreSQL timestamptz expression."""
    return "NULL" if milliseconds is None else f"to_timestamp({int(milliseconds)} / 1000.0)"


def sql_text_array(values: list[str]) -> str:
    """Render a text array without interpolating catalog text into SQL syntax."""
    if not values:
        return "NULL"
    return "ARRAY[" + ",".join(sql_text(str(value)) for value in values) + "]::text[]"


def full_sha256(path: Path) -> str:
    """Return a streaming SHA-256 for staged-source integrity checks."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def partial_md5(path: Path) -> str:
    """Compute Readest's sampled MD5 over the head and exponential file ranges."""
    file_size = path.stat().st_size
    ranges: list[tuple[int, int]] = []
    for exponent in range(-1, 11):
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


def discover_single_readest_user() -> str:
    """Return the only Readest user, refusing to guess in a multi-user service."""
    users = run_postgres_query("SELECT id::text FROM auth.users ORDER BY id")
    if len(users) != 1:
        raise RuntimeError(f"Calibre staging import expected one Readest user, found {len(users)}")
    return users[0]


def load_active_book_hashes(user_id: str) -> set[str]:
    """Load active book hashes for last-moment idempotency checks."""
    return set(
        run_postgres_query(
            "SELECT book_hash FROM public.books "
            f"WHERE user_id={sql_text(user_id)}::uuid AND deleted_at IS NULL"
        )
    )


def table_digest(table: str) -> str:
    """Fingerprint a full table independent of physical row order."""
    return run_postgres_query(
        "SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text),'' "
        f"ORDER BY md5(row_to_json(x)::text))),'') FROM (SELECT * FROM public.{table}) x"
    )[0]


def row_digests(table: str, key: str) -> dict[str, str]:
    """Capture complete per-row fingerprints to prove pre-existing rows stayed untouched."""
    rows = run_postgres_query(
        f"SELECT {key}||E'\\t'||md5(row_to_json(x)::text) FROM (SELECT * FROM public.{table}) x ORDER BY {key}"
    )
    return dict(line.split("\t", 1) for line in rows)


def prepare_cover(source: Path, destination: Path) -> str:
    """Decode a staged cover and write the real PNG representation Readest expects."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        normalized = ImageOps.exif_transpose(image)
        if normalized.mode not in {"RGB", "RGBA"}:
            normalized = normalized.convert("RGB")
        normalized.save(destination, format="PNG", optimize=True)
    return partial_md5(destination)


def object_exists_with_size(client: Any, bucket: str, key: str, size: int) -> bool:
    """Return true only when an object already exists at the expected size."""
    try:
        result = client.head_object(Bucket=bucket, Key=key)
        return int(result.get("ContentLength", -1)) == size
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def build_import_sql(
    books: list[dict[str, Any]], user_id: str, file_rows: list[tuple[str, str, int]]
) -> str:
    """Build an insert-only Readest transaction for books and cloud-file indexes."""
    user = f"{sql_text(user_id)}::uuid"
    statements = ["BEGIN;"]
    for book in books:
        metadata_json = json.dumps(book["metadata"], ensure_ascii=False, separators=(",", ":"))
        statements.append(
            "INSERT INTO public.books "
            "(user_id,book_hash,meta_hash,format,title,source_title,author,\"group\",tags,created_at,"
            "updated_at,deleted_at,uploaded_at,progress,reading_status,reading_status_updated_at,"
            "cover_hash,cover_updated_at,metadata_updated_at,group_id,group_name,metadata,last_read_at) VALUES ("
            f"{user},{sql_text(book['bookHash'])},{sql_nullable_text(book.get('metaHash'))},"
            f"{sql_text(book['format'])},{sql_text(book['title'])},{sql_text(book['sourceTitle'])},"
            f"{sql_text(book['author'])},NULL,{sql_text_array(book.get('tags') or [])},"
            f"{sql_timestamp(book['createdAt'])},{sql_timestamp(book['updatedAt'])},NULL,"
            f"{sql_timestamp(book['uploadedAt'])},NULL,{sql_text(book['readingStatus'])},"
            f"{sql_timestamp(book['readingStatusUpdatedAt'])},{sql_text(book['coverHash'])},"
            f"{sql_timestamp(book['metadataUpdatedAt'])},{sql_timestamp(book['metadataUpdatedAt'])},"
            f"{sql_text(book['groupId'])},{sql_text(book['groupName'])},to_json({sql_text(metadata_json)}),"
            f"{sql_timestamp(book.get('lastReadAt'))}) ON CONFLICT (user_id,book_hash) DO UPDATE SET "
            "meta_hash=EXCLUDED.meta_hash,format=EXCLUDED.format,title=EXCLUDED.title,"
            "source_title=EXCLUDED.source_title,author=EXCLUDED.author,tags=EXCLUDED.tags,"
            "created_at=EXCLUDED.created_at,updated_at=EXCLUDED.updated_at,deleted_at=NULL,"
            "uploaded_at=EXCLUDED.uploaded_at,progress=NULL,reading_status=EXCLUDED.reading_status,"
            "reading_status_updated_at=EXCLUDED.reading_status_updated_at,cover_hash=EXCLUDED.cover_hash,"
            "cover_updated_at=EXCLUDED.cover_updated_at,metadata_updated_at=EXCLUDED.metadata_updated_at,"
            "group_id=EXCLUDED.group_id,group_name=EXCLUDED.group_name,metadata=EXCLUDED.metadata,"
            "last_read_at=EXCLUDED.last_read_at WHERE books.deleted_at IS NOT NULL;"
        )
    for book_hash, file_key, file_size in file_rows:
        statements.append(
            "INSERT INTO public.files (user_id,book_hash,file_key,file_size,created_at,updated_at,deleted_at) VALUES ("
            f"{user},{sql_text(book_hash)},{sql_text(file_key)},{file_size},NOW(),NOW(),NULL) "
            "ON CONFLICT (file_key) DO NOTHING;"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


def validate_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Enforce the reviewed selection, destination, and collision-free plan contract."""
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise RuntimeError("Calibre staging plan format/version mismatch")
    if plan.get("targetGroup", {}).get("name") != EXPECTED_GROUP_NAME:
        raise RuntimeError("Calibre staging plan targets an unexpected Group")
    summary = plan.get("summary", {})
    if summary.get("selectedBooks") != 290 or summary.get("parseFailures") != 0:
        raise RuntimeError("Calibre staging plan is not the reviewed 290-book selection")
    if summary.get("internalCollisions") != 0 or plan.get("internalCollisions"):
        raise RuntimeError("Calibre staging plan contains unresolved identity collisions")
    books = [book for book in plan["books"] if book["disposition"] == "create"]
    if len({book["bookHash"] for book in books}) != len(books):
        raise RuntimeError("Calibre staging plan repeats a Readest book hash")
    for book in books:
        classification = book.get("metadata", {}).get("calibreSource", {}).get("classification", {})
        if classification.get("category") != "Book":
            raise RuntimeError(f"Non-Book category reached import plan: {book['calibreId']}")
    return books


def main() -> int:
    """Validate all inputs, print a dry run, and mutate only with explicit --apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--user-id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text())
    planned_books = validate_plan(plan)
    user_id = args.user_id or discover_single_readest_user()
    live_hashes = load_active_book_hashes(user_id)
    books = [book for book in planned_books if book["bookHash"] not in live_hashes]
    missing_or_changed: list[int] = []
    cover_failures: list[int] = []
    for book in books:
        source = args.stage_dir / book["archiveBookPath"]
        cover = args.stage_dir / book["archiveCoverPath"]
        if (
            not source.is_file()
            or source.stat().st_size != int(book["fileSize"])
            or full_sha256(source) != book["sourceFileSha256"]
            or partial_md5(source) != book["bookHash"]
            or not cover.is_file()
            or full_sha256(cover) != book["sourceCoverSha256"]
        ):
            missing_or_changed.append(int(book["calibreId"]))
            continue
        try:
            with Image.open(cover) as image:
                image.verify()
        except Exception:  # noqa: BLE001 - Pillow plugins expose heterogeneous decoder errors.
            cover_failures.append(int(book["calibreId"]))
    if missing_or_changed or cover_failures:
        raise RuntimeError(
            "Calibre staging validation failed: "
            f"{len(missing_or_changed)} source mismatches, {len(cover_failures)} invalid covers"
        )

    report = {
        "mode": "apply" if args.apply else "dry-run",
        "planBooks": len(planned_books),
        "newBooks": len(books),
        "alreadyPresentExactBooks": len(planned_books) - len(books),
        "epubs": sum(book["format"] == "EPUB" for book in books),
        "pdfs": sum(book["format"] == "PDF" for book in books),
        "covers": len(books),
        "sourceBytes": sum(int(book["fileSize"]) for book in books),
        "group": plan["targetGroup"],
        "lastReadDates": sum(book.get("lastReadAt") is not None for book in books),
        "configsNotesAndStatsToCreate": 0,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if not args.apply or not books:
        return 0

    environment = read_environment_file(args.env_file)
    required_keys = ("S3_BUCKET_NAME", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    missing_keys = [key for key in required_keys if not environment.get(key)]
    if missing_keys:
        raise RuntimeError(f"Readest environment file missing keys: {', '.join(missing_keys)}")
    s3 = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:39000",
        aws_access_key_id=environment["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=environment["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )
    bucket = environment["S3_BUCKET_NAME"]
    pre_book_rows = row_digests("books", "book_hash")
    pre_file_rows = row_digests("files", "file_key")
    untouched_before = {table: table_digest(table) for table in UNTOUCHED_TABLES}
    file_rows: list[tuple[str, str, int]] = []
    newly_uploaded: list[str] = []
    prepared_covers = args.output_dir / "covers"

    try:
        for index, book in enumerate(books, start=1):
            source = args.stage_dir / book["archiveBookPath"]
            cover_source = args.stage_dir / book["archiveCoverPath"]
            cover = prepared_covers / f"{book['bookHash']}.png"
            book["coverHash"] = prepare_cover(cover_source, cover)
            extension = book["format"].lower()
            prefix = f"{user_id}/Readest/Books/{book['bookHash']}"
            objects = [
                (source, f"{prefix}/{book['bookHash']}.{extension}"),
                (cover, f"{prefix}/cover.png"),
            ]
            for local_path, key in objects:
                exists = object_exists_with_size(s3, bucket, key, local_path.stat().st_size)
                if not exists:
                    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
                    s3.upload_file(
                        str(local_path), bucket, key, ExtraArgs={"ContentType": content_type}
                    )
                    newly_uploaded.append(key)
                file_rows.append((book["bookHash"], key, local_path.stat().st_size))
            if index % 25 == 0 or index == len(books):
                print(f"Prepared/uploaded {index}/{len(books)} book(s).")

        apply_postgres_sql(build_import_sql(books, user_id, file_rows))
    except Exception:
        for key in newly_uploaded:
            try:
                s3.delete_object(Bucket=bucket, Key=key)
            except Exception as cleanup_error:  # noqa: BLE001 - retain the original migration failure.
                print(
                    f"Warning: object rollback failed ({type(cleanup_error).__name__})",
                    file=sys.stderr,
                )
        raise

    live_group_count = int(
        run_postgres_query(
            "SELECT count(*) FROM public.books "
            f"WHERE user_id={sql_text(user_id)}::uuid AND deleted_at IS NULL "
            f"AND group_id={sql_text(plan['targetGroup']['id'])} "
            f"AND group_name={sql_text(plan['targetGroup']['name'])}"
        )[0]
    )
    imported_hashes = {book["bookHash"] for book in books}
    post_book_rows = row_digests("books", "book_hash")
    post_file_rows = row_digests("files", "file_key")
    changed_existing_books = sorted(
        key
        for key, digest in pre_book_rows.items()
        if key not in imported_hashes and post_book_rows.get(key) != digest
    )
    changed_existing_files = sorted(
        key for key, digest in pre_file_rows.items() if post_file_rows.get(key) != digest
    )
    untouched_after = {table: table_digest(table) for table in UNTOUCHED_TABLES}
    missing_objects = []
    for book_hash, key, size in file_rows:
        if book_hash in imported_hashes and not object_exists_with_size(s3, bucket, key, size):
            missing_objects.append(key)
    failures = {
        "groupCountMatches": live_group_count == len(planned_books),
        "existingBookRowsUnchanged": not changed_existing_books,
        "existingFileRowsUnchanged": not changed_existing_files,
        "configsNotesStatsUnchanged": untouched_before == untouched_after,
        "allObjectsPresent": not missing_objects,
    }
    result = {
        "result": "applied-and-verified" if all(failures.values()) else "verification-failed",
        "insertedBooks": len(books),
        "groupBooks": live_group_count,
        "fileRows": len(file_rows),
        "newlyUploadedObjects": len(newly_uploaded),
        "checks": failures,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "apply-report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not all(failures.values()):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
