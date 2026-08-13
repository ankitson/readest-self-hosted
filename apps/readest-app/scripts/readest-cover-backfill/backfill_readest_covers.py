#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3>=1.40,<2", "httpx>=0.28,<1", "pillow>=11,<12", "pymupdf>=1.26,<2"]
# ///
"""Prepare and apply missing Readest covers without changing reading dates."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import posixpath
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import boto3
import httpx
import pymupdf
from botocore.config import Config
from PIL import Image

PREFERRED_COVER_URLS = {
    # Exact publisher/catalog covers selected after visual review of the full
    # contact sheet; the local files contain only a plain title page or no file.
    "888ac991d71294d7c112b1432c272a0b": "https://covers.openlibrary.org/b/isbn/9780073523408-L.jpg?default=false",
    "335d8ae6086de16d8b9ef1fc221a9fd9": "https://cdn.penguin.co.uk/dam-assets/books/9780141043883/9780141043883-jacket-large.jpg",
}


def read_environment_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE configuration without exposing credential values."""
    result: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def run_postgres_query(sql: str) -> list[str]:
    """Run a PostgreSQL query inside the local Readest database container."""
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
    """Apply a guarded transaction without echoing row contents."""
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
    encoded = base64.b64encode(value.encode()).decode()
    return f"convert_from(decode('{encoded}', 'base64'), 'UTF8')"


def partial_md5(path: Path) -> str:
    """Compute the sampled MD5 used by Readest for coverHash."""
    size = path.stat().st_size
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for exponent in range(-1, 11):
            start = 0 if exponent == -1 else min(size, 1024 << (2 * exponent))
            if start >= size:
                break
            source.seek(start)
            digest.update(source.read(min(1024, size - start)))
    return digest.hexdigest()


def s3_client(environment: dict[str, str]) -> Any:
    return boto3.client(
        "s3",
        endpoint_url="http://127.0.0.1:39000",
        aws_access_key_id=environment["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=environment["S3_SECRET_ACCESS_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )


def load_coverless_books() -> list[dict[str, Any]]:
    """Load live books whose cover file or cover version is missing."""
    rows = run_postgres_query(
        "WITH live AS (SELECT b.*,CASE WHEN json_typeof(b.metadata)='string' "
        "THEN (b.metadata #>> '{}')::json ELSE b.metadata END AS m FROM public.books b "
        "WHERE b.deleted_at IS NULL) SELECT json_build_object("
        "'userId',user_id,'hash',book_hash,'title',title,'author',author,'format',format,"
        "'identifier',m->>'identifier','isbn',m->>'isbn','coverHash',cover_hash,"
        "'bookKey',(SELECT file_key FROM public.files f WHERE f.user_id=live.user_id "
        "AND f.book_hash=live.book_hash AND f.deleted_at IS NULL AND f.file_key !~ '/cover\\.png$' LIMIT 1),"
        "'coverKey',(SELECT file_key FROM public.files f WHERE f.user_id=live.user_id "
        "AND f.book_hash=live.book_hash AND f.deleted_at IS NULL AND f.file_key ~ '/cover\\.png$' LIMIT 1)) "
        "FROM live WHERE COALESCE(cover_hash,'')='' OR NOT EXISTS(SELECT 1 FROM public.files f "
        "WHERE f.user_id=live.user_id AND f.book_hash=live.book_hash AND f.deleted_at IS NULL "
        "AND f.file_key ~ '/cover\\.png$') ORDER BY title"
    )
    return [json.loads(row) for row in rows]


def normalize_image(raw: bytes, destination: Path) -> None:
    """Validate and normalize a cover to a reasonably sized RGB PNG."""
    with Image.open(io.BytesIO(raw)) as source:
        source.load()
        if source.width < 100 or source.height < 100:
            raise ValueError(f"cover is too small: {source.width}x{source.height}")
        image = source.convert("RGB")
        image.thumbnail((1600, 2000), Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "PNG", optimize=True)


def find_epub_cover(epub_path: Path) -> tuple[bytes, str] | None:
    """Extract the cover declared by EPUB2/EPUB3 metadata, with a filename fallback."""
    with zipfile.ZipFile(epub_path) as archive:
        names = set(archive.namelist())
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        rootfile = next(
            node for node in container.iter() if node.tag.endswith("rootfile")
        )
        opf_path = rootfile.attrib["full-path"]
        opf_dir = posixpath.dirname(opf_path)
        opf = ElementTree.fromstring(archive.read(opf_path))
        manifest: dict[str, tuple[str, str, str]] = {}
        cover_id: str | None = None
        for node in opf.iter():
            if node.tag.endswith("item"):
                manifest[node.attrib.get("id", "")] = (
                    node.attrib.get("href", ""),
                    node.attrib.get("media-type", ""),
                    node.attrib.get("properties", ""),
                )
                if "cover-image" in node.attrib.get("properties", "").split():
                    cover_id = node.attrib.get("id")
            elif (
                node.tag.endswith("meta")
                and node.attrib.get("name", "").lower() == "cover"
            ):
                cover_id = node.attrib.get("content")
        candidates: list[str] = []
        if cover_id and cover_id in manifest:
            candidates.append(manifest[cover_id][0])
        candidates.extend(
            href
            for href, media_type, _properties in manifest.values()
            if media_type.startswith("image/") and "cover" in href.lower()
        )
        for href in candidates:
            path = posixpath.normpath(posixpath.join(opf_dir, href.split("#", 1)[0]))
            if path in names:
                return archive.read(path), f"embedded:{path}"
    return None


def render_pdf_cover(pdf_path: Path) -> tuple[bytes, str]:
    """Render the first PDF page, which is the edition's own cover/title page."""
    document = pymupdf.open(pdf_path)
    try:
        pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png"), "embedded:first-pdf-page"
    finally:
        document.close()


def fetch_web_cover(
    book: dict[str, Any], client: httpx.Client
) -> tuple[bytes, str] | None:
    """Fetch an ISBN/Gutenberg/Open Library cover when the book embeds none."""
    isbn = re.sub(r"[^0-9Xx]", "", str(book.get("isbn") or ""))
    urls: list[str] = []
    if len(isbn) in {10, 13}:
        urls.append(f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false")
    identifier = str(book.get("identifier") or "")
    gutenberg = re.search(r"(?:ebooks/|gutenberg\.org/)(\d+)|^(\d+)$", identifier)
    if gutenberg:
        book_id = next(group for group in gutenberg.groups() if group)
        urls.append(
            f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.cover.medium.jpg"
        )
    for url in urls:
        response = client.get(url)
        if response.status_code == 200 and response.headers.get(
            "content-type", ""
        ).startswith("image/"):
            return response.content, url

    response = client.get(
        "https://openlibrary.org/search.json",
        params={
            "title": book["title"],
            "author": book["author"],
            "limit": 10,
            "fields": "cover_i,title,author_name",
        },
    )
    response.raise_for_status()
    for result in response.json().get("docs", []):
        if result.get("cover_i"):
            url = f"https://covers.openlibrary.org/b/id/{result['cover_i']}-L.jpg?default=false"
            cover = client.get(url)
            if cover.status_code == 200:
                return cover.content, url
    return None


def prepare_covers(output_dir: Path, environment: dict[str, str]) -> dict[str, Any]:
    """Materialize exact embedded covers, then web fallbacks, and write a reviewed plan."""
    books = load_coverless_books()
    s3 = s3_client(environment)
    bucket = environment["S3_BUCKET_NAME"]
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    covers_dir = output_dir / "covers"
    with tempfile.TemporaryDirectory(prefix="readest-cover-source-") as temp_name:
        temp_dir = Path(temp_name)
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Readest metadata cleanup"},
        ) as web:
            for index, book in enumerate(books, 1):
                destination = covers_dir / f"{book['hash']}.png"
                try:
                    source: tuple[bytes, str] | None = None
                    if book.get("coverKey"):
                        source = (
                            s3.get_object(Bucket=bucket, Key=book["coverKey"])[
                                "Body"
                            ].read(),
                            "existing-cloud-cover",
                        )
                    if source is None and book["hash"] in PREFERRED_COVER_URLS:
                        preferred_url = PREFERRED_COVER_URLS[book["hash"]]
                        response = web.get(preferred_url)
                        response.raise_for_status()
                        source = (response.content, preferred_url)
                    if source is None and book.get("bookKey"):
                        extension = ".pdf" if book["format"] == "PDF" else ".epub"
                        local_book = temp_dir / f"{book['hash']}{extension}"
                        s3.download_file(bucket, book["bookKey"], str(local_book))
                        source = (
                            render_pdf_cover(local_book)
                            if book["format"] == "PDF"
                            else find_epub_cover(local_book)
                        )
                    if source is None:
                        source = fetch_web_cover(book, web)
                    if source is None:
                        raise RuntimeError("no embedded or web cover found")
                    normalize_image(source[0], destination)
                    records.append(
                        {
                            "hash": book["hash"],
                            "title": book["title"],
                            "source": source[1],
                            "path": str(destination.relative_to(output_dir)),
                            "size": destination.stat().st_size,
                            "coverHash": partial_md5(destination),
                        }
                    )
                except Exception as error:  # noqa: BLE001 - report every unresolved book
                    failures.append(
                        {
                            "hash": book["hash"],
                            "title": book["title"],
                            "error": str(error),
                        }
                    )
                print(f"Prepared {index}/{len(books)} cover candidates", flush=True)
    plan = {
        "format": "readest-cover-backfill",
        "version": 1,
        "books": records,
        "failures": failures,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cover-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    )
    return plan


def apply_cover_plan(
    plan: dict[str, Any], output_dir: Path, environment: dict[str, str]
) -> None:
    """Upload covers, index them, stamp cover LWW fields, and verify every object."""
    if plan.get("failures"):
        raise RuntimeError(f"cover plan has {len(plan['failures'])} unresolved books")
    users = run_postgres_query("SELECT id::text FROM auth.users ORDER BY id")
    if len(users) != 1:
        raise RuntimeError(f"expected one Readest user, found {len(users)}")
    user_id = users[0]
    s3 = s3_client(environment)
    bucket = environment["S3_BUCKET_NAME"]
    statements = ["BEGIN;"]
    for book in plan["books"]:
        cover = output_dir / book["path"]
        if (
            cover.stat().st_size != book["size"]
            or partial_md5(cover) != book["coverHash"]
        ):
            raise RuntimeError(f"cover plan fingerprint mismatch: {book['hash']}")
        key = f"{user_id}/Readest/Books/{book['hash']}/cover.png"
        s3.upload_file(str(cover), bucket, key, ExtraArgs={"ContentType": "image/png"})
        head = s3.head_object(Bucket=bucket, Key=key)
        if int(head["ContentLength"]) != book["size"]:
            raise RuntimeError(f"uploaded cover size mismatch: {book['hash']}")
        statements.append(
            "UPDATE public.books SET "
            f"cover_hash={sql_text(book['coverHash'])},cover_updated_at=clock_timestamp() "
            f"WHERE user_id={sql_text(user_id)}::uuid AND book_hash={sql_text(book['hash'])} AND deleted_at IS NULL;"
        )
        statements.append(
            "INSERT INTO public.files (user_id,book_hash,file_key,file_size,created_at,updated_at,deleted_at) VALUES ("
            f"{sql_text(user_id)}::uuid,{sql_text(book['hash'])},{sql_text(key)},{book['size']},clock_timestamp(),clock_timestamp(),NULL) "
            "ON CONFLICT (file_key) DO UPDATE SET file_size=EXCLUDED.file_size,updated_at=EXCLUDED.updated_at,deleted_at=NULL;"
        )
    statements.append("COMMIT;")
    apply_postgres_sql("\n".join(statements))
    remaining = load_coverless_books()
    if remaining:
        raise RuntimeError(f"{len(remaining)} live books remain coverless after apply")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    environment = read_environment_file(args.env_file)
    required = ("S3_BUCKET_NAME", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    if any(not environment.get(key) for key in required):
        raise RuntimeError("Readest S3 environment is incomplete")
    plan_path = args.output_dir / "cover-plan.json"
    plan = (
        json.loads(plan_path.read_text())
        if args.apply and plan_path.exists()
        else prepare_covers(args.output_dir, environment)
    )
    print(
        json.dumps(
            {"planned": len(plan["books"]), "failures": len(plan["failures"])}, indent=2
        )
    )
    if args.apply:
        apply_cover_plan(plan, args.output_dir, environment)
        print(f"Verified {len(plan['books'])} uploaded and indexed covers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
