from flask import Flask, make_response, g, request
from flask_cors import CORS
from flask_socketio import SocketIO
from db.extensions import db, migrate, mail
from controllers.booking_controller import booking_blueprint
from controllers.slot_controller import slot_blueprint
from controllers.game_controller import game_blueprint
from controllers.pass_controller import pass_blueprint
from .config import Config
from events.socketio_events import register_socketio_events
from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler

import logging
import os
import time
import uuid
from werkzeug.middleware.proxy_fix import ProxyFix

# Allow all origins for SocketIO
socketio = SocketIO(
    async_mode="eventlet",
    cors_allowed_origins="*",
    ping_interval=int(os.getenv("SOCKETIO_PING_INTERVAL_SEC", "25") or 25),
    ping_timeout=int(os.getenv("SOCKETIO_PING_TIMEOUT_SEC", "60") or 60),
    max_http_buffer_size=int(os.getenv("SOCKETIO_MAX_HTTP_BUFFER_BYTES", str(1_000_000)) or 1_000_000),
    logger=os.getenv("SOCKETIO_LOGGER", "false").lower() == "true",
    engineio_logger=os.getenv("ENGINEIO_LOGGER", "false").lower() == "true"
)

def _is_insecure_secret(value: str, placeholders: set[str]) -> bool:
    if not value:
        return True
    candidate = str(value).strip()
    if candidate in placeholders:
        return True
    return len(candidate) < 32


def _validate_production_config(app: Flask) -> None:
    app_env = str(app.config.get("APP_ENV", "development")).lower()
    is_production = app_env in {"prod", "production"}
    if not is_production:
        return
    weak_secret = _is_insecure_secret(
        app.config.get("SECRET_KEY", ""),
        {"dev-secret-change-me", "changeme"},
    )
    weak_jwt_secret = _is_insecure_secret(
        app.config.get("JWT_SECRET_KEY", ""),
        {"dev-jwt-secret-change-me", "dev", "changeme"},
    )
    if weak_secret or weak_jwt_secret:
        raise RuntimeError(
            "In production, SECRET_KEY and JWT_SECRET_KEY must be strong non-default values with length >= 32."
        )


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    _validate_production_config(app)
    if app.config.get("TRUST_PROXY", True):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    app.json.sort_keys = False
    app.json.compact = True

    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)

    # Allow all origins for API routes
    CORS(
        app,
        resources={r"/*": {
            "origins": app.config.get("CORS_ALLOWED_ORIGINS", "*"),
            "allow_headers": "*",
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "expose_headers": ["Content-Type", "Authorization"],
            "supports_credentials": False
        }}
    )

    app.register_blueprint(booking_blueprint, url_prefix="/api")
    app.register_blueprint(slot_blueprint, url_prefix="/api")
    app.register_blueprint(game_blueprint, url_prefix="/api")
    app.register_blueprint(pass_blueprint, url_prefix='/api')

    def _is_public_cacheable_path(path: str) -> bool:
        return (
            path.startswith("/api/getSlots/vendor/")
            or path.startswith("/api/games/vendor/")
            or path.startswith("/api/vendor/") and path.endswith("/passes/available")
            or path.startswith("/api/bookings/pricing-estimate")
        )

    @app.before_request
    def _start_request_timer():
        g.request_start_ts = time.perf_counter()
        incoming_request_id = (
            request.headers.get("X-Request-Id")
            or request.headers.get("X-Correlation-Id")
        )
        g.request_id = incoming_request_id or str(uuid.uuid4())

    @app.after_request
    def force_cors_headers(response):
        # Safety net: keep CORS headers present even on error paths/timeouts from Flask handlers.
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Client-Source, X-Requested-With"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Expose-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")

        if app.config.get("API_ENABLE_TIMING_HEADERS", True):
            start_ts = getattr(g, "request_start_ts", None)
            if start_ts is not None:
                elapsed_ms = (time.perf_counter() - start_ts) * 1000.0
                response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
                slow_ms = int(app.config.get("API_SLOW_REQUEST_MS", 120) or 120)
                if elapsed_ms >= slow_ms:
                    app.logger.warning(
                        "slow_request request_id=%s method=%s path=%s status=%s elapsed_ms=%.2f",
                        getattr(g, "request_id", "-"),
                        request.method,
                        request.path,
                        response.status_code,
                        elapsed_ms,
                    )

        if "Cache-Control" not in response.headers and request.method == "GET" and response.status_code == 200:
            has_auth_header = bool(request.headers.get("Authorization"))
            if not has_auth_header and _is_public_cacheable_path(request.path):
                response.headers["Cache-Control"] = app.config.get(
                    "API_PUBLIC_CACHE_CONTROL",
                    "public, max-age=15, stale-while-revalidate=30",
                )
            else:
                response.headers["Cache-Control"] = app.config.get("API_PRIVATE_CACHE_CONTROL", "no-store")
        return response

    # Global preflight fallback so browser OPTIONS never hard-fails with 404.
    @app.route("/api", methods=["OPTIONS"])
    @app.route("/api/<path:_path>", methods=["OPTIONS"])
    def api_preflight(_path=None):
        response = make_response("", 204)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Client-Source, X-Requested-With"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "86400"
        return response

    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    log_level = logging.DEBUG if debug_mode else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    redis_conn = Redis.from_url(app.config["REDIS_URL"])
    queue = Queue("booking_tasks", connection=redis_conn)
    scheduler = Scheduler(queue=queue, connection=redis_conn)
    app.extensions["scheduler"] = scheduler

    socketio.init_app(
        app,
        message_queue=app.config["REDIS_URL"],
        cors_allowed_origins=app.config.get("CORS_ALLOWED_ORIGINS", "*"),
    )
    register_socketio_events(socketio)

    return app


app = create_app()
