"""Exercise production batch SQL against a database without starting network services."""
import ast
from pathlib import Path
import sqlite3
from types import SimpleNamespace as Row
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / "services/booking_service.py"
service = next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.ClassDef) and n.name == "BookingService")
helper = next(n for n in service.body if isinstance(n, ast.FunctionDef) and n.name == "insert_vendor_booking_rows")
helper.decorator_list = []


class BookingBatchWritesTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.executescript("""
            CREATE TABLE VENDOR_7_DASHBOARD (
                username TEXT, user_id INTEGER, start_time TEXT, end_time TEXT,
                date TEXT, book_id INTEGER, game_id INTEGER, game_name TEXT,
                console_id INTEGER, book_status TEXT
            );
            CREATE TABLE VENDOR_7_PROMO_DETAIL (
                booking_id INTEGER, transaction_id INTEGER UNIQUE,
                promo_code TEXT, discount_applied TEXT, actual_price REAL
            );
        """)
        self.session = Mock()
        self.session.execute.side_effect = self.connection.executemany
        scope = {"db": Row(session=self.session), "text": lambda sql: sql}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), str(SOURCE), "exec"), scope)
        self.write = scope[helper.name]
        self.bookings = [Row(id=1, slot_id=10, game_id=3, status="confirmed"),
                         Row(id=2, slot_id=11, game_id=3, status="checked_in")]
        self.transactions = [Row(id=20, booking_id=1, booked_date="2026-09-28", amount=20),
                             Row(id=21, booking_id=2, booked_date="2026-09-28", amount=40),
                             Row(id=22, booking_id=2, booked_date="2026-09-28", amount=5)]
        self.slots = {10: Row(start_time="18:00", end_time="19:00"),
                      11: Row(start_time="17:00", end_time="18:00")}
        self.runtime = {1: {"console_id": -1, "dashboard_status": "upcoming"},
                        2: {"console_id": 9, "dashboard_status": "current"}}

    def persist(self, transactions=None):
        self.write(7, self.transactions if transactions is None else transactions,
                   self.bookings, Row(id=42, name="Customer"), Row(game_name="PC"),
                   self.slots, self.runtime)

    def test_batch_preserves_slots_status_prices_and_controller_transaction(self):
        self.persist()
        self.assertEqual(self.session.execute.call_count, 2)
        self.session.commit.assert_not_called()
        self.assertEqual(self.connection.execute(
            "SELECT book_id, console_id, book_status, start_time FROM VENDOR_7_DASHBOARD"
        ).fetchall(), [(1, -1, "upcoming", "18:00"), (2, 9, "current", "17:00"), (2, 9, "current", "17:00")])
        self.assertEqual(self.connection.execute(
            "SELECT booking_id, transaction_id, promo_code, discount_applied, actual_price FROM VENDOR_7_PROMO_DETAIL"
        ).fetchall(), [(1, 20, "NOPROMO", "0", 20), (2, 21, "NOPROMO", "0", 40), (2, 22, "NOPROMO", "0", 5)])

    def test_failure_can_roll_back_both_tables(self):
        self.transactions[2].id = 21
        with self.assertRaises(sqlite3.IntegrityError):
            self.persist()
        self.connection.rollback()
        for table in ("VENDOR_7_DASHBOARD", "VENDOR_7_PROMO_DETAIL"):
            self.assertEqual(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
        self.session.commit.assert_not_called()

    def test_empty_batch_has_no_database_work(self):
        self.persist([])
        self.session.execute.assert_not_called()

    def test_zero_price_and_extra_status_preserved(self):
        self.transactions[0].amount = None
        self.bookings[0].status = "extra"
        self.persist()
        self.assertEqual(self.connection.execute("SELECT book_status FROM VENDOR_7_DASHBOARD WHERE book_id=1").fetchone()[0], "extra")
        self.assertEqual(self.connection.execute("SELECT actual_price FROM VENDOR_7_PROMO_DETAIL WHERE booking_id=1").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
