"""Persist retrieved text, its source, and its exact checksum in SurrealDB."""
from __future__ import annotations
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit
from operator_app.models import Document
from outreach import Memory

MAX_CONTENT_BYTES = 2 * 1024 * 1024


def capture_document(source_url: str, content: str, *, title: str = '', content_format: str = 'text',
                     session_id: str | None = None, call_id: str | None = None,
                     is_truncated: bool = False, capture_method: str = 'manual') -> Document:
    """Build a stable source/content version ID; never silently truncate text."""
    url = urlsplit(source_url)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
        raise ValueError('Document source must be an HTTP(S) URL without embedded credentials')
    source = urlunsplit((url.scheme, url.netloc, url.path, url.query, ''))
    if not content.strip():
        raise ValueError('Retrieved document content is empty')
    if len(content.encode('utf-8')) > MAX_CONTENT_BYTES:
        raise ValueError('Document exceeds the 2 MiB text limit; split it explicitly before ingestion')
    if content_format not in {'text', 'markdown', 'html'}:
        raise ValueError('Supported document representations: text, markdown, html')
    checksum = hashlib.sha256(content.encode('utf-8')).hexdigest()
    key = hashlib.sha256((source + '\0' + checksum).encode()).hexdigest()
    return Document(key, source, title or source, content, content_format, checksum,
                    datetime.now(timezone.utc), session_id, call_id, is_truncated, capture_method)


def documents_from_events(output: str) -> list[Document]:
    """Capture completed OpenCode webfetch results, excluding links and failed tools."""
    found: dict[str, Document] = {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get('type') != 'tool_use':
            continue
        part = event.get('part')
        if not isinstance(part, dict) or part.get('tool') != 'webfetch':
            continue
        state = part.get('state') or {}
        if not isinstance(state, dict) or state.get('status') != 'completed':
            continue
        args = state.get('input') or {}
        content = state.get('output')
        if not isinstance(args, dict) or not isinstance(args.get('url'), str) or not isinstance(content, str):
            raise ValueError('Completed webfetch event is missing its source URL or text output')
        metadata = state.get('metadata') or {}
        if not isinstance(metadata, dict):
            raise ValueError('Completed webfetch event has invalid provenance metadata')
        document = capture_document(args['url'], content, title=state.get('title') or '',
                                    content_format=args.get('format', 'markdown'),
                                    session_id=event.get('sessionID') or part.get('sessionID'),
                                    call_id=part.get('callID'), is_truncated=bool(metadata.get('truncated')),
                                    capture_method='opencode.webfetch')
        found[document.key] = document
    return list(found.values())


class DocumentStore:
    """Store source/content versions; identical source/text pairs share one record."""

    def __init__(self, env: Mapping[str, str] | None = None, *, memory: Any = None) -> None:
        """Reuse the database adapter without forwarding credentials to the agent."""
        self.memory = memory if memory is not None else Memory(env=env)

    def save(self, document: Document) -> str:
        """Idempotently store one version and return its reusable document key."""
        payload = asdict(document)
        payload['retrieved_at'] = document.retrieved_at.isoformat()
        self.memory.query("UPSERT type::record('document', $id) CONTENT $document;",
                          {'id': document.key, 'document': payload})
        return document.key

    def ingest_events(self, output: str) -> tuple[str, ...]:
        """Persist fetched documents, surfacing backend failures with the exact version ID."""
        keys = []
        for document in documents_from_events(output):
            try:
                keys.append(self.save(document))
            except Exception as error:
                raise RuntimeError(f'Document ingestion failed for version {document.key}; '
                                   'the agent turn must not be reported as fully saved') from error
        return tuple(keys)

    def list(self) -> list[Any]:
        """Return source metadata without loading all stored content."""
        return self.memory.query('SELECT key, source_url, title, content_sha256, retrieved_at, '
                                 'source_session_id, is_truncated FROM document;')[0]

    def get(self, key: str) -> list[Any]:
        """Retrieve a specific source/content version for reuse or citation."""
        return self.memory.query("SELECT * FROM type::record('document', $id);", {'id': key})[0]
