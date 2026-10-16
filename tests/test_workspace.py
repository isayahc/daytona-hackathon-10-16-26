"""Validate reusable workspace data contracts and fixture relationships."""
import json
import unittest
from dataclasses import replace
from datetime import datetime
from operator_app.mock_data import demo_workspace
from operator_app.models import Catering, Event, EventStatus, Location, Organization, Person, Sponsor, Venue
from operator_app.server import workspace_json


class WorkspaceTests(unittest.TestCase):
    """Guard API provenance, linked IDs, and calendar timestamp correctness."""

    def test_references_resolve(self) -> None:
        """Every cross-surface event, venue, and organization link must resolve."""
        workspace = demo_workspace()
        events = {event.id for event in workspace.events}
        venues = {venue.id for venue in workspace.venues}
        for event in workspace.events:
            if event.venue_id is not None:
                self.assertIn(event.venue_id, venues)
            self.assertEqual(event.organization_id, workspace.organization.id)
        for item in (*workspace.activities, *workspace.metrics):
            self.assertIn(item.event_id, events)
        people = {person.id for person in workspace.people}
        sponsors = {sponsor.id for sponsor in workspace.sponsors}
        catering = {plan.id for plan in workspace.catering}
        for event in workspace.events:
            self.assertTrue(set(event.attendee_ids).issubset(people))
            self.assertTrue(set(event.organizer_person_ids).issubset(people))
            self.assertTrue(set(event.sponsor_ids).issubset(sponsors))
            if event.catering_id is not None:
                self.assertIn(event.catering_id, catering)
        for partner in (*workspace.sponsors, *workspace.catering):
            if partner.contact_person_id:
                self.assertIn(partner.contact_person_id, people)

    def test_api_marks_all_sample_records(self) -> None:
        """Mock provenance survives serialization at envelope and record levels."""
        payload = json.loads(workspace_json())
        self.assertTrue(payload['is_mock'])
        self.assertTrue(payload['organization']['is_mock'])
        for collection in ['events', 'venues', 'activities', 'metrics', 'people', 'sponsors', 'catering']:
            self.assertTrue(all(item['is_mock'] for item in payload[collection]))
        self.assertEqual(payload['timezone'], 'America/New_York')
        self.assertEqual(payload['events'][0]['status'], 'planning')

    def test_dates_preserve_daylight_saving_offsets(self) -> None:
        """October and November retain their correct Eastern timezone offsets."""
        payload = json.loads(workspace_json())
        self.assertTrue(payload['events'][0]['starts_at'].endswith('-04:00'))
        self.assertTrue(payload['events'][2]['starts_at'].endswith('-05:00'))

    def test_invalid_domain_values(self) -> None:
        """Reject invalid locations, naive times, reversed duration, and negative goals."""
        with self.assertRaises(ValueError):
            Location(100, 0, 'invalid', 'NYC')
        event = demo_workspace().events[0]
        for changes in [{'ends_at': event.starts_at}, {'starts_at': datetime(2026, 10, 24)},
                        {'registration_target': -1}]:
            with self.assertRaises(ValueError):
                replace(event, **changes)

    def test_core_event_does_not_require_planning_details(self) -> None:
        organization = Organization('nonprofit', 'Community nonprofit')
        event = Event(id='event', organization_id=organization.id, title='Community workshop',
                      starts_at=datetime.fromisoformat('2026-11-14T13:00:00-05:00'))
        self.assertEqual(organization.kind, 'nonprofit')
        self.assertEqual(event.status, EventStatus.PLANNING)
        self.assertIsNone(event.ends_at)
        self.assertIsNone(event.venue_id)
        self.assertIsNone(event.budget_usd)
        self.assertIsNone(event.registration_count)
        self.assertEqual(event.attendee_ids, ())
        self.assertEqual(event.sponsor_ids, ())
        self.assertIsNone(event.catering_id)
        self.assertIsNone(Venue('venue', 'Candidate space').capacity)
        self.assertIsNone(Person('person', 'Participant').email)
        self.assertIsNone(Sponsor('sponsor', 'Candidate supporter').contribution_usd)
        self.assertIsNone(Catering('food', 'Candidate kitchen').headcount)
        for changes in ({'title': ''}, {'organization_id': ''}, {'id': ''}):
            with self.assertRaises(ValueError):
                replace(event, **changes)

    def test_document_based_proposal_has_no_invented_attendance(self) -> None:
        payload = json.loads(workspace_json())
        event = next(event for event in payload['events'] if event['id'] == 'e4')
        self.assertEqual(event['source_urls'], ['https://www.energy.gov/solar'])
        self.assertTrue(event['source_document_keys'])
        self.assertEqual(event['attendee_ids'], [])
        self.assertIsNone(event['registration_count'])
        self.assertEqual(payload['sponsors'][0]['status'], 'prospective')
        self.assertIsNone(payload['sponsors'][0]['contribution_usd'])

    def test_attendance_is_independent_of_registration_counts(self) -> None:
        event = replace(demo_workspace().events[0], status=EventStatus.COMPLETED,
                        registration_count=10, attendee_ids=('person-1', 'person-2'))
        self.assertEqual(len(event.attendee_ids), 2)
        self.assertEqual(event.registration_count, 10)
        with self.assertRaises(ValueError):
            Catering('food', 'Kitchen', headcount=-1)
        with self.assertRaises(ValueError):
            Sponsor('sponsor', 'Supporter', contribution_usd=-10)


if __name__ == '__main__':
    unittest.main()
