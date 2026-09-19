"""Exercise actual slot readers with a warm cache and mocked database boundary."""
import ast
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / 'controllers/slot_controller.py'
TREE = ast.parse(SOURCE.read_text())


def load(args):
    functions = [n for n in TREE.body if isinstance(n, ast.FunctionDef)
                 and n.name in {'_force_slot_refresh', 'get_slots_on_game_id'}]
    for node in functions:
        node.decorator_list = []
    query = Mock()
    query.filter_by.return_value.first.return_value = None
    response = SimpleNamespace(headers={})
    scope = dict(request=SimpleNamespace(args=args), time=SimpleNamespace(time=lambda: 1),
                 _slots_single_cache_lock=threading.Lock(),
                 _slots_single_cache={'1:2:20260919': {'payload': [], 'expires_at': 10}},
                 jsonify=lambda *a, **kw: response, AvailableGame=SimpleNamespace(query=query))
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), str(SOURCE), 'exec'), scope)
    return scope, query, response


class SlotCacheTests(unittest.TestCase):
    def test_normal_read_uses_warm_cache(self):
        scope, query, response = load({})
        _, status = scope['get_slots_on_game_id'](1, 2, '20260919')
        self.assertEqual(status, 200)
        self.assertEqual(response.headers['X-Cache'], 'HIT')
        query.filter_by.assert_not_called()

    def test_explicit_and_legacy_refresh_reach_database(self):
        for args in ({'refresh': '1'}, {'no_cache': 'true'}, {'t': '1234'}):
            with self.subTest(args=args):
                scope, query, response = load(args)
                _, status = scope['get_slots_on_game_id'](1, 2, '20260919')
                self.assertEqual(status, 404)  # stubbed database: no game
                query.filter_by.assert_called_once_with(id=2, vendor_id=1)
                self.assertNotIn('X-Cache', response.headers)


if __name__ == '__main__':
    unittest.main()
