"""Vendor-scoped realtime emits and the opt-in bridge socket token."""
import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from utils.realtime import emit_vendor_event
from events import socketio_events


class VendorScopedEmitTests(unittest.TestCase):
    def test_emits_only_to_the_vendor_room(self):
        socket = Mock()
        self.assertTrue(emit_vendor_event(socket, 'pay_at_cafe_accepted', {'access_code': '1234'}, 7))
        event, payload = socket.emit.call_args.args
        self.assertEqual(event, 'pay_at_cafe_accepted')
        self.assertEqual(socket.emit.call_args.kwargs, {'to': 'vendor_7'})
        self.assertEqual(payload['vendorId'], 7)
        self.assertEqual(payload['vendor_id'], 7)

    def test_never_broadcasts_without_a_vendor(self):
        socket = Mock()
        self.assertFalse(emit_vendor_event(socket, 'booking_updated', {'booking_id': 1}, None))
        socket.emit.assert_not_called()

    def test_emit_failure_does_not_raise(self):
        socket = Mock()
        socket.emit.side_effect = RuntimeError('redis down')
        self.assertFalse(emit_vendor_event(socket, 'gamers_credit_updated', {}, 3))


class BridgeTokenTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def check(self, headers):
        with self.app.test_request_context(headers=headers):
            return socketio_events._bridge_token_ok()

    def test_open_when_no_token_configured(self):
        with patch.dict(os.environ, {'BOOKING_AUTH_TOKEN': ''}):
            self.assertTrue(self.check({}))

    def test_requires_matching_bearer_when_configured(self):
        with patch.dict(os.environ, {'BOOKING_AUTH_TOKEN': 'secret-token'}):
            self.assertFalse(self.check({}))
            self.assertFalse(self.check({'Authorization': 'Bearer wrong'}))
            self.assertTrue(self.check({'Authorization': 'Bearer secret-token'}))


if __name__ == '__main__':
    unittest.main()
