#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# ///
"""Plan, apply, and verify a one-off Readest metadata cleanup."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
# Kept out of git (see /tmp/ in .gitignore): the corrections file lists real
# book titles and ISBNs from a personal library, and this repo is public.
DEFAULT_CORRECTIONS = REPO_ROOT / "tmp" / "readest-metadata-corrections.json"
IMMUTABLE_TABLES = ("book_configs", "book_notes", "files", "stat_books", "stat_pages")


def run_postgres_query(sql: str) -> list[str]:
    """Run a PostgreSQL query in the dedicated local Readest container."""
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
    # JSON metadata can legitimately contain Unicode line-separator characters.
    # Split only on the row delimiter emitted by psql, not every Unicode line break.
    return [line for line in result.stdout.split("\n") if line]


def apply_postgres_sql(sql: str) -> None:
    """Apply one transaction while keeping row data out of command output."""
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
    """Encode arbitrary UTF-8 as a safe PostgreSQL text expression."""
    encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    return f"convert_from(decode('{encoded}', 'base64'), 'UTF8')"


def metadata_object(value: Any) -> dict[str, Any]:
    """Decode Readest's JSON-string metadata representation."""
    while isinstance(value, str):
        value = json.loads(value)
    return copy.deepcopy(value or {})


def author_name(value: Any) -> str:
    """Return the display name from Readest's supported author shapes."""
    if isinstance(value, dict):
        return str(value.get("name") or "")
    if isinstance(value, list):
        return "; ".join(author_name(item) for item in value if author_name(item))
    return str(value or "")


def natural_author_list(value: str) -> str:
    """Convert semicolon-separated author names to a natural English display list."""
    names = [
        part.strip().rstrip(";")
        for part in value.split(";")
        if part.strip().rstrip(";")
    ]
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def valid_isbn(value: Any) -> str | None:
    """Return a checksum-valid ISBN-10/13 stripped of punctuation."""
    compact = re.sub(r"[^0-9Xx]", "", str(value or ""))
    if len(compact) == 10:
        total = sum(
            (10 - index) * (10 if char.upper() == "X" else int(char))
            for index, char in enumerate(compact)
        )
        return compact.upper() if total % 11 == 0 else None
    if len(compact) == 13:
        total = sum(
            int(char) * (1 if index % 2 == 0 else 3)
            for index, char in enumerate(compact)
        )
        return compact if total % 10 == 0 else None
    return None


def load_live_books() -> list[dict[str, Any]]:
    """Load every non-deleted Readest book with timestamps expressed in milliseconds."""
    rows = run_postgres_query(
        "SELECT json_build_object("
        "'userId',user_id,'hash',book_hash,'title',title,'author',author,"
        "'updatedAt',round(extract(epoch from updated_at)*1000),"
        "'lastReadAt',round(extract(epoch from last_read_at)*1000),"
        "'metadataUpdatedAt',round(extract(epoch from metadata_updated_at)*1000),"
        "'metadata',metadata) FROM public.books WHERE deleted_at IS NULL ORDER BY book_hash"
    )
    return [json.loads(row) for row in rows]


def database_fingerprints() -> dict[str, str]:
    """Fingerprint all state that this metadata-only migration must not mutate."""
    fingerprints: dict[str, str] = {}
    immutable_books = run_postgres_query(
        "SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text),'' ORDER BY book_hash)),'') FROM ("
        'SELECT user_id,book_hash,meta_hash,format,source_title,"group",tags,created_at,deleted_at,'
        "uploaded_at,progress,reading_status,reading_status_updated_at,cover_hash,cover_updated_at,group_id,group_name "
        "FROM public.books ORDER BY book_hash) x"
    )
    fingerprints["booksImmutable"] = immutable_books[0]
    for table in IMMUTABLE_TABLES:
        digest = run_postgres_query(
            f"SELECT COALESCE(md5(string_agg(md5(row_to_json(x)::text),'' ORDER BY md5(row_to_json(x)::text))),'') "
            f"FROM (SELECT * FROM public.{table}) x"
        )
        fingerprints[table] = digest[0]
    return fingerprints


def build_cleanup_plan(
    books: list[dict[str, Any]], corrections: dict[str, Any]
) -> list[dict[str, Any]]:
    """Apply deterministic global normalization and reviewed per-book corrections in memory."""
    by_hash = {book["hash"]: book for book in books}
    unknown = sorted(set(corrections["books"]) - set(by_hash))
    if unknown:
        raise RuntimeError(
            f"Correction manifest references missing live book hashes: {', '.join(unknown)}"
        )

    plans: list[dict[str, Any]] = []
    normalizations = corrections.get("normalizations", {})
    restore_dates = corrections.get("restoreUpdatedAt", {})
    for book in books:
        before = metadata_object(book["metadata"])
        after = copy.deepcopy(before)
        title = str(after.get("title") or book["title"] or "").strip()

        if (
            normalizations.get("splitTitleSubtitleAtFirstColon")
            and ":" in title
            and not after.get("subtitle")
        ):
            main_title, subtitle = (part.strip() for part in title.split(":", 1))
            if main_title and subtitle:
                after["title"] = main_title
                after["subtitle"] = subtitle

        if normalizations.get("normalizeSemicolonSeparatedAuthors"):
            display_author = author_name(after.get("author") or book.get("author"))
            normalized_author = natural_author_list(display_author)
            if normalized_author != display_author:
                after["author"] = normalized_author

        if (
            normalizations.get("fillIdentifierFromIsbn")
            and not str(after.get("identifier") or "").strip()
        ):
            isbn = valid_isbn(after.get("isbn"))
            if isbn:
                after["isbn"] = isbn
                after["identifier"] = f"urn:isbn:{isbn}"

        correction = corrections["books"].get(book["hash"])
        if correction:
            final_manifest_title = correction.get("set", {}).get(
                "title", correction["expectedTitle"]
            )
            acceptable_titles = {correction["expectedTitle"], final_manifest_title}
            if (
                normalizations.get("splitTitleSubtitleAtFirstColon")
                and ":" in correction["expectedTitle"]
            ):
                acceptable_titles.add(
                    correction["expectedTitle"].split(":", 1)[0].strip()
                )
            if title not in acceptable_titles:
                raise RuntimeError(
                    f"Title guard failed for {book['hash']}: expected {correction['expectedTitle']!r}, found {title!r}"
                )
            after.update(correction.get("set", {}))
            for key in correction.get("remove", []):
                after.pop(key, None)

        final_title = str(after.get("title") or book["title"] or "").strip()
        final_author = author_name(after.get("author") or book.get("author")).strip()
        if not final_title or not final_author or "UnknownAuthor" in final_author:
            raise RuntimeError(
                f"Invalid final title/author for {book['hash']}: {final_title!r} / {final_author!r}"
            )

        changes: dict[str, dict[str, Any]] = {}
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                changes[f"metadata.{key}"] = {
                    "before": before.get(key),
                    "after": after.get(key),
                }
        if book["title"] != final_title:
            changes["books.title"] = {"before": book["title"], "after": final_title}
        if book["author"] != final_author:
            changes["books.author"] = {"before": book["author"], "after": final_author}

        restored_at = restore_dates.get(book["hash"])
        current_last_read = int(book.get("lastReadAt") or book["updatedAt"])
        if restored_at is not None and current_last_read != int(restored_at):
            changes["books.lastReadAt"] = {
                "before": current_last_read,
                "after": int(restored_at),
            }

        if changes:
            plans.append(
                {
                    "hash": book["hash"],
                    "beforeTitle": title,
                    "title": final_title,
                    "author": final_author,
                    "metadata": after,
                    "originalUpdatedAt": int(book["updatedAt"]),
                    "updatedAt": int(book["updatedAt"]),
                    "lastReadAt": int(restored_at)
                    if restored_at is not None
                    else current_last_read,
                    "changes": changes,
                }
            )
    return plans


def plan_sql(plans: list[dict[str, Any]], user_id: str) -> str:
    """Build a guarded transaction that changes metadata but preserves reading timestamps."""
    statements = ["BEGIN;"]
    for plan in plans:
        metadata_json = json.dumps(
            plan["metadata"], ensure_ascii=False, separators=(",", ":")
        )
        statements.append(
            "DO $cleanup$ BEGIN UPDATE public.books SET "
            f"title={sql_text(plan['title'])},author={sql_text(plan['author'])},"
            f"metadata=to_jsonb({sql_text(metadata_json)}),metadata_updated_at=clock_timestamp(),"
            f"last_read_at=to_timestamp({plan['lastReadAt']} / 1000.0) "
            f"WHERE user_id={sql_text(user_id)}::uuid AND book_hash={sql_text(plan['hash'])} "
            f"AND deleted_at IS NULL AND round(extract(epoch from updated_at)*1000)={plan['originalUpdatedAt']}; "
            "IF NOT FOUND THEN RAISE EXCEPTION 'guarded metadata update failed'; END IF; END $cleanup$;"
        )
    statements.append("COMMIT;")
    return "\n".join(statements)


def summarize_plan(plans: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a compact machine-readable and human-reviewable migration report."""
    field_counts: dict[str, int] = {}
    for plan in plans:
        for field in plan["changes"]:
            field_counts[field] = field_counts.get(field, 0) + 1
    return {
        "changedBooks": len(plans),
        "changedFields": dict(sorted(field_counts.items())),
        "books": plans,
    }


def verify_applied_plan(
    plans: list[dict[str, Any]],
    before_books: list[dict[str, Any]],
    after_books: list[dict[str, Any]],
    fingerprints_before: dict[str, str],
    fingerprints_after: dict[str, str],
) -> None:
    """Prove metadata landed while reading state, covers, files, notes, and stats stayed fixed."""
    if fingerprints_before != fingerprints_after:
        changed = sorted(
            key
            for key in fingerprints_before
            if fingerprints_before[key] != fingerprints_after.get(key)
        )
        raise RuntimeError(
            f"Immutable database state changed unexpectedly: {', '.join(changed)}"
        )
    before_by_hash = {book["hash"]: book for book in before_books}
    after_by_hash = {book["hash"]: book for book in after_books}
    plan_by_hash = {plan["hash"]: plan for plan in plans}
    if set(before_by_hash) != set(after_by_hash):
        raise RuntimeError("Live book set changed during metadata cleanup")
    for plan in plans:
        actual = after_by_hash[plan["hash"]]
        if metadata_object(actual["metadata"]) != plan["metadata"]:
            raise RuntimeError(f"Metadata verification failed for {plan['hash']}")
        if int(actual["updatedAt"]) != plan["updatedAt"]:
            raise RuntimeError(f"Row timestamp verification failed for {plan['hash']}")
        if int(actual["lastReadAt"]) != plan["lastReadAt"]:
            raise RuntimeError(f"Date Read verification failed for {plan['hash']}")
    for book_hash, actual in after_by_hash.items():
        before = before_by_hash[book_hash]
        if int(actual["updatedAt"]) != int(before["updatedAt"]):
            raise RuntimeError(f"Unplanned row timestamp change for {book_hash}")
        if book_hash not in plan_by_hash and metadata_object(
            actual["metadata"]
        ) != metadata_object(before["metadata"]):
            raise RuntimeError(f"Unplanned metadata change for {book_hash}")
    if any(
        "UnknownAuthor"
        in author_name(
            metadata_object(book["metadata"]).get("author") or book["author"]
        )
        for book in after_books
    ):
        raise RuntimeError("UnknownAuthor remains after cleanup")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS)
    parser.add_argument(
        "--report", type=Path, help="Write the complete JSON diff report here"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply and verify; default is dry-run only"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    corrections = json.loads(args.corrections.read_text())
    if (
        corrections.get("format") != "readest-metadata-corrections"
        or corrections.get("version") != 1
    ):
        raise RuntimeError("Unsupported corrections manifest")
    books_before = load_live_books()
    users = {book["userId"] for book in books_before}
    if len(users) != 1:
        raise RuntimeError(
            f"Expected one Readest user among live books, found {len(users)}"
        )
    plans = build_cleanup_plan(books_before, corrections)
    report = summarize_plan(plans)
    report["mode"] = "apply" if args.apply else "dry-run"
    report["liveBooks"] = len(books_before)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("mode", "liveBooks", "changedBooks", "changedFields")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not args.apply:
        return 0

    fingerprints_before = database_fingerprints()
    apply_postgres_sql(plan_sql(plans, users.pop()))
    books_after = load_live_books()
    fingerprints_after = database_fingerprints()
    verify_applied_plan(
        plans, books_before, books_after, fingerprints_before, fingerprints_after
    )
    print(
        f"Verified {len(plans)} metadata updates; immutable reading, cover, note, file, and stats state is unchanged."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
