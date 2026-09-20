#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3>=1.40,<2", "pillow>=11,<12"]
# ///
"""Verify every Calibre staging book, file index, object, and preservation invariant."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import boto3
from apply_calibre_book_stage import (
    UNTOUCHED_TABLES,
    discover_single_readest_user,
    object_exists_with_size,
    partial_md5,
    read_environment_file,
    run_postgres_query,
    sql_text,
    table_digest,
    validate_plan,
)
from botocore.config import Config


def load_json_rows(sql: str) -> list[dict[str, Any]]:
    """Load one PostgreSQL JSON object per output line."""
    return [json.loads(line) for line in run_postgres_query(sql)]


def decode_metadata(value: Any) -> dict[str, Any]:
    """Decode Readest's JSON-string-inside-JSON metadata representation."""
    while isinstance(value, str):
        value = json.loads(value)
    return value or {}


def main() -> int:
    """Compare the complete live staging Group and object set to the frozen plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--covers-dir", type=Path, required=True)
    parser.add_argument("--pre-state", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--user-id")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text())
    books = validate_plan(plan)
    expected = {book["bookHash"]: book for book in books}
    user_id = args.user_id or discover_single_readest_user()
    user = f"{sql_text(user_id)}::uuid"
    group_id = sql_text(plan["targetGroup"]["id"])
    group_name = sql_text(plan["targetGroup"]["name"])
    live_books = load_json_rows(
        "SELECT json_build_object("
        "'bookHash',book_hash,'format',format,'title',title,'sourceTitle',source_title,"
        "'author',author,'groupId',group_id,'groupName',group_name,'coverHash',cover_hash,"
        "'updatedAt',round(extract(epoch from updated_at)*1000),"
        "'lastReadAt',CASE WHEN last_read_at IS NULL THEN NULL ELSE round(extract(epoch from last_read_at)*1000) END,"
        "'metadata',metadata) FROM public.books "
        f"WHERE user_id={user} AND deleted_at IS NULL AND group_id={group_id} AND group_name={group_name}"
    )
    live_by_hash = {row["bookHash"]: row for row in live_books}
    row_mismatches: list[str] = []
    for book_hash, book in expected.items():
        row = live_by_hash.get(book_hash)
        if not row:
            row_mismatches.append(f"{book_hash}:missing")
            continue
        metadata = decode_metadata(row["metadata"])
        cover = args.covers_dir / f"{book_hash}.png"
        expected_values = {
            "format": book["format"],
            "title": book["title"],
            "sourceTitle": book["sourceTitle"],
            "author": book["author"],
            "groupId": book["groupId"],
            "groupName": book["groupName"],
            "updatedAt": book["updatedAt"],
            "lastReadAt": book.get("lastReadAt"),
            "coverHash": partial_md5(cover),
        }
        for field, value in expected_values.items():
            if row.get(field) != value:
                row_mismatches.append(f"{book_hash}:{field}")
        if (
            not metadata.get("identifier")
            or metadata.get("calibreSource", {}).get("classification", {}).get("category") != "Book"
        ):
            row_mismatches.append(f"{book_hash}:metadata")

    target_hash_sql = ",".join(sql_text(book_hash) for book_hash in expected)
    live_files = load_json_rows(
        "SELECT json_build_object('bookHash',book_hash,'fileKey',file_key,'fileSize',file_size) "
        f"FROM public.files WHERE user_id={user} AND deleted_at IS NULL AND book_hash IN ({target_hash_sql})"
    )
    live_file_map = {row["fileKey"]: row for row in live_files}
    expected_files: dict[str, tuple[str, int]] = {}
    for book_hash, book in expected.items():
        prefix = f"{user_id}/Readest/Books/{book_hash}"
        source_size = int(book["fileSize"])
        cover_size = (args.covers_dir / f"{book_hash}.png").stat().st_size
        expected_files[f"{prefix}/{book_hash}.{book['format'].lower()}"] = (book_hash, source_size)
        expected_files[f"{prefix}/cover.png"] = (book_hash, cover_size)
    file_mismatches = sorted(
        key
        for key, (book_hash, size) in expected_files.items()
        if key not in live_file_map
        or live_file_map[key]["bookHash"] != book_hash
        or int(live_file_map[key]["fileSize"]) != size
    )
    unexpected_files = sorted(set(live_file_map) - set(expected_files))

    environment = read_environment_file(args.env_file)
    client = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:39000",
        aws_access_key_id=environment["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=environment["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )
    missing_or_wrong_objects = sorted(
        key
        for key, (_, size) in expected_files.items()
        if not object_exists_with_size(client, environment["S3_BUCKET_NAME"], key, size)
    )
    pre_state = json.loads(args.pre_state.read_text())
    changed_untouched_tables = sorted(
        table
        for table in UNTOUCHED_TABLES
        if table_digest(table) != pre_state["fingerprints"][table]
    )
    related_state_rows = {}
    for table in UNTOUCHED_TABLES:
        related_state_rows[table] = int(
            run_postgres_query(
                f"SELECT count(*) FROM public.{table} WHERE user_id={user} AND book_hash IN ({target_hash_sql})"
            )[0]
        )

    failures = {
        "missingOrUnexpectedGroupHashes": sorted(set(expected) ^ set(live_by_hash)),
        "rowMismatches": row_mismatches,
        "fileMismatches": file_mismatches,
        "unexpectedFiles": unexpected_files,
        "missingOrWrongSizeObjects": missing_or_wrong_objects,
        "changedUntouchedTables": changed_untouched_tables,
        "unexpectedConfigsNotesOrStats": [
            f"{table}:{count}" for table, count in related_state_rows.items() if count
        ],
    }
    result = {
        "result": "verified" if not any(failures.values()) else "verification-failed",
        "group": plan["targetGroup"],
        "verifiedBooks": len(live_by_hash),
        "verifiedFileRows": len(live_files),
        "verifiedObjects": len(expected_files) - len(missing_or_wrong_objects),
        "booksWithLastReadDate": sum(row.get("lastReadAt") is not None for row in live_books),
        "relatedStateRows": related_state_rows,
        "failureCounts": {name: len(values) for name, values in failures.items()},
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({**result, "failures": failures}, indent=2) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if any(failures.values()):
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
