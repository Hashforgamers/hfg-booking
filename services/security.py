from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64
import functools
from flask import request, jsonify, g, current_app
import jwt

import time
from threading import Lock

_PRIVATE_KEY_CACHE = {}
_PRIVATE_KEY_CACHE_LOCK = Lock()
_DECRYPTED_SUBJECT_CACHE = {}
_DECRYPTED_SUBJECT_CACHE_LOCK = Lock()

def encode_user(user_id: str, public_key_pem: str) -> str:
    """
    Encode a user ID using RSA public key PEM string.
    Returns a base64-encoded string.
    """
    public_key = serialization.load_pem_public_key(public_key_pem.encode())

    encrypted = public_key.encrypt(
        str(user_id).encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    return base64.urlsafe_b64encode(encrypted).decode()


def decode_user(encoded_user: str, private_key_pem: str) -> str:
    """
    Decode the encrypted user ID using RSA private key PEM string.
    """
    key_cache_key = str(private_key_pem or "")
    with _PRIVATE_KEY_CACHE_LOCK:
        private_key = _PRIVATE_KEY_CACHE.get(key_cache_key)
    if private_key is None:
        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        with _PRIVATE_KEY_CACHE_LOCK:
            _PRIVATE_KEY_CACHE[key_cache_key] = private_key

    encrypted_bytes = base64.urlsafe_b64decode(encoded_user.encode())

    decrypted = private_key.decrypt(
        encrypted_bytes,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    return decrypted.decode()

def auth_required_self(decrypt_user=False):
    return auth_required(match_route_user=False, decrypt_user=decrypt_user)

def extract_bearer_token():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth.split(" ", 1)[1].strip()

def auth_required(match_route_user=True, decrypt_user=False):
    """
    - match_route_user: if True, ensure token user_id matches the user_id in the route.
    - decrypt_user: if True, apply decrypt_user_id() to the user_id claim before comparing.
    Attaches g.token_claims, g.auth_user_id, and g.token_expired for downstream usage.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            auth_debug = bool(current_app.config.get("AUTH_DEBUG_LOGS", False))
            if auth_debug:
                current_app.logger.debug("Starting auth_required check...")

            token = extract_bearer_token()
            if not token:
                current_app.logger.warning("Missing Authorization Bearer token")
                return jsonify({"message": "Missing Authorization Bearer token"}), 401

            try:
                secret = current_app.config["JWT_SECRET_KEY"]

                # Decode without enforcing expiration
                claims = jwt.decode(
                    token,
                    secret,
                    algorithms=["HS256"],
                    options={
                        "require": ["exp", "iat", "uuid"],
                        "verify_exp": False
                    },
                )
                if auth_debug:
                    current_app.logger.debug("Decoded JWT claims keys: %s", list(claims.keys()))

                # Handle expiration manually
                exp = claims.get("exp")
                if exp and int(time.time()) > exp:
                    current_app.logger.warning("Token is expired, but proceeding anyway.")
                    g.token_expired = True
                else:
                    g.token_expired = False

            except jwt.InvalidTokenError as e:
                current_app.logger.warning(f"Invalid token: {e}")
                return jsonify({"message": "Invalid token"}), 401

            token_user_id_raw = claims.get("uuid")
            if token_user_id_raw is None:
                current_app.logger.warning("Token missing 'uuid' claim")
                return jsonify({"message": "Invalid token: missing subject"}), 401

            if decrypt_user:
                now_ts = time.time()
                exp_ts = int(claims.get("exp") or 0)
                cache_ttl_cap = int(current_app.config.get("AUTH_DECRYPT_CACHE_TTL_SEC", 300))
                cache_ttl = max(1, min(cache_ttl_cap, max(exp_ts - int(now_ts), 1))) if exp_ts else cache_ttl_cap
                with _DECRYPTED_SUBJECT_CACHE_LOCK:
                    cached = _DECRYPTED_SUBJECT_CACHE.get(token_user_id_raw)
                    if cached and float(cached.get("expires_at", 0)) > now_ts:
                        token_user_id = cached.get("user_id")
                    else:
                        token_user_id = None
                try:
                    if token_user_id is None:
                        token_user_id = decode_user(
                            token_user_id_raw,
                            current_app.config['ENCRYPT_PRIVATE_KEY']
                        )
                        with _DECRYPTED_SUBJECT_CACHE_LOCK:
                            _DECRYPTED_SUBJECT_CACHE[token_user_id_raw] = {
                                "user_id": token_user_id,
                                "expires_at": now_ts + cache_ttl,
                            }
                    if auth_debug:
                        current_app.logger.debug("Decrypted token subject successfully")
                except Exception as e:
                    current_app.logger.warning(f"Cannot decrypt user ID: {e}")
                    return jsonify({"message": "Invalid token: cannot decrypt subject"}), 401
            else:
                token_user_id = token_user_id_raw
                if auth_debug:
                    current_app.logger.debug("Using raw token subject")

            try:
                token_user_id_int = int(token_user_id)
            except (TypeError, ValueError):
                current_app.logger.warning("Token subject type is invalid (not int)")
                return jsonify({"message": "Invalid token: subject type"}), 401

            g.token_claims = claims
            g.auth_user_id = token_user_id_int
            if auth_debug:
                current_app.logger.debug(
                    "Stored auth context user_id=%s token_expired=%s",
                    g.auth_user_id,
                    g.token_expired,
                )

            if match_route_user:
                route_user_id = kwargs.get("user_id")
                if route_user_id is None:
                    current_app.logger.warning("Route user_id missing")
                    return jsonify({"message": "Route user_id missing"}), 400
                if int(route_user_id) != token_user_id_int:
                    current_app.logger.warning(
                        f"User mismatch: route={route_user_id}, token={token_user_id_int}"
                    )
                    return jsonify({"message": "Forbidden: user mismatch"}), 403

            if auth_debug:
                current_app.logger.debug("Authorization successful")
            return fn(*args, **kwargs)

        return wrapper
    return decorator
