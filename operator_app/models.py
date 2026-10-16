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
    kind: str
    mission: str
    website: str | None = None
    location: Location | None = None
    source_url: str | None = None
    is_mock: bool = True


@dataclass(frozen=True)
class Venue:
    """A venue candidate; suitability and availability require verification."""
    id: str
    name: str
    location: Location
    capacity: int
    hourly_cost_usd: float | None
    accessibility_notes: str
    availability: str = 'unverified'
    source_url: str | None = None
    is_mock: bool = True


@dataclass(frozen=True)
class Event:
    """A program event and the measurable goals that guide its operation."""
    id: str
    organization_id: str
    title: str
    summary: str
    starts_at: datetime
    ends_at: datetime
    status: EventStatus
    venue_id: str | None
    audience: str
    budget_usd: float
    funding_secured_usd: float
    registration_count: int
    registration_target: int
    intended_outcomes: tuple[str, ...] = ()
    is_mock: bool = True

    def __post_init__(self) -> None:
        """Require aware timestamps and a positive event duration."""
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError('Event timestamps must include a timezone')
        if self.ends_at <= self.starts_at:
            raise ValueError('Event end must follow its start')
        if min(self.budget_usd, self.funding_secured_usd, self.registration_count, self.registration_target) < 0:
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
    timezone: str = 'America/New_York'
    demo_date: str = '2026-10-16'
    is_mock: bool = True
    schema_version: str = '1.0'
    metadata: dict[str, Any] = field(default_factory=dict)
