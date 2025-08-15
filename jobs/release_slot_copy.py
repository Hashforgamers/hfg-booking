import json
import logging
import os
import time
from datetime import datetime

import requests

# -----------------------------------------------------------------------------
# Config via env
# -----------------------------------------------------------------------------
API_BASE = os.getenv("SERVICE_BASE_URL", "https://hfg-booking.onrender.com/api")
RELEASE_ENDPOINT = f"{API_BASE}/release_slot_job"

AUTH_HEADER = os.getenv("RELEASE_JOB_AUTH")  # e.g., "Bearer <token>" or "Key abc123"
INTERVAL_SEC = int(os.getenv("RELEASE_TRIGGER_INTERVAL_SEC", "30"))  # seconds between calls
RUN_LOOPS = int(os.getenv("RELEASE_TRIGGER_LOOPS", "2880"))  # 2880 loops ≈ 24h @30s; adjust as needed
TIMEOUT_SEC = int(os.getenv("RELEASE_TRIGGER_TIMEOUT_SEC", "20"))  # HTTP timeout

RETRIES = int(os.getenv("RELEASE_TRIGGER_RETRIES", "3"))
BACKOFF = float(os.getenv("RELEASE_TRIGGER_BACKOFF", "1.5"))

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("release_slot_trigger")


def build_headers():
    headers = {"Content-Type": "application/json"}
    if AUTH_HEADER:
        headers["Authorization"] = AUTH_HEADER
    return headers


def http_post_with_retries(url, json_payload=None, headers=None, retries=3, backoff=1.5, timeout=20):
    attempt = 0
    last_exc = None
    while attempt < retries:
        try:
            return requests.post(url, json=json_payload, headers=headers, timeout=timeout)
        except Exception as e:
            last_exc = e
            attempt += 1
            sleep_for = backoff ** attempt
            log.warning(f"POST {url} failed (attempt {attempt}/{retries}): {e}. Retrying in {sleep_for:.1f}s...")
            time.sleep(sleep_for)
    raise last_exc


def trigger_once():
    """Call the scanner endpoint once and log the outcome."""
    headers = build_headers()
    log.info(f"Triggering release scan at {datetime.utcnow().isoformat()}Z -> {RELEASE_ENDPOINT}")
    try:
        resp = http_post_with_retries(
            RELEASE_ENDPOINT,
            json_payload={},  # controller does its own scanning; no payload needed
            headers=headers,
            retries=RETRIES,
            backoff=BACKOFF,
            timeout=TIMEOUT_SEC,
        )
        body_text = (resp.text or "")[:800]

        if 200 <= resp.status_code < 300:
            # Try to parse JSON to surface counts cleanly
            try:
                body = resp.json()
                found = body.get("found")
                released = body.get("released")
                skipped = body.get("skipped")
                errors = body.get("errors")
                log.info(f"Release scan OK: status={resp.status_code} found={found} released={released} skipped={skipped}")
                if errors:
                    log.warning(f"Partial issues: {errors}")
            except Exception:
                log.info(f"Release scan OK: status={resp.status_code} body={body_text}")
        else:
            log.error(f"Release scan failed: status={resp.status_code} body={body_text}")

    except Exception as e:
        log.error(f"Failed to call release endpoint: {e}")


def main():
    log.info(
        "Starting release-slot trigger job with config: "
        f"endpoint={RELEASE_ENDPOINT}, interval={INTERVAL_SEC}s, loops={RUN_LOOPS}, "
        f"retries={RETRIES}, backoff={BACKOFF}"
    )
    for i in range(1, RUN_LOOPS + 1):
        log.info(f"Loop {i}/{RUN_LOOPS}")
        trigger_once()
        if i < RUN_LOOPS:
            time.sleep(INTERVAL_SEC)
    log.info("Release-slot trigger job finished.")


if __name__ == "__main__":
    main()
