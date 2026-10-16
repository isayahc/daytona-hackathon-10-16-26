"""Source document capture and versioned SurrealDB storage."""
from .store import DocumentStore, capture_document, documents_from_events

__all__ = ['DocumentStore', 'capture_document', 'documents_from_events']
