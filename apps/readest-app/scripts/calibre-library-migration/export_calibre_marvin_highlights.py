#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3>=1.40,<2"]
# ///
"""Stage Marvin highlights from a Calibre library for import into existing Readest books.

Marvin (an iOS reader) wrote its highlights into Calibre's `mm_annotations`
comments column as HTML: entries separated by `---`, each a `>` quote followed by
an optional `**Page N**` marker and an optional free-text note. Marvin keeps no
CFIs, IDs, colours or timestamps, so the planner must locate every quote by text.

For each annotated Calibre book this matches the live Readest edition (exact
partial MD5 of a Calibre format file, else normalised title), downloads that
exact Readest file from MinIO, and records the book's existing note texts so the
planner can skip highlights Readest already has. Calibre is opened read-only.

S3 credentials come from READEST_S3_ACCESS_KEY_ID / READEST_S3_SECRET_ACCESS_KEY.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
import uuid
from pathlib import Path

STAGE_FORMAT = "readest-calibre-marvin-highlights"
STAGE_VERSION = 1
MARVIN_COLUMN_LABEL = "mm_annotations"
# Stable namespace so re-exports derive the same note IDs (idempotent imports).
MARVIN_NAMESPACE = uuid.UUID("5c0f4a52-7b0e-4d8e-9a43-6f1d2c3b9e10")
PAGE_MARKER = re.compile(r"^\*\*Page (\d+)\*\*$")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--s3-endpoint", default="http://127.0.0.1:39000")
    parser.add_argument("--bucket", default="readest-files")
    return parser.parse_args()


def run_postgres_query(sql: str) -> list[list[str]]:
    """Run a read-only query in the Readest database container; rows are tab-separated."""
    result = subprocess.run(
        ["docker", "exec", "readest-db", "psql", "-U", "postgres", "-d", "postgres",
         "-AtF", "\t", "-c", sql],
        check=True, text=True, capture_output=True,
    )
    return [line.split("\t") for line in result.stdout.splitlines() if line]


def partial_md5(path: Path) -> str:
    """Mirror src/utils/md5.ts partialMD5, including JavaScript's 32-bit `<<`."""
    size, digest = path.stat().st_size, hashlib.md5()
    with path.open("rb") as source:
        for index in range(-1, 11):
            offset = (1024 << ((2 * index) & 31)) & 0xFFFFFFFF
            offset = offset - (1 << 32) if offset & 0x80000000 else offset
            start = min(size, offset)
            if start >= size:
                break
            source.seek(start)
            digest.update(source.read(min(start + 1024, size) - start))
    return digest.hexdigest()


def normalize_title(title: str) -> str:
    """Fold a title to its main-title letters so subtitle and punctuation drift still match."""
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    folded = re.split(r"\s*[:(\[]", folded)[0]
    folded = re.sub(r"^(the|a|an)\s+", "", folded)
    return re.sub(r"[^a-z0-9]+", "", folded)


def html_paragraphs(value: str) -> list[str]:
    """Return the text of each <p>, with blank paragraphs kept as '' separators."""
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", value, flags=re.DOTALL)
    return [html.unescape(re.sub(r"<[^>]+>", "", p)).replace("\xa0", " ").strip() for p in paragraphs]


def parse_marvin_annotations(calibre_id: int, value: str) -> tuple[list[str], list[dict]]:
    """Split one Marvin column value into the book-level preamble and its quote entries."""
    preamble: list[str] = []
    entries: list[dict] = []
    blocks: list[list[str]] = [[]]
    for paragraph in html_paragraphs(value):
        if paragraph == "---":
            blocks.append([])
        else:
            blocks[-1].append(paragraph)
    # The block before the first `---` is usually a review or header, but some
    # entries start with a quote and no separator at all.
    first_quote = next((i for i, line in enumerate(blocks[0]) if line.startswith(">")), len(blocks[0]))
    preamble = [line for line in blocks[0][:first_quote] if line]
    blocks[0] = blocks[0][first_quote:]
    for block in blocks:
        lines = list(block)
        while lines and not lines[0]:
            lines.pop(0)
        if not lines:
            continue
        if not lines or not lines[0].startswith(">"):
            # Not a quote: keep it so nothing is silently dropped.
            preamble.extend(line for line in lines if line)
            continue
        first = lines.pop(0)[1:].strip()
        continuation: list[str] = []
        # A `**Page N**` marker can follow the quote with no blank line between.
        while lines and lines[0] and not PAGE_MARKER.match(lines[0]):
            line = lines.pop(0)
            continuation.append(line[1:].strip() if line.startswith(">") else line)
        page = None
        note_lines: list[str] = []
        for line in lines:
            if not line:
                continue
            marker = PAGE_MARKER.match(line)
            if marker:
                page = int(marker.group(1))
            else:
                note_lines.append(line)
        quote = " ".join([first, *continuation])
        entries.append({
            "id": str(uuid.uuid5(MARVIN_NAMESPACE, f"{calibre_id}\n{quote}")),
            "quote": quote,
            "firstParagraph": first,
            "continuation": continuation,
            "note": "\n\n".join(note_lines),
            "page": page,
        })
    return preamble, entries


def main() -> int:
    args = parse_arguments()
    library_root = args.metadata_db.parent
    output = args.output_dir
    (output / "books").mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(f"file:{args.metadata_db}?mode=ro", uri=True)

    column = connection.execute(
        "SELECT id FROM custom_columns WHERE label=?", (MARVIN_COLUMN_LABEL,)
    ).fetchone()
    if not column:
        raise RuntimeError(f"Calibre library has no {MARVIN_COLUMN_LABEL} column")

    users = run_postgres_query("SELECT id FROM auth.users")
    if len(users) != 1:
        raise RuntimeError(f"Expected exactly one Readest auth user, found {len(users)}")
    user_id = users[0][0]
    live = run_postgres_query(
        "SELECT book_hash, coalesce(format,''), coalesce(title,''), coalesce(source_title,''), "
        "coalesce(meta_hash,'') FROM public.books "
        f"WHERE user_id='{user_id}' AND deleted_at IS NULL"
    )
    by_hash = {row[0]: row for row in live}
    by_title: dict[str, list[list[str]]] = {}
    for row in live:
        for title in {row[2], row[3]}:
            if normalize_title(title):
                by_title.setdefault(normalize_title(title), []).append(row)
    stored = {
        row[0]: row[1]
        for row in run_postgres_query(
            "SELECT book_hash, file_key FROM public.files WHERE deleted_at IS NULL "
            f"AND user_id='{user_id}' AND file_key NOT LIKE '%/cover.png'"
        )
    }

    import boto3  # deferred so --help works without the dependency resolved

    s3 = boto3.client(
        "s3",
        endpoint_url=args.s3_endpoint,
        region_name="us-east-1",
        aws_access_key_id=os.environ["READEST_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["READEST_S3_SECRET_ACCESS_KEY"],
    )

    books, skipped = [], []
    rows = connection.execute(
        f"SELECT b.id, b.title, b.path, c.value FROM custom_column_{column[0]} c "
        "JOIN books b ON b.id=c.book ORDER BY b.id"
    ).fetchall()
    for calibre_id, title, path, value in rows:
        author = connection.execute(
            "SELECT group_concat(a.name, ' & ') FROM books_authors_link l "
            "JOIN authors a ON a.id=l.author WHERE l.book=?", (calibre_id,)
        ).fetchone()[0] or ""
        preamble, entries = parse_marvin_annotations(calibre_id, value)
        if not entries:
            skipped.append({"calibreId": calibre_id, "title": title, "reason": "no quotes", "preamble": preamble})
            continue

        match, matched_by = None, None
        for fmt, name in connection.execute("SELECT format, name FROM data WHERE book=?", (calibre_id,)):
            candidate = library_root / path / f"{name}.{fmt.lower()}"
            if candidate.exists() and partial_md5(candidate) in by_hash:
                match, matched_by = by_hash[partial_md5(candidate)], "partial-md5"
                break
        if not match:
            candidates = by_title.get(normalize_title(title), [])
            candidates.sort(key=lambda row: row[1] != "EPUB")  # prefer an EPUB edition
            if candidates:
                match, matched_by = candidates[0], "title"
        if not match or match[0] not in stored:
            skipped.append({"calibreId": calibre_id, "title": title, "reason": "no live Readest edition with a stored file"})
            continue

        book_hash, book_format = match[0], match[1]
        file_key = stored[book_hash]
        staged = f"{book_hash}{Path(file_key).suffix}"
        target = output / "books" / staged
        if not target.exists():
            s3.download_file(args.bucket, file_key, str(target))
        if partial_md5(target) != book_hash:
            raise RuntimeError(f"Downloaded Readest file for {title!r} does not hash to {book_hash}")

        existing = [
            row[0]
            for row in run_postgres_query(
                "SELECT coalesce(text,'') FROM public.book_notes "
                f"WHERE user_id='{user_id}' AND book_hash='{book_hash}' AND deleted_at IS NULL "
                "AND type='annotation'"
            )
        ]
        books.append({
            "calibreId": calibre_id,
            "title": title,
            "author": author,
            "bookHash": book_hash,
            "metaHash": match[4] or None,
            "format": book_format,
            "readestTitle": match[2],
            "matchedBy": matched_by,
            "stagedFilename": staged,
            "preamble": preamble,
            "existingNoteTexts": existing,
            "entries": entries,
        })

    stage = {
        "format": STAGE_FORMAT,
        "version": STAGE_VERSION,
        "exportedAt": int(time.time() * 1000),
        "userId": user_id,
        "books": books,
        "skipped": skipped,
    }
    (output / "marvin-highlights.json").write_text(json.dumps(stage, ensure_ascii=False, indent=1))
    print(json.dumps({
        "books": len(books),
        "entries": sum(len(book["entries"]) for book in books),
        "skipped": [(item["title"], item["reason"]) for item in skipped],
        "matchedBy": {
            key: sum(book["matchedBy"] == key for book in books) for key in ("partial-md5", "title")
        },
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
