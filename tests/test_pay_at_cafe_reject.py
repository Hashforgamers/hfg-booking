"""Regression tests for rejecting a pay-at-cafe request, without network boot.

The real route body is compiled from its AST and its DB/socket boundaries are
mocked, like tests/test_release_slot.py.
"""
import ast
import sys
from datetime import date, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / 'controllers/booking_controller.py'
tree = ast.parse(SOURCE.read_text())
func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'reject_pay_at_cafe_booking')
func.decorator_list = []
CODE = compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), str(SOURCE), 'exec')


class RejectPayAtCafeTests(unittest.TestCase):
    def setup_reject(self, release_side_effect=None):
        calls = []
        booking = SimpleNamespace(id=11, status='pending_acceptance', game_id=5, slot_id=99,
                                  user_id=3, squad_details={'slot_units': 1, 'booked_date': '2026-11-27'})
        game = SimpleNamespace(id=5, vendor_id=7)
        user = SimpleNamespace(name='Gamer', contact_info=SimpleNamespace(email='g@example.test'))

        def model(obj):
            cls = Mock()  # column attributes used in join/filter expressions
            cls.query.filter_by.return_value.first.return_value = obj
            return cls

        session = Mock()
        session.commit.side_effect = lambda: calls.append(('commit', booking.status))
        release = Mock(side_effect=release_side_effect or (lambda *a: calls.append(('release', booking.status))))
        emit_vendor = Mock(side_effect=lambda *a, **k: calls.append(('emit_vendor', a[1])))
        emit_booking = Mock(side_effect=lambda *a, **k: calls.append(('emit_booking', k['data']['booking_id'])))
        mail = Mock(side_effect=lambda **k: calls.append(('mail', k['gamer_email'])))

        realtime = ModuleType('utils.realtime')
        realtime.emit_vendor_event = emit_vendor
        sys.modules['utils.realtime'] = realtime
        self.addCleanup(sys.modules.pop, 'utils.realtime', None)

        app = SimpleNamespace(logger=Mock(), extensions={'socketio': object()})
        scope = dict(
            request=SimpleNamespace(get_json=lambda silent=True: {
                'booking_id': 11, 'vendor_id': 7, 'rejection_reason': 'Full'}),
            jsonify=lambda payload: payload,
            current_app=app, datetime=datetime, db=SimpleNamespace(session=session),
            Booking=model(booking),
            AvailableGame=model(game),
            Vendor=model(SimpleNamespace(cafe_name='Cafe')),
            User=model(user),
            _parse_json_details=lambda d: d if isinstance(d, dict) else {},
            _resolve_pay_at_cafe_batch=lambda *a, **k: [booking],
            resolve_booking_booked_date=lambda b: date(2026, 11, 27),
            _release_slot_for_booking=release,
            _invalidate_pay_at_cafe_vendor_cache=Mock(),
            _log_pay_at_cafe_action=Mock(),
            emit_booking_event=emit_booking,
            reject_booking_mail=mail,
        )
        exec(CODE, scope)
        return scope['reject_pay_at_cafe_booking'], booking, session, release, calls

    def test_reject_cancels_frees_slot_and_notifies_after_commit(self):
        reject, booking, session, release, calls = self.setup_reject()
        body, status = reject()
        self.assertEqual(status, 200)
        self.assertTrue(body['success'])
        self.assertEqual(booking.status, 'cancelled')
        release.assert_called_once_with(booking, 7, date(2026, 11, 27))
        session.remove.assert_not_called()
        session.rollback.assert_not_called()
        names = [c[0] for c in calls]
        self.assertEqual(names, ['release', 'commit', 'emit_vendor', 'emit_booking', 'mail'])
        self.assertIn(('commit', 'cancelled'), calls)

    def test_missing_schedule_row_still_rejects(self):
        reject, booking, session, _, calls = self.setup_reject(
            release_side_effect=ValueError('Slot schedule is missing'))
        body, status = reject()
        self.assertEqual(status, 200)
        self.assertEqual(booking.status, 'cancelled')
        self.assertIn(('commit', 'cancelled'), calls)

    def test_database_failure_rolls_back_without_notifying(self):
        reject, booking, session, _, calls = self.setup_reject(
            release_side_effect=RuntimeError('database unavailable'))
        body, status = reject()
        self.assertEqual(status, 500)
        session.rollback.assert_called_once()
        self.assertFalse([c for c in calls if c[0] in ('commit', 'emit_vendor', 'mail')])


if __name__ == '__main__':
    unittest.main()
