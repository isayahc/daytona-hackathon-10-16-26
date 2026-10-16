"""Reusable domain models for the operator workspace and future persistence adapters."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventStatus(str, Enum):
    """Lifecycle stages shared by planning, calendar, and reporting."""
    PLANNING = 'planning'
    CONFIRMED = 'confirmed'
    COMPLETED = 'completed'


class ActivityKind(str, Enum):
    """Filterable activity categories independent of transport provider."""
    MESSAGE = 'message'
    TASK = 'task'
    FUNDING = 'funding'
    OUTCOME = 'outcome'


@dataclass(frozen=True)
class Location:
    """A geographic point with an operator-readable address."""
    latitude: float
    longitude: float
    address: str
    borough: str

    def __post_init__(self) -> None:
        """Reject impossible geographic coordinates."""
        if not -90 <= self.latitude <= 90 or not -180 <= self.longitude <= 180:
            raise ValueError('Invalid coordinates')


@dataclass(frozen=True)
class Organization:
    """Nonprofit, venue operator, institution, or prospective sponsor."""
    id: str
    name: str
    kind: str = 'nonprofit'
    mission: str = ''
    website: str | None = None
    location: Location | None = None
    source_url: str | None = None
    is_mock: bool = True


@dataclass(frozen=True)
class Venue:
    """A venue candidate; suitability and availability require verification."""
    id: str
    name: str
    location: Location | None = None
    capacity: int | None = None
    hourly_cost_usd: float | None = None
    accessibility_notes: str = ''
    availability: str = 'unverified'
    source_url: str | None = None
    is_mock: bool = True


@dataclass(frozen=True)
class Person:
    """An attendee, organizer, volunteer, or partner contact; contact data is optional."""
    id: str
    name: str
    organization_id: str | None = None
    email: str | None = None
    role: str | None = None
    is_mock: bool = True


@dataclass(frozen=True)
class Sponsor:
    """A prospective or confirmed sponsor, distinct from a funding commitment."""
    id: str
    name: str
    organization_id: str | None = None
    contact_person_id: str | None = None
    contribution_usd: float | None = None
    contribution_notes: str | None = None
    status: str = 'prospective'
    is_mock: bool = True

    def __post_init__(self) -> None:
        if self.contribution_usd is not None and self.contribution_usd < 0:
            raise ValueError('Sponsor contribution cannot be negative')


@dataclass(frozen=True)
class Catering:
    """An optional food-service plan; naming a provider does not imply a booking."""
    id: str
    provider_name: str
    organization_id: str | None = None
    contact_person_id: str | None = None
    headcount: int | None = None
    cost_usd: float | None = None
    dietary_notes: str | None = None
    status: str = 'proposed'
    is_mock: bool = True

    def __post_init__(self) -> None:
        if any(value is not None and value < 0 for value in (self.headcount, self.cost_usd)):
            raise ValueError('Catering headcount and cost cannot be negative')


@dataclass(frozen=True)
class Event:
    """Core identity, organizer and time, with optional planning relationships.

    Attendee IDs represent recorded attendance, not registrations or invitations.
    Empty relationships mean none have been recorded, not a confirmed absence.
    """
    id: str
    organization_id: str
    title: str
    starts_at: datetime
    summary: str = ''
    ends_at: datetime | None = None
    status: EventStatus = EventStatus.PLANNING
    venue_id: str | None = None
    audience: str = ''
    budget_usd: float | None = None
    funding_secured_usd: float | None = None
    registration_count: int | None = None
    registration_target: int | None = None
    intended_outcomes: tuple[str, ...] = ()
    is_mock: bool = True
    attendee_ids: tuple[str, ...] = ()
    organizer_person_ids: tuple[str, ...] = ()
    sponsor_ids: tuple[str, ...] = ()
    catering_id: str | None = None
    source_document_keys: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Require aware timestamps and a positive event duration."""
        if not all(value.strip() for value in (self.id, self.organization_id, self.title)):
            raise ValueError('Event ID, organizer ID and title are required')
        if self.starts_at.utcoffset() is None or (self.ends_at is not None and self.ends_at.utcoffset() is None):
            raise ValueError('Event timestamps must include a timezone')
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError('Event end must follow its start')
        if any(value is not None and value < 0 for value in
               (self.budget_usd, self.funding_secured_usd, self.registration_count, self.registration_target)):
            raise ValueError('Event metrics cannot be negative')


@dataclass(frozen=True)
class Activity:
    """An event-linked message, task, funding change, or outcome update."""
    id: str
    event_id: str
    kind: ActivityKind
    channel: str
    title: str
    body: str
    occurred_at: datetime
    actor: str
    action_label: str
    status: str = 'pending'
    source_url: str | None = None
    is_mock: bool = True


@dataclass(frozen=True)
class Metric:
    """An event KPI with explicit units and evidence provenance."""
    id: str
    event_id: str
    label: str
    value: float
    target: float | None
    unit: str
    evidence_urls: tuple[str, ...] = ()
    is_mock: bool = True


@dataclass(frozen=True)
class Workspace:
    """Shared response envelope consumed by all workspace surfaces."""
    organization: Organization
    venues: tuple[Venue, ...]
    events: tuple[Event, ...]
    activities: tuple[Activity, ...]
    metrics: tuple[Metric, ...]
    people: tuple[Person, ...] = ()
    sponsors: tuple[Sponsor, ...] = ()
    catering: tuple[Catering, ...] = ()
    timezone: str = 'America/New_York'
    demo_date: str = '2026-10-16'
    is_mock: bool = True
    schema_version: str = '1.0'
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Document:
    """Retrieved source text with versioned provenance for research and citations."""
    key: str
    source_url: str
    title: str
    content: str
    content_format: str
    content_sha256: str
    retrieved_at: datetime
    source_session_id: str | None = None
    source_tool_call_id: str | None = None
    is_truncated: bool = False
    capture_method: str = 'manual'
    is_mock: bool = False
    category: str = ''
