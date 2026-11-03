"""Exercise the checkout hook and handlers together with a mocked gateway."""
import ast
import base64
import hashlib
import hmac
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask, current_app, g, jsonify, request

from services import cafe_payment_policy as policy


class PlatformCheckoutTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['RAZORPAY_KEY_SECRET'] = 'secret'
        app.before_request(policy.enforce_cafe_payment_policy)
        self.gateway = Mock()
        http = Mock()
        http.post.side_effect = lambda *args, json, **kwargs: Mock(ok=True, json=lambda: json)
        # Isolate the real handlers from unrelated scheduler and booking imports.
        namespace = dict(globals(), requests=http, razorpay=self.gateway,
                         PLATFORM_PURPOSES=policy.PLATFORM_PURPOSES,
                         cafe_context_required=policy.cafe_context_required)
        source = Path(__file__).resolve().parents[1] / 'controllers/booking_controller.py'
        for node in ast.parse(source.read_text()).body:
            if isinstance(node, ast.FunctionDef) and node.name in ('create_order', 'capture_payment'):
                node.decorator_list = []
                exec(compile(ast.Module([node], []), str(source), 'exec'), namespace)
                app.add_url_rule('/' + node.name, view_func=namespace[node.name], methods=['POST'])
        app.before_request(lambda: setattr(g, 'auth_user_id', 1))
        self.client = app.test_client()
        self.capture = dict(razorpay_order_id='ord', razorpay_payment_id='pay',
                            razorpay_signature=hmac.new(b'secret', b'ord|pay', hashlib.sha256).hexdigest())
        self.api = self.gateway.Client.return_value
        self.api.payment.fetch.return_value = dict(order_id='ord', status='authorized', amount=10000)

    def test_platform_order_and_capture(self):
        for purpose, marker in [('wallet_topup', {'receipt': 'wallet_rcpt_1793683967098'}),
                                *((p, {'purpose': p}) for p in policy.PLATFORM_PURPOSES)]:
            with self.subTest(marker=marker):
                order = self.client.post('/create_order', json=dict(amount=10000, **marker))
                self.assertEqual(order.status_code, 200)
                self.assertEqual(order.json['notes']['purpose'], purpose)
                self.api.order.fetch.return_value = order.json
                self.assertEqual(self.client.post('/capture_payment', json=self.capture).status_code, 200)
                self.api.payment.capture.assert_called_with('pay', 10000)

    def test_cafe_policy_and_capture_relabeling(self):
        response = self.client.post('/create_order', json={'amount': 10000, 'purpose': 'unknown'})
        self.assertEqual(response.json['code'], 'cafe_context_required')
        with patch.object(policy, 'require_method', side_effect=ValueError('disabled')):
            for route in ('create_order', 'capture_payment'):
                response = self.client.post('/' + route, json={'vendor_id': 2, 'purpose': 'wallet_topup'})
                self.assertEqual(response.status_code, 403)
        self.api.order.fetch.return_value = {'notes': {'user_id': '1'}}
        response = self.client.post('/capture_payment', json=dict(self.capture, purpose='wallet_topup'))
        self.assertEqual(response.json['code'], 'cafe_context_required')
        self.api.payment.capture.assert_not_called()
