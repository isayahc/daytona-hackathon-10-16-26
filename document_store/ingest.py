"""Extract public or local research documents for the shared document store."""
from __future__ import annotations

import mimetypes
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from documents import CATEGORIES, MAX_DOWNLOAD_BYTES, download, extract
from .store import capture_document


def ingest_document(store, *, source_url: str, file: Path | None = None,
                    title: str = '', category: str = '') -> str:
    """Extract PDF, DOCX, HTML, or text; reject failed/empty extraction explicitly."""
    if category and category not in CATEGORIES:
        raise ValueError('Choose weather, climate, defense, or energy')
    if file is None:
        data, metadata = download(source_url)
    else:
        with file.open('rb') as stream:
            data = stream.read(MAX_DOWNLOAD_BYTES + 1)
        if not data or len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError('Use a nonempty file no larger than 50 MiB')
        metadata = {'filename': file.name, 'content_type': mimetypes.guess_type(file.name)[0] or '',
                    'charset': 'utf-8-sig'}
    if (Path(metadata['filename']).suffix.lower() == '.docx'
            or metadata['content_type'] == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'):
        with ZipFile(BytesIO(data)) as archive:
            info = archive.getinfo('word/document.xml')
            if info.file_size > MAX_DOWNLOAD_BYTES:
                raise ValueError('Word document expands beyond the 50 MiB limit')
            root = ElementTree.fromstring(archive.read(info))
        namespace = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = '\n'.join(''.join(paragraph.itertext()) for paragraph in root.findall('.//w:p', namespace))
        status = 'extracted' if text.strip() else 'no_text'
    else:
        text, details = extract(data, metadata)
        status = details['extraction_status']
    if status != 'extracted':
        raise ValueError(f'Cannot ingest document text: {status}. Scanned files need OCR; use PDF, DOCX, HTML or text.')
    document = capture_document(source_url, text, title=title or metadata['filename'],
                                capture_method='file.extract' if file else 'url.extract')
    return store.save(replace(document, category=category))
