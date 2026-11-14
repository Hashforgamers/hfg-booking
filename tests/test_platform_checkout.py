"""Exercise the checkout hook and handlers together with a mocked gateway."""
import ast
import base64
import hashlib
import hmac
import unittest
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask, current_app, g, jsonify, request

from services import cafe_payment_policy as policy
from services.legacy_pass_checkout import is_legacy_pass_request, is_legacy_pass_order, LEGACY_PASS_VERSION


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


class LegacyFlutterCheckoutTest(PlatformCheckoutTest):
    def setUp(self):
        super().setUp()
        from services.legacy_pass_checkout import pass_order_auth
        from services.security import auth_required_self
        app = self.client.application
        # Exercise production authentication; only subject decryption is stubbed.
        app.before_request_funcs[None] = [policy.enforce_cafe_payment_policy]
        app.config.update(JWT_SECRET_KEY='test-checkout-secret-' * 3, ENCRYPT_PRIVATE_KEY='test')
        app.view_functions['create_order'] = pass_order_auth(app.view_functions['create_order'])
        app.view_functions['capture_payment'] = auth_required_self(decrypt_user=True)(app.view_functions['capture_payment'])
        self.decrypt = patch('services.security.decode_user', return_value='1')
        self.decrypt.start()
        self.addCleanup(self.decrypt.stop)
        import jwt
        import time
        self.auth = {'Authorization': 'Bearer ' + jwt.encode(
            {'uuid': '1', 'iat': int(time.time()), 'exp': int(time.time()) + 600},
            app.config['JWT_SECRET_KEY'], algorithm='HS256')}

    # Parent cases test handlers without auth; these variants include real auth.
    def test_platform_order_and_capture(self):
        response = self.client.post('/create_order', json={'amount':10000, 'purpose':'game_pass'})
        self.assertEqual(response.status_code, 401)

    def test_cafe_policy_and_capture_relabeling(self):
        self.assertEqual(self.client.post('/capture_payment', json=self.capture).status_code, 401)

    def test_exact_flutter_order_contract(self):
        payload = {'amount':10000, 'currency':'INR', 'receipt':'pass_rcpt_1793683967098'}
        response = self.client.post('/create_order', json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['notes']['checkout_version'], LEGACY_PASS_VERSION)
        self.assertEqual(response.json['notes']['user_id'], '')
        self.assertTrue(response.json['receipt'].startswith('pass_'))
        for changes in ({'cafe_pass_id':1}, {'vendor_id':1}, {'receipt':'wallet_rcpt_1793683967098'}):
            self.assertNotEqual(self.client.post('/create_order', json=dict(payload, **changes)).status_code, 200)
        self.assertEqual(self.client.post('/create_order', json=payload, headers={'Authorization':'Bearer invalid'}).status_code, 401)

    def test_bound_pass_capture_is_a_valid_platform_order(self):
        self.api.order.fetch.return_value = {'notes': {'user_id':'1', 'purpose':'pass_purchase', 'cafe_pass_id':'1'}}
        self.api.payment.fetch.return_value = dict(id='pay', order_id='ord', status='captured', currency='INR', amount=10000)
        response = self.client.post('/capture_payment', json=self.capture, headers=self.auth)
        self.assertEqual(response.status_code, 200)

    def test_signed_legacy_capture_and_bad_signature(self):
        handler = self.client.application.view_functions['capture_payment'].__wrapped__
        claim = Mock()
        handler.__globals__['claim_legacy_payment'] = claim
        handler.__globals__['db'] = Mock()
        self.api.order.fetch.return_value = {'notes': {'source':'hfg_booking', 'purpose':'game_pass', 'checkout_version':LEGACY_PASS_VERSION}}
        self.api.payment.fetch.return_value = dict(id='pay', order_id='ord', status='captured', currency='INR', amount=10000)
        response = self.client.post('/capture_payment', json=dict(self.capture, razorpay_signature='invalid'), headers=self.auth)
        self.assertEqual(response.status_code, 400)
        claim.assert_not_called()
        response = self.client.post('/capture_payment', json=self.capture, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        claim.assert_called_once_with(1, self.api.payment.fetch.return_value, 'ord')
