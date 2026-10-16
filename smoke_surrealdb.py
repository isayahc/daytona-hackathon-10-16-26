"""Run a live CRUD smoke test using the project's SurrealDB settings."""
from __future__ import annotations

import sys
import os
import json
import uuid
from pathlib import Path
from urllib.error import URLError

from dotenv import load_dotenv

from outreach import Memory


def smoke_test(db: Memory) -> None:
    """Check authenticated queries and CRUD, then remove the unique test record."""
    if db.query("RETURN 1;") != [1]:
        raise RuntimeError("Unexpected response to the connectivity check")
    variables = {"id": str(uuid.uuid4()), "value": "created"}
    record = "type::record('smoke_test', $id)"
    try:
        db.query(f"CREATE {record} SET value = $value;", variables)
        rows = db.query(f"SELECT value FROM {record};", variables)[0]
        if rows != [{"value": "created"}]:
            raise RuntimeError("Created record did not round-trip")
        variables["value"] = "updated"
        db.query(f"UPDATE {record} SET value = $value;", variables)
        rows = db.query(f"SELECT value FROM {record};", variables)[0]
        if rows != [{"value": "updated"}]:
            raise RuntimeError("Updated record did not round-trip")
    finally:
        db.query(f"DELETE {record};", variables)
    if db.query(f"SELECT * FROM {record};", variables)[0]:
        raise RuntimeError("Test record still exists after deletion")


def main() -> int:
    load_dotenv(Path(__file__).resolve().with_name(".env"))
    try:
        if any(os.getenv(key) for key in ('SPECTRON_URL', 'SPECTRON_CONTEXT_ID', 'SPECTRON_API_KEY')):
            from document_store import DocumentStore, capture_document
            store = DocumentStore()
            document = capture_document('https://example.org/smoke/' + uuid.uuid4().hex,
                                        'Daytona Spectron smoke test: exact text round trip. 🌎')
            try:
                event = {'type': 'tool_use', 'sessionID': 'smoke-test', 'part': {
                    'tool': 'webfetch', 'callID': 'smoke-fetch', 'state': {
                        'status': 'completed', 'input': {'url': document.source_url, 'format': 'text'},
                        'output': document.content}}}
                if store.ingest_events(json.dumps(event)) != (document.key,):
                    raise RuntimeError('Webfetch ingestion returned the wrong document key')
                rows = store.get(document.key)
                if len(rows) != 1 or rows[0]['content'] != document.content:
                    raise RuntimeError('Spectron document did not round-trip')
                if not any(row['key'] == document.key for row in store.list()):
                    raise RuntimeError('Spectron document missing from listing')
                if not any(row['document_key'] == document.key for row in store.search('Daytona Spectron smoke test')):
                    raise RuntimeError('Spectron smoke document missing from passage search')
                store.save(document)
                if len([row for row in store.spectron.records()
                        if row['key'] == document.key]) != 1:
                    raise RuntimeError('Duplicate document was created')
            finally:
                store.spectron.delete(document.key)
            if store.get(document.key):
                raise RuntimeError('Spectron smoke document was not deleted')
            print('Spectron smoke test PASSED: save, exact retrieval, checksum, list, search, deduplication, cleanup.')
            return 0
        smoke_test(Memory())
    except (ValueError, RuntimeError) as error:
        print(f"SurrealDB smoke test FAILED: {error}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError):
        print("SurrealDB smoke test FAILED: could not connect to the database.", file=sys.stderr)
        return 1
    print("SurrealDB smoke test PASSED: authenticated query, create, read, update, delete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
