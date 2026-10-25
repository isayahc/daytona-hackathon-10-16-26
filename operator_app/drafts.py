"""SQLite persistence for locally authored event drafts (separate from sample data)."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import Event


def save_draft(database: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate editable fields and persist one draft, without external actions."""
    title = payload.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 160:
        raise ValueError('Enter an event title of 1–160 characters.')
    for field in ('summary', 'audience'):
        if not isinstance(payload.get(field, ''), str) or len(payload.get(field, '')) > 5000:
            raise ValueError(f'{field} must be text under 5,000 characters.')
    for field in ('budget_usd', 'registration_target'):
        value = payload.get(field)
        if value is not None and (type(value) not in (int, float) or not 0 <= value <= 1_000_000_000):
            raise ValueError(f'{field} must be a nonnegative finite number.')
    target = payload.get('registration_target')
    if target is not None and int(target) != target:
        raise ValueError('Participant target must be a whole number.')
    try:
        starts_at = datetime.fromisoformat(payload.get('starts_at', ''))
    except (TypeError, ValueError) as error:
        raise ValueError('Provide a valid start time including its UTC offset.') from error
    event = Event(id=f'draft-{uuid4().hex}', organization_id='local-organizer',
                  title=title.strip(), starts_at=starts_at,
                  summary=payload.get('summary', '').strip(), audience=payload.get('audience', '').strip(),
                  budget_usd=payload.get('budget_usd'), registration_target=target, is_mock=False)
    result = asdict(event)
    result['starts_at'] = starts_at.isoformat()
    result = json.loads(json.dumps(result))
    with _connect(database) as connection:
        connection.execute('INSERT INTO drafts VALUES (?, ?)', (event.id, json.dumps(result)))
    return result


def _connect(database: Path) -> sqlite3.Connection:
    """Open and initialize the local draft store."""
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return connection


def list_drafts(database: Path) -> list[dict[str, Any]]:
    """Read stored drafts in creation order."""
    with _connect(database) as connection:
        return [json.loads(row[0]) for row in connection.execute('SELECT payload FROM drafts ORDER BY rowid')]
