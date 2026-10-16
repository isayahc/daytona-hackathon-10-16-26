"""Context-scoped Spectron document storage using its public REST API."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from outreach import required


class SpectronDocuments:
    """Keep exact document envelopes as raw files, with searchable source text."""

    def __init__(self, env: Mapping[str, str]) -> None:
        endpoint = required('SPECTRON_URL', env).rstrip('/')
        url = urlsplit(endpoint)
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
            raise ValueError('SPECTRON_URL must be an HTTP(S) origin without credentials')
        self.base = endpoint + '/api/v1/' + quote(required('SPECTRON_CONTEXT_ID', env), safe='')
        self.headers = {'Authorization': 'Bearer ' + required('SPECTRON_API_KEY', env)}

    def request(self, path: str, *, method: str = 'GET', data: bytes | None = None,
                headers: dict[str, str] | None = None, raw: bool = False) -> Any:
        request = Request(self.base + path, data=data, method=method,
                          headers={**self.headers, **(headers or {})})
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
        except HTTPError as error:
            status = error.code
            error.close()
            raise RuntimeError(f'Spectron request failed (HTTP {status}); check context, key and permissions') from None
        except (URLError, TimeoutError):
            raise RuntimeError('Could not connect to Spectron') from None
        return body if raw else json.loads(body) if body else {}

    def records(self) -> list[dict[str, Any]]:
        records = []
        cursor = None
        while True:
            params = {'limit': 100}
            if cursor:
                params['cursor'] = cursor
            result = self.request('/documents?' + urlencode(params))
            for row in result['documents']:
                match = re.match(r'^daytona-document:([0-9a-f]{64}) ', row.get('title', ''))
                if match:
                    records.append({**row, 'key': match[1]})
            cursor = result.get('page', {}).get('nextCursor')
            if not cursor:
                return records

    def find(self, key: str) -> dict[str, Any] | None:
        return next((row for row in self.records() if row['key'] == key), None)

    def save(self, payload: dict[str, Any]) -> str:
        key = payload['key']
        if self.find(key):
            return key
        # Raw downloads preserve all provenance and exact text, independently of indexing.
        content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        # List/detail responses omit labels on the hosted API. A namespaced title
        # makes stable keys discoverable; the original title stays in the raw envelope.
        metadata = {'title': f'daytona-document:{key} ' + payload['title'], 'source': payload['source_url'],
                    'mimeType': 'text/plain', 'filename': key + '.txt',
                    'labels': ['app=daytona-document-store', f'document_key={key}']}
        boundary = 'daytona-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
                'Content-Type: application/json\r\n\r\n').encode() + json.dumps(metadata).encode()
        body += (f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                 f'filename="{key}.txt"\r\nContent-Type: text/plain\r\n\r\n').encode()
        body += content + f'\r\n--{boundary}--\r\n'.encode()
        self.request('/documents', method='POST', data=body, headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Idempotency-Key': 'daytona-document-' + key})
        return key

    def get(self, key: str) -> list[dict[str, Any]]:
        row = self.find(key)
        if row is None:
            return []
        return [self.read(row)]

    def read(self, row: dict[str, Any]) -> dict[str, Any]:
        """Download and validate one exact stored source/content version."""
        payload = json.loads(self.request('/documents/' + quote(row['id'], safe='') + '/raw', raw=True))
        checksum = hashlib.sha256(payload['content'].encode('utf-8')).hexdigest()
        identity = hashlib.sha256((payload['source_url'] + '\0' + checksum).encode()).hexdigest()
        if payload['key'] != row['key'] or identity != row['key'] or payload['content_sha256'] != checksum:
            raise RuntimeError('Spectron document failed its identity/checksum check')
        return payload

    def list(self) -> list[dict[str, Any]]:
        fields = ('key', 'source_url', 'title', 'category', 'content_sha256', 'retrieved_at',
                  'source_session_id', 'is_truncated')
        result = []
        for row in self.records():
            payload = self.read(row)
            result.append({field: payload.get(field, '') for field in fields})
        return result

    def delete(self, key: str) -> None:
        row = self.find(key)
        if row:
            self.request('/documents/' + quote(row['id'], safe=''), method='DELETE')
