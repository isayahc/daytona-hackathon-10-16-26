"""Download source documents and retain originals plus extracted text in SurrealDB."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from pypdf import PdfReader

CATEGORIES = ("weather", "climate", "defense", "energy")
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
BLOB_CHUNK_BYTES = 256 * 1024
TEXT_CHUNK_CHARS = 16000


class Database(Protocol):
    """Reuse the outreach CLI's parameterized SurrealDB connection."""

    def query(self, sql: str, variables: dict[str, Any] | None = None) -> list[Any]: ...


class VisibleText(HTMLParser):
    """Extract static HTML text without scripts, styling, or document head data."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"head", "script", "style", "template"}:
            self.hidden.append(tag)
        elif not self.hidden and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()
        elif not self.hidden and tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def source_url(value: str) -> str:
    """Accept HTTP(S) document locations and discard non-download fragments."""
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("Use an HTTP(S) document URL without embedded credentials")
    return urlunsplit(parsed._replace(fragment=""))


def download(url: str) -> tuple[bytes, dict[str, Any]]:
    """Download the response as-is, without browser or database credentials."""
    url = source_url(url)
    req = Request(url, headers={"User-Agent": "OutreachDocumentIngest/1.0",
                               "Accept-Encoding": "identity"})
    try:
        with urlopen(req, timeout=120) as response:
            resolved_url = source_url(response.geturl())
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_DOWNLOAD_BYTES:
                raise ValueError("Document exceeds the 50 MiB download limit")
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(data) > MAX_DOWNLOAD_BYTES:
                raise ValueError("Document exceeds the 50 MiB download limit")
            if not data:
                raise ValueError("Source returned an empty document")
            disposition = Message()
            disposition["Content-Disposition"] = response.headers.get("Content-Disposition", "")
            name = disposition.get_filename() or unquote(urlsplit(resolved_url).path).rsplit("/", 1)[-1]
            filename = re.sub(r"[^\w. -]", "_", name.replace("\\", "/").rsplit("/", 1)[-1])[:200]
            if filename in {"", ".", ".."}:
                filename = "document"
            metadata = {
                "source_url": url, "resolved_url": resolved_url,
                "source_host": urlsplit(url).hostname, "filename": filename,
                "content_type": response.headers.get_content_type(),
                "charset": response.headers.get_content_charset() or "utf-8-sig",
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
            }
            return data, metadata
    except HTTPError as error:
        error.close()
        raise ValueError(f"Document download failed (HTTP {error.code}); check the source URL and access") from None
    except (URLError, TimeoutError):
        raise ValueError("Document download failed; check the source URL and network connection") from None


def extract(data: bytes, metadata: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract PDF/static HTML/plain text; retain originals even if extraction fails."""
    mime = metadata["content_type"]
    extension = Path(metadata["filename"]).suffix.lower()
    detected = "unsupported"
    text = ""
    details: dict[str, Any] = {}
    try:
        if data.lstrip().startswith(b"%PDF-") or mime == "application/pdf":
            detected = "pdf"
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted and not reader.decrypt(""):
                return "", {"format": detected, "extraction_status": "encrypted"}
            details["page_count"] = len(reader.pages)
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        elif mime in {"text/html", "application/xhtml+xml"} or extension in {".html", ".htm"}:
            detected = "html"
            parser = VisibleText()
            parser.feed(data.decode(metadata["charset"], errors="replace"))
            parser.close()
            text = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
        elif (mime.startswith("text/") or mime in {"application/json", "application/xml"}
              or extension in {".txt", ".md", ".csv", ".json", ".xml"}):
            detected = "text"
            text = data.decode(metadata["charset"], errors="replace")
        else:
            return "", {"format": detected, "extraction_status": "unsupported"}
    except Exception as error:
        return "", {"format": detected, "extraction_status": "failed",
                    "extraction_error": type(error).__name__}
    details.update(format=detected, extraction_status="extracted" if text.strip() else "no_text")
    return text, details


class Documents:
    """Store bounded chunks, then publish a manifest only after all writes succeed."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Use the 64-character document key returned by ingest")
        rows = self.db.query("SELECT * FROM type::record('document:' + $key);", {"key": key})[0]
        if not rows:
            raise ValueError("Document not found")
        return rows[0]

    def ingest(self, url: str, category: str, title: str | None = None) -> dict[str, Any]:
        if category not in CATEGORIES:
            raise ValueError("Choose weather, climate, defense, or energy")
        # Verify connectivity/credentials before downloading a potentially large file.
        self.db.query("RETURN true;")
        data, metadata = download(url)
        digest = hashlib.sha256(data).hexdigest()
        identity = json.dumps([metadata["source_url"], category, digest])
        key = hashlib.sha256(identity.encode()).hexdigest()
        existing = self.db.query("SELECT * FROM type::record('document:' + $key);", {"key": key})[0]
        if existing:
            return {**existing[0], "already_stored": True}
        text, extraction = extract(data, metadata)
        blob_count = (len(data) + BLOB_CHUNK_BYTES - 1) // BLOB_CHUNK_BYTES
        text_count = (len(text) + TEXT_CHUNK_CHARS - 1) // TEXT_CHUNK_CHARS
        for position, start in enumerate(range(0, len(data), BLOB_CHUNK_BYTES)):
            # SurrealDB 2.x's decoder expects standard base64 without padding.
            encoded = base64.b64encode(data[start:start + BLOB_CHUNK_BYTES]).decode("ascii").rstrip("=")
            self.db.query(
                "UPSERT type::record('document_blob:' + $chunk_key) SET document_key = $key, "
                "position = $position, content = encoding::base64::decode($content) RETURN NONE;",
                {"chunk_key": f"{key}_{position}", "key": key, "position": position, "content": encoded})
        for position, start in enumerate(range(0, len(text), TEXT_CHUNK_CHARS)):
            self.db.query(
                "UPSERT type::record('document_text:' + $chunk_key) CONTENT $chunk RETURN NONE;",
                {"chunk_key": f"{key}_{position}", "chunk": {
                    "document_key": key, "position": position, "category": category,
                    "text": text[start:start + TEXT_CHUNK_CHARS]}})
        record = {
            **metadata, **extraction, "key": key, "title": title or metadata["filename"],
            "category": category, "sha256": digest, "size_bytes": len(data),
            "blob_chunks": blob_count, "text_chunks": text_count, "text_chars": len(text),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        self.db.query("UPSERT type::record('document:' + $key) CONTENT $document RETURN NONE;",
                      {"key": key, "document": record})
        return {**record, "already_stored": False}

    def list(self, category: str | None = None) -> list[Any]:
        return self.db.query(
            "SELECT * FROM document WHERE $category = NULL OR category = $category "
            "ORDER BY downloaded_at DESC LIMIT 100;", {"category": category})[0]

    def search(self, term: str, category: str | None = None) -> list[Any]:
        if not term.strip():
            raise ValueError("Search term cannot be empty")
        return self.db.query(
            "SELECT document_key, position, text FROM document_text WHERE "
            "document_key IN (SELECT VALUE key FROM document) "
            "AND ($category = NULL OR category = $category) "
            "AND string::contains(string::lowercase(text), string::lowercase($term)) LIMIT 20;",
            {"term": term, "category": category})[0]

    def export(self, key: str, output: Path, text: bool = False) -> dict[str, Any]:
        record = self.get(key)
        chunks = []
        for position in range(record["text_chunks" if text else "blob_chunks"]):
            if text:
                sql = "SELECT text FROM type::record('document_text:' + $chunk_key);"
            else:
                sql = ("SELECT encoding::base64::encode(content) AS content "
                       "FROM type::record('document_blob:' + $chunk_key);")
            rows = self.db.query(sql, {"chunk_key": f"{key}_{position}"})[0]
            if not rows:
                raise ValueError("Stored document is missing a chunk; export aborted")
            if text:
                chunks.append(rows[0]["text"].encode("utf-8"))
            else:
                encoded = rows[0]["content"]
                chunks.append(base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True))
        data = b"".join(chunks)
        expected = record["text_sha256" if text else "sha256"]
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Stored document checksum mismatch; export aborted")
        # Verify every chunk before writing, and avoid overwriting an existing file.
        try:
            with output.open("xb") as destination:
                destination.write(data)
        except FileExistsError:
            raise ValueError("Output file already exists; choose a new --output path") from None
        return {"key": key, "output": str(output), "size_bytes": len(data), "text": text}


def add_commands(commands: Any) -> None:
    parser = commands.add_parser("documents", help="Download documents; retain originals and extracted text")
    actions = parser.add_subparsers(dest="document_command", required=True)
    ingest = actions.add_parser("ingest", help="Download one public document into SurrealDB")
    ingest.add_argument("--url", required=True)
    ingest.add_argument("--category", choices=CATEGORIES, required=True)
    ingest.add_argument("--title")
    listing = actions.add_parser("list")
    listing.add_argument("--category", choices=CATEGORIES)
    show = actions.add_parser("show", help="Show document metadata and extraction status")
    show.add_argument("key")
    search = actions.add_parser("search", help="Case-insensitive substring search within text chunks")
    search.add_argument("term")
    search.add_argument("--category", choices=CATEGORIES)
    export = actions.add_parser("export", help="Restore the original file or extracted UTF-8 text")
    export.add_argument("key")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--text", action="store_true")


def run(args: argparse.Namespace, db: Database) -> None:
    documents = Documents(db)
    if args.document_command == "ingest":
        result = documents.ingest(args.url, args.category, args.title)
    elif args.document_command == "list":
        result = documents.list(args.category)
    elif args.document_command == "show":
        result = documents.get(args.key)
    elif args.document_command == "search":
        result = documents.search(args.term, args.category)
    else:
        result = documents.export(args.key, args.output, args.text)
    print(json.dumps(result, indent=2))
