"""Isolated regression tests of the production release method, without network boot.

The real method is compiled from its AST; DB boundaries are mocked. Database-level
lock contention must additionally be tested against PostgreSQL in staging.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / 'services/booking_service.py'
tree = ast.parse(SOURCE.read_text())
method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'release_slot')
method.decorator_list = []
CODE = compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(SOURCE), 'exec')


class ReleaseTests(unittest.TestCase):
    def setup_release(self, status='pending_verified', squad=None, rowcount=1):
        booking = SimpleNamespace(status=status, squad_details=squad or {})
        query = Mock()
        query.filter_by.return_value.with_for_update.return_value.first.return_value = booking
        session = Mock()
        session.execute.side_effect = lambda sql, params: (
            SimpleNamespace(fetchone=lambda: (7,)) if sql.startswith('SELECT')
            else SimpleNamespace(rowcount=rowcount))
        app = SimpleNamespace(logger=Mock(), extensions={'socketio': object()})
        app._get_current_object = lambda: app
        emit = Mock()
        scope = dict(current_app=app, has_app_context=lambda: True, get_current_job=lambda: None,
                     Booking=SimpleNamespace(query=query), db=SimpleNamespace(session=session),
                     text=lambda sql: sql, emit_booking_event=emit)
        exec(CODE, scope)
        return scope['release_slot'], booking, session, query, emit

    def test_duplicate_job_restores_capacity_once(self):
        release, booking, session, query, emit = self.setup_release()
        release(2, 3, '2026-09-19')
        release(2, 3, '2026-09-19')
        self.assertEqual(booking.status, 'verification_failed')
        self.assertEqual(session.execute.call_count, 2)  # vendor lookup + one update
        session.commit.assert_called_once()
        self.assertEqual(query.filter_by.return_value.with_for_update.call_count, 2)
        emit.assert_called_once()
        self.assertEqual(emit.call_args.kwargs['vendor_id'], 7)
        self.assertEqual(session.remove.call_count, 2)

    def test_cancelled_or_paid_booking_is_not_released(self):
        for status in ('cancelled', 'paid', 'confirmed', 'verification_failed'):
            with self.subTest(status=status):
                release, _, session, _, emit = self.setup_release(status)
                release(2, 3, '2026-09-19')
                session.execute.assert_not_called()
                session.commit.assert_not_called()
                emit.assert_not_called()

    def test_pc_squad_restores_all_reserved_units(self):
        release, _, session, _, _ = self.setup_release(squad={'console_group': 'pc', 'player_count': 4})
        release(2, 3, '2026-09-19')
        self.assertEqual(session.execute.call_args.args[1]['slot_units'], 4)
        session.commit.assert_called_once()

    def test_missing_slot_rolls_back_and_reports_failure(self):
        release, booking, session, _, emit = self.setup_release(rowcount=0)
        with self.assertRaises(ValueError):
            release(2, 3, '2026-09-19')
        self.assertEqual(booking.status, 'pending_verified')
        session.rollback.assert_called_once()
        session.commit.assert_not_called()
        session.remove.assert_called_once()
        emit.assert_not_called()

    def test_database_failure_is_not_silently_successful(self):
        release, _, session, _, emit = self.setup_release()
        session.execute.side_effect = RuntimeError('database unavailable')
        with self.assertRaises(RuntimeError):
            release(2, 3, '2026-09-19')
        session.rollback.assert_called_once()
        session.commit.assert_not_called()
        emit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
