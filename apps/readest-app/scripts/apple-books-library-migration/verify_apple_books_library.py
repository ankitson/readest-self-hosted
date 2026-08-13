#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Verify Apple Books migration rows and S3 objects against the generated plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from apply_apple_books_library import (
    discover_single_readest_user,
    load_existing_readest_books,
    read_environment_file,
    remap_matching_readest_editions,
    run_postgres_query,
    sql_text,
)


def load_json_rows(sql: str) -> list[dict[str, Any]]:
    """Load PostgreSQL rows emitted as one JSON object per line."""
    return [json.loads(line) for line in run_postgres_query(sql)]


def main() -> int:
    """Verify migrated book identities, annotation IDs, file indexes, and stored object sizes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--user-id")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    user_id = args.user_id or discover_single_readest_user()
    existing = load_existing_readest_books(user_id)
    books, resolutions = remap_matching_readest_editions(plan["books"], existing)
    target_hashes = {book["bookHash"] for book in books}
    user = f"{sql_text(user_id)}::uuid"

    database_books = load_json_rows(
        "SELECT json_build_object('bookHash',book_hash,'readingStatus',reading_status,"
        "'progress',progress,'uploadedAt',uploaded_at) "
        f"FROM public.books WHERE user_id={user} AND deleted_at IS NULL"
    )
    database_book_hashes = {row["bookHash"] for row in database_books}
    database_notes = load_json_rows(
        "SELECT json_build_object('bookHash',book_hash,'id',id,'cfi',cfi) "
        f"FROM public.book_notes WHERE user_id={user} AND deleted_at IS NULL "
        "AND id LIKE 'apple-books-%'"
    )
    database_note_keys = {(row["bookHash"], row["id"]) for row in database_notes}
    expected_note_keys = {
        (book["bookHash"], note["id"]) for book in books for note in book["notes"]
    }
    database_files = load_json_rows(
        "SELECT json_build_object('bookHash',book_hash,'fileKey',file_key,'fileSize',file_size) "
        f"FROM public.files WHERE user_id={user} AND deleted_at IS NULL"
    )
    target_files = [row for row in database_files if row["bookHash"] in target_hashes]
    books_with_files = {
        row["bookHash"]
        for row in target_files
        if not row["fileKey"].endswith("/cover.png")
    }

    environment = read_environment_file(args.env_file)
    s3 = boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:39000",
        aws_access_key_id=environment["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=environment["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )
    missing_objects: list[str] = []
    wrong_size_objects: list[str] = []
    for row in target_files:
        try:
            response = s3.head_object(
                Bucket=environment["S3_BUCKET_NAME"], Key=row["fileKey"]
            )
        except ClientError:
            missing_objects.append(row["fileKey"])
            continue
        if int(response.get("ContentLength", -1)) != int(row["fileSize"]):
            wrong_size_objects.append(row["fileKey"])

    failures = {
        "missingBookRows": sorted(target_hashes - database_book_hashes),
        "missingBookFiles": sorted(target_hashes - books_with_files),
        "missingNotes": sorted(
            f"{book_hash}:{note_id}"
            for book_hash, note_id in expected_note_keys - database_note_keys
        ),
        "missingObjects": missing_objects,
        "wrongSizeObjects": wrong_size_objects,
    }
    result = {
        "plannedBooks": len(books),
        "existingEditionMatches": len(resolutions),
        "verifiedBookRows": len(target_hashes & database_book_hashes),
        "verifiedBookFiles": len(target_hashes & books_with_files),
        "expectedNotes": len(expected_note_keys),
        "verifiedNotes": len(expected_note_keys & database_note_keys),
        "verifiedObjects": len(target_files)
        - len(missing_objects)
        - len(wrong_size_objects),
        "failureCounts": {key: len(value) for key, value in failures.items()},
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if any(failures.values()):
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
