import sys
from types import SimpleNamespace
from datetime import date, time, datetime
from unittest.mock import Mock, patch
import unittest
from services.upcoming_slots import move_slot


class UpcomingSlotTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(id=9, slot_id=10, game_id=3, game_name='PC', status='confirmed', squad_details={}, start_time=time(18), end_time=time(19), booked_date=date(2026,9,28))
        self.target = dict(start_time=time(20), end_time=time(21))
        self.session = Mock()
        self.capacity = True
        def execute(sql, params):
            result = Mock()
            result.scalar.return_value = 'upcoming'
            query = str(sql)
            if 'MIN(t.booked_date)' in query:
                result.mappings.return_value.first.return_value = self.row
            elif 'SELECT start_time, end_time' in query:
                result.mappings.return_value.first.return_value = self.target
            elif 'available_slot=available_slot-' in query:
                result.first.return_value = (11,) if self.capacity else None
            elif 'available_slot=available_slot+' in query:
                result.first.return_value = (10,)
            return result
        self.session.execute.side_effect = execute

    def move(self):
        with patch.dict(sys.modules, {'controllers.booking_controller': SimpleNamespace(_requires_multi_console_units=lambda *a: True)}):
            move_slot(self.session, 7, 9, 11, date(2026,9,28), datetime(2026,9,28,17))

    def test_moves_only_booked_slot_and_keeps_payment_amount(self):
        self.move()
        calls = [(str(c.args[0]), c.args[1]) for c in self.session.execute.call_args_list]
        release = next(p for q,p in calls if 'available_slot=available_slot+' in q)
        self.assertEqual(release['slot'], 10)
        self.assertEqual(release['units'], 1)
        self.assertFalse(any('amount=' in q for q,p in calls))
        self.session.commit.assert_not_called()

    def test_full_destination_does_not_release_original(self):
        self.capacity = False
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            self.move()
        self.assertFalse(any('available_slot=available_slot+' in str(c.args[0]) for c in self.session.execute.call_args_list))

    def test_started_booking_cannot_move(self):
        self.row['status'] = 'checked_in'
        with self.assertRaisesRegex(ValueError, 'upcoming'):
            self.move()
        self.assertFalse(any(str(c.args[0]).lstrip().startswith('UPDATE') for c in self.session.execute.call_args_list))

    def test_duration_cannot_silently_change(self):
        self.target['end_time'] = time(22)
        with self.assertRaisesRegex(ValueError, 'same duration'):
            self.move()

    def test_squad_moves_all_reserved_units(self):
        self.row['squad_details'] = {'enabled': True, 'player_count': 3}
        self.move()
        updates = [c.args[1] for c in self.session.execute.call_args_list if 'available_slot=available_slot' in str(c.args[0])]
        self.assertEqual([p['units'] for p in updates], [3,3])
