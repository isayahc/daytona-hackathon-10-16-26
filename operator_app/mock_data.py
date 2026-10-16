"""Fictional NYC fixtures; no venue availability or sponsor commitment is real."""
from datetime import datetime
from .models import Activity, ActivityKind, Event, EventStatus, Location, Metric, Organization, Venue, Workspace


def timestamp(value: str) -> datetime:
    """Parse an explicit Eastern-time ISO timestamp."""
    return datetime.fromisoformat(value)


def demo_workspace() -> Workspace:
    """Return the single source of mock data used by the API and UI."""
    organization = Organization('org-1', 'Common Ground NYC', 'nonprofit',
                                'Help New Yorkers build practical skills and community-led projects.')
    venues = (
        Venue('v1', 'Brooklyn Community Workshop', Location(40.6782, -73.9442, 'Illustrative location · Crown Heights', 'Brooklyn'), 80, 75, 'Step-free entrance; confirm accessible restroom'),
        Venue('v2', 'Midtown Learning Studio', Location(40.7527, -73.9850, 'Illustrative location · Midtown', 'Manhattan'), 60, 120, 'Elevator access; verify operating hours'),
        Venue('v3', 'Queens Neighborhood Lab', Location(40.7440, -73.9240, 'Illustrative location · Sunnyside', 'Queens'), 45, 50, 'Ground floor; accessibility review pending'),
    )
    events = (
        Event('e1', 'org-1', 'Neighborhood Builders Lab', 'A hands-on afternoon turning local challenges into practical community projects.', timestamp('2026-10-24T13:00:00-04:00'), timestamp('2026-10-24T17:00:00-04:00'), EventStatus.PLANNING, 'v1', 'NYC community builders and first-time makers', 4000, 1500, 38, 60, ('6 documented community projects', 'A reusable workshop curriculum', 'Participant follow-up at 30 days')),
        Event('e2', 'org-1', 'Civic Tech Partner Breakfast', 'Connect nonprofit operators with institutions supporting workforce and civic technology.', timestamp('2026-10-29T09:00:00-04:00'), timestamp('2026-10-29T11:00:00-04:00'), EventStatus.CONFIRMED, 'v2', 'Nonprofit program leads and institutional partners', 2000, 1800, 24, 40, ('8 partner introductions', '3 follow-up program conversations')),
        Event('e3', 'org-1', 'Repair & Reuse Saturday', 'Neighbors learn repair skills and document electronics recovery projects.', timestamp('2026-11-07T10:00:00-05:00'), timestamp('2026-11-07T14:00:00-05:00'), EventStatus.PLANNING, 'v3', 'Queens residents and volunteer repair mentors', 2500, 500, 12, 35, ('Document repair outcomes', 'Publish a materials recovery summary')),
    )
    activities = (
        Activity('a1', 'e1', ActivityKind.MESSAGE, 'LinkedIn', 'A sponsor wants to learn more', 'Maya at Example Civic Fund asked for the workshop budget and the participant outcomes.', timestamp('2026-10-16T10:45:00-04:00'), 'Maya Chen · fictional contact', 'Review message'),
        Activity('a2', 'e1', ActivityKind.TASK, 'Planning', 'Confirm the workshop space', 'The venue is shortlisted. Confirm availability, accessibility, and equipment before booking.', timestamp('2026-10-16T10:20:00-04:00'), 'Your event plan', 'View task'),
        Activity('a3', 'e1', ActivityKind.FUNDING, 'Funding', '$1,500 of the budget covered', 'Illustrative funding entry. There is still a $2,500 gap against the event budget.', timestamp('2026-10-16T09:50:00-04:00'), 'Demo ledger', 'View funding'),
        Activity('a4', 'e2', ActivityKind.MESSAGE, 'Gmail', 'Venue details received', 'The example venue contact shared room layout notes for the partner breakfast.', timestamp('2026-10-16T09:15:00-04:00'), 'Sam Rivera · fictional contact', 'Review email'),
        Activity('a5', 'e1', ActivityKind.OUTCOME, 'Outcomes', 'Collect evidence from day one', 'Plan for attendance, project summaries, and consented feedback to support your sponsor report.', timestamp('2026-10-15T16:00:00-04:00'), 'Program checklist', 'View deliverables'),
        Activity('a6', 'e3', ActivityKind.TASK, 'Planning', 'Find two volunteer mentors', 'Identify repair mentors and confirm the tools needed for the first session.', timestamp('2026-10-15T15:00:00-04:00'), 'Your event plan', 'View task'),
    )
    metrics = tuple(metric for event in events for metric in (
        Metric(event.id+'-funding', event.id, 'Funding secured', event.funding_secured_usd, event.budget_usd, 'USD'),
        Metric(event.id+'-people', event.id, 'Registrations', event.registration_count, event.registration_target, 'people'),
    ))
    return Workspace(organization, venues, events, activities, metrics,
                     metadata={'notice': 'All organizations, venues, messages, commitments, and metrics are fictional demo data. Locations are illustrative.'})
