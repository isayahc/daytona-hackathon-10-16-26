"""Manually ingest extracted document text or inspect stored research sources."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from dotenv import load_dotenv
from .store import DocumentStore, capture_document
from .ingest import ingest_document
from documents import CATEGORIES


def main() -> None:
    """Save a document representation or list/retrieve stored versions."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('ingest')
    ingest.add_argument('--url', required=True)
    files = ingest.add_mutually_exclusive_group()
    files.add_argument('--text-file', type=Path, help='UTF-8 extracted text (legacy input)')
    files.add_argument('--file', type=Path, help='Local PDF, DOCX, HTML or text; omit to download --url')
    ingest.add_argument('--title', default='')
    ingest.add_argument('--format', choices=['text', 'markdown', 'html'], default='text')
    ingest.add_argument('--category', choices=CATEGORIES, default='')
    search = commands.add_parser('search')
    search.add_argument('query')
    search.add_argument('--category', choices=CATEGORIES, default='')
    search.add_argument('--limit', type=int, default=5)
    commands.add_parser('list')
    show = commands.add_parser('show')
    show.add_argument('key')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    store = DocumentStore()
    if args.command == 'ingest':
        if args.text_file:
            from dataclasses import replace
            document = capture_document(args.url, args.text_file.read_text(encoding='utf-8'),
                                        title=args.title, content_format=args.format)
            key = store.save(replace(document, category=args.category))
        else:
            key = ingest_document(store, source_url=args.url, file=args.file,
                                  title=args.title, category=args.category)
        print(json.dumps({'document_key': key}))
    elif args.command == 'search':
        print(json.dumps(store.search(args.query, category=args.category, limit=args.limit), indent=2))
    elif args.command == 'list':
        print(json.dumps(store.list(), indent=2))
    else:
        print(json.dumps(store.get(args.key), indent=2))


if __name__ == '__main__':
    # Preserve the exception and its cause for actionable diagnostics.
    main()
