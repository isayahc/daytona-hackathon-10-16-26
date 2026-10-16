"""Manually ingest extracted document text or inspect stored research sources."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .store import DocumentStore, capture_document


def main() -> None:
    """Save a document representation or list/retrieve stored versions."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('ingest')
    ingest.add_argument('--url', required=True)
    ingest.add_argument('--text-file', type=Path, required=True)
    ingest.add_argument('--title', default='')
    ingest.add_argument('--format', choices=['text', 'markdown', 'html'], default='text')
    commands.add_parser('list')
    show = commands.add_parser('show')
    show.add_argument('key')
    args = parser.parse_args()
    store = DocumentStore()
    if args.command == 'ingest':
        document = capture_document(args.url, args.text_file.read_text(encoding='utf-8'),
                                    title=args.title, content_format=args.format)
        print(json.dumps({'document_key': store.save(document), 'content_sha256': document.content_sha256}))
    elif args.command == 'list':
        print(json.dumps(store.list(), indent=2))
    else:
        print(json.dumps(store.get(args.key), indent=2))


if __name__ == '__main__':
    # Preserve the exception and its cause for actionable diagnostics.
    main()
