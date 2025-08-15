from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64
import functools
from flask import request, jsonify, g, current_app
import jwt


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
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)

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
    Attaches g.token_claims and g.auth_user_id for downstream usage.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            current_app.logger.debug("Starting auth_required check...")

            token = extract_bearer_token()
            current_app.logger.debug(f"Extracted token: {token}")
            if not token:
                current_app.logger.warning("Missing Authorization Bearer token")
                return jsonify({"message": "Missing Authorization Bearer token"}), 401

            try:
                secret = current_app.config["JWT_SECRET_KEY"]
                current_app.logger.debug(f"Using JWT secret: {secret[:6]}... (hidden)")

                claims = jwt.decode(
                    token,
                    secret,
                    algorithms=["HS256"],
                    options={"require": ["exp", "iat", "uuid"]},
                )
                current_app.logger.debug(f"Decoded JWT claims: {claims}")

            except jwt.ExpiredSignatureError:
                current_app.logger.warning("Token expired")
                return jsonify({"message": "Token expired"}), 401
            except jwt.InvalidTokenError as e:
                current_app.logger.warning(f"Invalid token: {e}")
                return jsonify({"message": "Invalid token"}), 401

            token_user_id_raw = claims.get("uuid")
            current_app.logger.debug(f"Raw token user ID (uuid): {token_user_id_raw}")
            if token_user_id_raw is None:
                current_app.logger.warning("Token missing 'uuid' claim")
                return jsonify({"message": "Invalid token: missing subject"}), 401

            if decrypt_user:
                current_app.logger.debug("Decrypting user ID...")
                try:
                    token_user_id = decode_user(
                        token_user_id_raw,
                        current_app.config['ENCRYPT_PRIVATE_KEY']
                    )
                    current_app.logger.debug(f"Decrypted token user ID: {token_user_id}")
                except Exception as e:
                    current_app.logger.warning(f"Cannot decrypt user ID: {e}")
                    return jsonify({"message": "Invalid token: cannot decrypt subject"}), 401
            else:
                token_user_id = token_user_id_raw
                current_app.logger.debug(f"Using token user ID without decryption: {token_user_id}")

            try:
                token_user_id_int = int(token_user_id)
                current_app.logger.debug(f"Token user ID as int: {token_user_id_int}")
            except (TypeError, ValueError):
                current_app.logger.warning("Token subject type is invalid (not int)")
                return jsonify({"message": "Invalid token: subject type"}), 401

            g.token_claims = claims
            g.auth_user_id = token_user_id_int
            current_app.logger.debug(f"Stored g.token_claims and g.auth_user_id: {g.auth_user_id}")

            if match_route_user:
                route_user_id = kwargs.get("user_id")
                current_app.logger.debug(f"Route user ID: {route_user_id}")
                if route_user_id is None:
                    current_app.logger.warning("Route user_id missing")
                    return jsonify({"message": "Route user_id missing"}), 400
                if int(route_user_id) != token_user_id_int:
                    current_app.logger.warning(f"User mismatch: route={route_user_id}, token={token_user_id_int}")
                    return jsonify({"message": "Forbidden: user mismatch"}), 403

            current_app.logger.debug("Authorization successful, proceeding to view function.")
            return fn(*args, **kwargs)

        return wrapper
    return decorator
