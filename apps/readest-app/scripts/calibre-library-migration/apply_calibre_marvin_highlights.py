#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Dry-run, or apply and verify, a Calibre Marvin highlight plan against existing Readest books.

Only `book_notes` rows are written. Book rows, configs, progress and statistics
are untouched, because every target book already exists in Readest. Rows match
the Apple Books migration's note insert, but are insert-only: note IDs derive
from the Marvin quote, so a re-run skips notes already imported and never
resurrects or overwrites one deleted or edited on a device since. A dry run
rehearses the transaction and rolls it back.

Sync pulls notes by `updated_at > device cursor`, so notes are stamped with the
apply time (not the export time) to stay visible to devices that synced since.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apple-books-library-migration"))
from apply_apple_books_library import (
    apply_postgres_sql,
    run_postgres_query,
    sql_nullable_text,
    sql_text,
    sql_timestamp,
)

PLAN_FORMAT = "readest-calibre-marvin-highlights-plan"
PLAN_VERSION = 1


def build_notes_sql(plan: dict, applied_at: int, final: str) -> str:
    """One transaction upserting every planned note, ending in COMMIT or ROLLBACK."""
    user = f"{sql_text(plan['userId'])}::uuid"
    statements = ["BEGIN;"]
    for book in plan["books"]:
        for note in book["notes"]:
            statements.append(
                "INSERT INTO public.book_notes "
                "(user_id,book_hash,meta_hash,id,type,cfi,text,style,color,note,page,global,created_at,updated_at,deleted_at) VALUES ("
                f"{user},{sql_text(book['bookHash'])},{sql_nullable_text(book.get('metaHash'))},"
                f"{sql_text(note['id'])},{sql_text(note['type'])},{sql_text(note['cfi'])},"
                f"{sql_nullable_text(note.get('text'))},{sql_nullable_text(note.get('style'))},"
                f"{sql_nullable_text(note.get('color'))},{sql_text(note.get('note') or '')},NULL,FALSE,"
                f"{sql_timestamp(note['createdAt'])},{sql_timestamp(applied_at)},NULL) "
                "ON CONFLICT (user_id,book_hash,id) DO NOTHING;"
            )
    statements.append(f"{final};")
    return "\n".join(statements) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--recovery-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text())
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise RuntimeError("Calibre Marvin highlight plan format/version mismatch")
    users = run_postgres_query("SELECT id FROM auth.users")
    if users != [plan["userId"]]:
        raise RuntimeError("Readest must have exactly the one auth user the plan was built for")

    hashes = [book["bookHash"] for book in plan["books"] if book["notes"]]
    hash_list = ",".join(f"'{h}'" for h in hashes)
    live = set(run_postgres_query(
        f"SELECT book_hash FROM public.books WHERE user_id='{plan['userId']}' "
        f"AND deleted_at IS NULL AND book_hash IN ({hash_list})"
    ))
    missing = [book["title"] for book in plan["books"] if book["notes"] and book["bookHash"] not in live]
    if missing:
        raise RuntimeError(f"Target books are no longer live in Readest: {missing}")

    planned = {note["id"] for book in plan["books"] for note in book["notes"]}
    existing = set(run_postgres_query(
        f"SELECT id FROM public.book_notes WHERE user_id='{plan['userId']}' "
        f"AND book_hash IN ({hash_list}) AND id LIKE 'calibre-marvin-%'"
    ))
    applied_at = int(time.time() * 1000)
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "books": len(hashes),
        "plannedNotes": len(planned),
        "newNotes": len(planned - existing),
        "alreadyImported": len(planned & existing),
    }

    # Rehearse first in every mode: the whole transaction must execute cleanly.
    apply_postgres_sql(build_notes_sql(plan, applied_at, "ROLLBACK"))
    report["rehearsal"] = "ok (rolled back)"
    if not args.apply:
        print(json.dumps(report, indent=1))
        return 0

    args.recovery_dir.mkdir(parents=True, exist_ok=True)
    recovery = args.recovery_dir / f"book_notes-before-{applied_at}.csv"
    dump = subprocess.run(
        ["docker", "exec", "readest-db", "psql", "-U", "postgres", "-d", "postgres", "-c",
         (f"COPY (SELECT * FROM public.book_notes WHERE user_id='{plan['userId']}' "
          f"AND book_hash IN ({hash_list})) TO STDOUT WITH (FORMAT csv, HEADER)")],
        check=True, capture_output=True,
    )
    recovery.write_bytes(dump.stdout)
    report["recoveryPoint"] = str(recovery)

    apply_postgres_sql(build_notes_sql(plan, applied_at, "COMMIT"))

    rows = {
        line.split("\t")[0]: line.split("\t")[1:]
        for line in run_postgres_query(
            f"SELECT id || chr(9) || cfi || chr(9) || (deleted_at IS NULL)::text FROM public.book_notes "
            f"WHERE user_id='{plan['userId']}' AND book_hash IN ({hash_list}) AND id LIKE 'calibre-marvin-%'"
        )
    }
    expected = {note["id"]: note["cfi"] for book in plan["books"] for note in book["notes"]}
    failures = [
        note_id for note_id, cfi in expected.items()
        if note_id not in rows or rows[note_id] != [cfi, "true"]
    ]
    report["verified"] = len(expected) - len(failures)
    report["verificationFailures"] = failures
    print(json.dumps(report, indent=1))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
