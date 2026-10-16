"""Fictional NYC fixtures; no venue availability or sponsor commitment is real."""
from datetime import datetime
from .models import (Activity, ActivityKind, Catering, Event, EventStatus, Location,
                     Metric, Organization, Person, Sponsor, Venue, Workspace)


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
        Event(id='e1', organization_id='org-1', title='Neighborhood Builders Lab', summary='A hands-on afternoon turning local challenges into practical community projects.', starts_at=timestamp('2026-10-24T13:00:00-04:00'), ends_at=timestamp('2026-10-24T17:00:00-04:00'), status=EventStatus.PLANNING, venue_id='v1', audience='NYC community builders and first-time makers', budget_usd=4000, funding_secured_usd=1500, registration_count=38, registration_target=60, intended_outcomes=('6 documented community projects', 'A reusable workshop curriculum', 'Participant follow-up at 30 days')),
        Event(id='e2', organization_id='org-1', title='Civic Tech Partner Breakfast', summary='Connect nonprofit operators with institutions supporting workforce and civic technology.', starts_at=timestamp('2026-10-29T09:00:00-04:00'), ends_at=timestamp('2026-10-29T11:00:00-04:00'), status=EventStatus.CONFIRMED, venue_id='v2', audience='Nonprofit program leads and institutional partners', budget_usd=2000, funding_secured_usd=1800, registration_count=24, registration_target=40, intended_outcomes=('8 partner introductions', '3 follow-up program conversations')),
        Event(id='e3', organization_id='org-1', title='Repair & Reuse Saturday', summary='Neighbors learn repair skills and document electronics recovery projects.', starts_at=timestamp('2026-11-07T10:00:00-05:00'), ends_at=timestamp('2026-11-07T14:00:00-05:00'), status=EventStatus.PLANNING, venue_id='v3', audience='Queens residents and volunteer repair mentors', budget_usd=2500, funding_secured_usd=500, registration_count=12, registration_target=35, intended_outcomes=('Document repair outcomes', 'Publish a materials recovery summary')),
        Event(id='e4', organization_id='org-1', title='Community Energy & Resilience Workshop',
              starts_at=timestamp('2026-11-14T13:00:00-05:00'),
              summary='Proposed nonprofit workshop: explore community solar, energy costs, and solar-plus-storage resilience using the DOE Solar Energy source. Date and resources are illustrative.',
              audience='NYC residents, nonprofit operators, and community volunteers',
              organizer_person_ids=('p1',), sponsor_ids=('s1',), catering_id='c1',
              intended_outcomes=('Explain community solar options using cited evidence',
                                 'Collect questions about local eligibility and costs',
                                 'Draft a neighborhood energy-resilience follow-up plan'),
              source_document_keys=('8e4b94f966aabf1e62e817783e75e0ec7217e8f7c66d6115c1be3cea59cf2091',),
              source_urls=('https://www.energy.gov/solar',)),
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
        (Metric(event.id+'-funding', event.id, 'Funding secured', event.funding_secured_usd, event.budget_usd, 'USD')
         if event.funding_secured_usd is not None else None),
        (Metric(event.id+'-people', event.id, 'Registrations', event.registration_count, event.registration_target, 'people')
         if event.registration_count is not None else None),
    ) if metric is not None)
    people = (Person('p1', 'Alex Morgan', organization_id='org-1', role='Nonprofit program organizer'),
              Person('p2', 'Jordan Lee', role='Prospective sponsor contact'),
              Person('p3', 'Taylor Rivera', role='Prospective catering contact'))
    sponsors = (Sponsor('s1', 'Example Neighborhood Energy Fund', contact_person_id='p2',
                        contribution_notes='Candidate for workshop materials or in-kind support; no commitment.'),)
    catering = (Catering('c1', 'Example Community Kitchen', contact_person_id='p3',
                         dietary_notes='Ask participants about dietary needs before requesting a quote.'),)
    return Workspace(organization, venues, events, activities, metrics,
                     people=people, sponsors=sponsors, catering=catering,
                     metadata={'notice': 'All organizations, venues, messages, commitments, and metrics are fictional demo data. Locations are illustrative.'})
