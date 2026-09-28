import unittest
from sqlalchemy import create_engine, text
from services.customer_search import search_booked_customers


class CustomerSearchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        self.db = self.engine.connect()
        self.addCleanup(self.db.close)
        for sql in (
            'CREATE TABLE users (id INTEGER, name TEXT)',
            'CREATE TABLE contact_info (parent_id INTEGER, parent_type TEXT, phone TEXT, email TEXT)',
            'CREATE TABLE transactions (id INTEGER, vendor_id INTEGER, user_id INTEGER)',
            "INSERT INTO users VALUES (1, 'Old Customer'), (2, 'Recent Customer'), (3, 'Other Cafe'), (4, 'Old_Customer')",
            "INSERT INTO contact_info VALUES (1, 'user', '8989785456', 'old@example.com'), (2, 'user', '1234567890', NULL)",
            'INSERT INTO transactions VALUES (1, 7, 1), (2, 8, 3), (3, 7, 4)',
        ):
            self.db.execute(text(sql))
        self.db.execute(text('INSERT INTO transactions VALUES (:id, 7, 2)'), [{'id': i} for i in range(10, 1010)])

    def test_finds_customer_older_than_recent_transaction_window(self):
        for field, query in [('name', 'old c'), ('phone', '8989'), ('email', 'OLD@')]:
            self.assertEqual([r['id'] for r in search_booked_customers(self.db, 7, query, field, 8)], [1])

    def test_vendor_scope_and_duplicates(self):
        self.assertEqual([r['id'] for r in search_booked_customers(self.db, 7, '', 'all', 8)], [4, 2, 1])
        self.assertEqual(search_booked_customers(self.db, 7, 'Other', 'name', 8), [])

    def test_literal_wildcard_and_bounded_results(self):
        self.assertEqual([r['id'] for r in search_booked_customers(self.db, 7, 'Old_', 'name', 8)], [4])
        self.assertEqual(len(search_booked_customers(self.db, 7, '', 'name', 1)), 1)


if __name__ == '__main__':
    unittest.main()
