#!/usr/bin/env python3
"""Export selected Calibre books into an immutable Readest staging archive."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STAGE_FORMAT = "readest-calibre-book-stage"
STAGE_VERSION = 1
EXPECTED_BOOK_COUNT = 290


def parse_arguments() -> argparse.Namespace:
    """Parse paths for the read-only Calibre export and staging archive."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--categories", type=Path, required=True)
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    """Return the complete SHA-256 for one source file without modifying it."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_selected_book_rows(categories_path: Path) -> list[dict[str, str]]:
    """Load exactly the records whose reviewed publication-form category is Book."""
    with categories_path.open(encoding="utf-8", newline="") as source:
        rows = [row for row in csv.DictReader(source) if row["category"] == "Book"]
    if len(rows) != EXPECTED_BOOK_COUNT:
        raise RuntimeError(
            f"Calibre stage expected {EXPECTED_BOOK_COUNT} Book records, found {len(rows)}"
        )
    ids = [int(row["calibre_id"]) for row in rows]
    if len(set(ids)) != len(ids):
        raise RuntimeError("Calibre stage selection contains duplicate Calibre IDs")
    return rows


def scalar_query(
    connection: sqlite3.Connection, sql: str, calibre_id: int | None = None
) -> Any:
    """Return the first column from a one-row Calibre metadata query."""
    parameters = () if calibre_id is None else (calibre_id,)
    row = connection.execute(sql, parameters).fetchone()
    return row[0] if row else None


def list_query(
    connection: sqlite3.Connection, sql: str, calibre_id: int
) -> list[str]:
    """Return ordered non-empty strings from a Calibre metadata query."""
    return [str(row[0]) for row in connection.execute(sql, (calibre_id,)) if row[0]]


def load_calibre_book_metadata(
    connection: sqlite3.Connection, calibre_id: int
) -> dict[str, Any]:
    """Load raw bibliographic, custom-column, and reading-state provenance."""
    connection.row_factory = sqlite3.Row
    book_row = connection.execute(
        "SELECT id,title,sort,timestamp,pubdate,series_index,author_sort,isbn,lccn,"
        "path,uuid,has_cover,last_modified FROM books WHERE id=?",
        (calibre_id,),
    ).fetchone()
    if book_row is None:
        raise RuntimeError(f"Calibre metadata missing selected book ID {calibre_id}")

    authors = list_query(
        connection,
        "SELECT authors.name FROM books_authors_link "
        "JOIN authors ON authors.id=books_authors_link.author "
        "WHERE books_authors_link.book=? ORDER BY books_authors_link.id",
        calibre_id,
    )
    identifiers = {
        str(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT type,val FROM identifiers WHERE book=? ORDER BY type,val",
            (calibre_id,),
        )
    }
    tags = list_query(
        connection,
        "SELECT tags.name FROM books_tags_link JOIN tags ON tags.id=books_tags_link.tag "
        "WHERE books_tags_link.book=? ORDER BY tags.name",
        calibre_id,
    )
    languages = list_query(
        connection,
        "SELECT languages.lang_code FROM books_languages_link "
        "JOIN languages ON languages.id=books_languages_link.lang_code "
        "WHERE books_languages_link.book=? ORDER BY books_languages_link.item_order",
        calibre_id,
    )

    custom_columns = {
        "readStatus": scalar_query(
            connection,
            "SELECT custom_column_3.value FROM custom_column_3 JOIN books_custom_column_3_link link "
            "ON link.value=custom_column_3.id WHERE link.book=? LIMIT 1",
            calibre_id,
        ),
        "pageCount": scalar_query(
            connection, "SELECT value FROM custom_column_4 WHERE book=?", calibre_id
        ),
        "wordCount": scalar_query(
            connection, "SELECT value FROM custom_column_5 WHERE book=?", calibre_id
        ),
        "genre": list_query(
            connection,
            "SELECT custom_column_6.value FROM custom_column_6 JOIN books_custom_column_6_link link "
            "ON link.value=custom_column_6.id WHERE link.book=? ORDER BY custom_column_6.value",
            calibre_id,
        ),
        "type": scalar_query(
            connection,
            "SELECT custom_column_7.value FROM custom_column_7 JOIN books_custom_column_7_link link "
            "ON link.value=custom_column_7.id WHERE link.book=? LIMIT 1",
            calibre_id,
        ),
        "dateRead": scalar_query(
            connection, "SELECT value FROM custom_column_8 WHERE book=?", calibre_id
        ),
    }
    publisher = scalar_query(
        connection,
        "SELECT publishers.name FROM books_publishers_link "
        "JOIN publishers ON publishers.id=books_publishers_link.publisher "
        "WHERE books_publishers_link.book=? LIMIT 1",
        calibre_id,
    )
    series = scalar_query(
        connection,
        "SELECT series.name FROM books_series_link "
        "JOIN series ON series.id=books_series_link.series "
        "WHERE books_series_link.book=? LIMIT 1",
        calibre_id,
    )
    comments = scalar_query(
        connection, "SELECT text FROM comments WHERE book=?", calibre_id
    )

    result = dict(book_row)
    result.update(
        {
            "authors": authors,
            "identifiers": identifiers,
            "tags": tags,
            "languages": languages,
            "publisher": publisher,
            "series": series,
            "comments": comments,
            "customColumns": custom_columns,
        }
    )
    return result


def build_calibre_stage_archive(
    categories_path: Path, metadata_db_path: Path, output_zip_path: Path
) -> dict[str, Any]:
    """Create one atomic ZIP containing exact selected books, covers, and provenance."""
    if output_zip_path.exists():
        raise RuntimeError(f"Calibre stage output already exists: {output_zip_path}")
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_zip_path.with_suffix(output_zip_path.suffix + ".partial")
    if partial_path.exists():
        partial_path.unlink()

    selected_rows = load_selected_book_rows(categories_path)
    connection = sqlite3.connect(
        f"file:{metadata_db_path.resolve()}?mode=ro", uri=True
    )
    generated_at = datetime.now(UTC).isoformat()
    manifest: dict[str, Any] = {
        "format": STAGE_FORMAT,
        "version": STAGE_VERSION,
        "generatedAt": generated_at,
        "selection": {
            "category": "Book",
            "count": EXPECTED_BOOK_COUNT,
            "categoriesSha256": sha256_file(categories_path),
        },
        "source": {
            "metadataDatabaseSha256": sha256_file(metadata_db_path),
            "libraryUuid": scalar_query(
                connection, "SELECT uuid FROM library_id LIMIT 1"
            ),
        },
        "books": [],
    }
    try:
        with zipfile.ZipFile(
            partial_path,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
            strict_timestamps=False,
        ) as archive:
            for index, category_row in enumerate(selected_rows, start=1):
                calibre_id = int(category_row["calibre_id"])
                source_book_path = Path(category_row["preferred_path"])
                if not source_book_path.is_file():
                    raise RuntimeError(
                        f"Calibre stage source file missing for ID {calibre_id}"
                    )
                extension = source_book_path.suffix.lower().lstrip(".")
                expected_extension = category_row["preferred_format"].lower()
                if extension != expected_extension:
                    raise RuntimeError(
                        f"Calibre stage format mismatch for ID {calibre_id}: "
                        f"{extension!r} != {expected_extension!r}"
                    )

                archive_book_path = f"books/{calibre_id}.{extension}"
                book_sha256 = sha256_file(source_book_path)
                archive.write(source_book_path, archive_book_path)

                source_cover_path = source_book_path.parent / "cover.jpg"
                archive_cover_path: str | None = None
                cover_sha256: str | None = None
                cover_size: int | None = None
                if source_cover_path.is_file():
                    archive_cover_path = f"covers/{calibre_id}.jpg"
                    cover_sha256 = sha256_file(source_cover_path)
                    cover_size = source_cover_path.stat().st_size
                    archive.write(source_cover_path, archive_cover_path)

                manifest["books"].append(
                    {
                        "calibreId": calibre_id,
                        "category": category_row["category"],
                        "classificationConfidence": category_row[
                            "classification_confidence"
                        ],
                        "sourcePreferredPath": str(source_book_path),
                        "archiveBookPath": archive_book_path,
                        "format": category_row["preferred_format"],
                        "fileSize": source_book_path.stat().st_size,
                        "fileSha256": book_sha256,
                        "archiveCoverPath": archive_cover_path,
                        "coverSize": cover_size,
                        "coverSha256": cover_sha256,
                        "calibre": load_calibre_book_metadata(
                            connection, calibre_id
                        ),
                    }
                )
                if index % 25 == 0 or index == len(selected_rows):
                    print(
                        f"Calibre stage archived {index}/{len(selected_rows)} selected books.",
                        flush=True,
                    )

            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
                + "\n",
            )
        partial_path.replace(output_zip_path)
    except BaseException:
        if partial_path.exists():
            partial_path.unlink()
        raise
    finally:
        connection.close()
    return manifest


def main() -> int:
    """Export the reviewed Book category and print a non-sensitive summary."""
    arguments = parse_arguments()
    manifest = build_calibre_stage_archive(
        arguments.categories, arguments.metadata_db, arguments.output_zip
    )
    print(
        json.dumps(
            {
                "result": "created",
                "books": len(manifest["books"]),
                "epubs": sum(book["format"] == "EPUB" for book in manifest["books"]),
                "pdfs": sum(book["format"] == "PDF" for book in manifest["books"]),
                "bookBytes": sum(book["fileSize"] for book in manifest["books"]),
                "covers": sum(bool(book["archiveCoverPath"]) for book in manifest["books"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
