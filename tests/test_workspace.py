"""Validate reusable workspace data contracts and fixture relationships."""
import json
import unittest
from dataclasses import replace
from datetime import datetime
from operator_app.mock_data import demo_workspace
from operator_app.models import Location
from operator_app.server import workspace_json


class WorkspaceTests(unittest.TestCase):
    """Guard API provenance, linked IDs, and calendar timestamp correctness."""

    def test_references_resolve(self) -> None:
        """Every cross-surface event, venue, and organization link must resolve."""
        workspace = demo_workspace()
        events = {event.id for event in workspace.events}
        venues = {venue.id for venue in workspace.venues}
        for event in workspace.events:
            self.assertIn(event.venue_id, venues)
            self.assertEqual(event.organization_id, workspace.organization.id)
        for item in (*workspace.activities, *workspace.metrics):
            self.assertIn(item.event_id, events)

    def test_api_marks_all_sample_records(self) -> None:
        """Mock provenance survives serialization at envelope and record levels."""
        payload = json.loads(workspace_json())
        self.assertTrue(payload['is_mock'])
        self.assertTrue(payload['organization']['is_mock'])
        for collection in ['events', 'venues', 'activities', 'metrics']:
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


if __name__ == '__main__':
    unittest.main()
