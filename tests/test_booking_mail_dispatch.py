"""Test the production background mail helper without booting network services."""
import ast
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'controllers/booking_controller.py'
tree = ast.parse(SOURCE.read_text())
helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_send_booking_mail_async')

class BookingMailTests(unittest.TestCase):
    def setup_dispatch(self):
        executor, mail, logger = Mock(), Mock(), Mock()
        scope = {'_ASYNC_EXECUTOR': executor, 'booking_mail': mail,
                 'current_app': SimpleNamespace(logger=logger)}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(SOURCE), 'exec'), scope)
        return scope['_send_booking_mail_async'], executor, mail, logger

    def test_mail_is_deferred_until_worker_runs(self):
        dispatch, executor, mail, _ = self.setup_dispatch()
        app = SimpleNamespace(app_context=nullcontext)
        job = {'gamer_name': 'Test', 'booking_details': [{'booking_id': 1}]}
        dispatch(app, [job])
        mail.assert_not_called()
        executor.submit.assert_called_once()
        executor.submit.call_args.args[0]()
        mail.assert_called_once_with(**job)

    def test_mail_failure_stays_in_background_and_next_job_runs(self):
        dispatch, executor, mail, logger = self.setup_dispatch()
        mail.side_effect = [TimeoutError('SMTP timeout'), None]
        dispatch(SimpleNamespace(app_context=nullcontext), [{'booking_id': 1}, {'booking_id': 2}])
        executor.submit.call_args.args[0]()
        self.assertEqual(mail.call_count, 2)
        logger.exception.assert_called_once()

if __name__ == '__main__':
    unittest.main()
