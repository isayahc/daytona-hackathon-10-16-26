"""Persist retrieved text, its source, and its exact checksum in SurrealDB."""
from __future__ import annotations
import hashlib
import json
import os
import re
import math
from collections import Counter
from dataclasses import asdict, replace
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
        env = os.environ if env is None else env
        self.spectron = None
        if memory is None and any(env.get(key) for key in ('SPECTRON_URL', 'SPECTRON_CONTEXT_ID', 'SPECTRON_API_KEY')):
            from .spectron import SpectronDocuments
            self.spectron = SpectronDocuments(env)
        self.memory = memory if memory is not None else None if self.spectron else Memory(env=env)

    def save(self, document: Document) -> str:
        """Idempotently store one version and return its reusable document key."""
        payload = asdict(document)
        payload['retrieved_at'] = document.retrieved_at.isoformat()
        if self.spectron:
            return self.spectron.save(payload)
        self.memory.query("UPSERT type::record('document:' + $id) CONTENT $document;",
                          {'id': document.key, 'document': payload})
        return document.key

    def ingest_events(self, output: str, *, category: str = '') -> tuple[str, ...]:
        """Persist fetched documents, surfacing backend failures with the exact version ID."""
        keys = []
        for document in documents_from_events(output):
            if category:
                document = replace(document, category=category)
            try:
                keys.append(self.save(document))
            except Exception as error:
                raise RuntimeError(f'Document ingestion failed for version {document.key}; '
                                   'the agent turn must not be reported as fully saved') from error
        return tuple(keys)

    def list(self) -> list[Any]:
        """Return source metadata without loading all stored content."""
        if self.spectron:
            return self.spectron.list()
        return self.memory.query('SELECT key, source_url, title, category, content_sha256, retrieved_at, '
                                 'source_session_id, is_truncated FROM document WHERE content != NONE;')[0]

    def get(self, key: str) -> list[Any]:
        """Retrieve a specific source/content version for reuse or citation."""
        if self.spectron:
            return self.spectron.get(key)
        return self.memory.query("SELECT * FROM type::record('document:' + $id) WHERE content != NONE;",
                                 {'id': key})[0]

    def search(self, query: str, *, category: str = '', limit: int = 5) -> list[dict[str, Any]]:
        """Rank exact stored passages lexically; works before async indexing completes.

        This bounded-context prototype scans the corpus, rather than relying on an
        asynchronously indexed or potentially stale remote passage representation.
        """
        if not 1 <= limit <= 20:
            raise ValueError('Search limit must be between 1 and 20')
        from documents import CATEGORIES
        if category and category not in CATEGORIES:
            raise ValueError('Choose weather, climate, defense, or energy')
        stopwords = {'the', 'and', 'for', 'with', 'that', 'this', 'from', 'what', 'how',
                     'are', 'can', 'our', 'into', 'about', 'would', 'could', 'should', 'does'}
        tokens = lambda text: [word for word in re.findall(r'\w+', text.lower())
                               if len(word) > 2 and word not in stopwords]
        terms = set(tokens(query))
        if not terms:
            return []
        if self.spectron:
            documents = [self.spectron.read(row) for row in self.spectron.records()]
        else:
            documents = [document for row in self.list() for document in self.get(row['key'])]
        passages = []
        for document in documents:
            if category and document.get('category', '') != category:
                continue
            text = document['content']
            for offset in range(0, len(text), 1200):
                passage = text[offset:offset + 1600]
                counts = Counter(tokens(passage))
                matched = terms & counts.keys()
                if not matched:
                    continue
                score = sum(1 + math.log(counts[term]) for term in matched) / math.sqrt(max(len(counts), 1))
                passages.append({'document_key': document['key'], 'title': document['title'],
                                 'source_url': document['source_url'], 'category': document.get('category', ''),
                                 'content_sha256': document['content_sha256'], 'passage': passage,
                                 'offset': offset, 'score': score})
        passages.sort(key=lambda row: (-row['score'], row['document_key'], row['offset']))
        return passages[:limit]
