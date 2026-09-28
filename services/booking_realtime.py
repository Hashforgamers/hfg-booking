"""Keep best-effort realtime delivery outside committed booking responses."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import BoundedSemaphore
import logging

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='booking-realtime')
_pending = BoundedSemaphore(128)


class DeferredBookingRealtime:
    def __init__(self, socketio):
        self.socketio = socketio
        self.events = []

    def emit(self, event, data, **kwargs):
        # Never hand ORM objects or request-scoped mutable payloads to a worker.
        self.events.append((event, deepcopy(data), dict(kwargs)))

    def dispatch(self):
        events, self.events = self.events, []
        if not events:
            return
        if not _pending.acquire(blocking=False):
            logger.warning('Booking realtime queue full; dashboard refresh will recover saved bookings')
            return

        def deliver():
            try:
                for event, data, kwargs in events:
                    try:
                        self.socketio.emit(event, data, **kwargs)
                    except Exception:
                        logger.exception('Booking realtime delivery failed event=%s', event)
            finally:
                _pending.release()

        try:
            _executor.submit(deliver)
        except Exception:
            _pending.release()
            logger.exception('Unable to queue booking realtime notifications')
