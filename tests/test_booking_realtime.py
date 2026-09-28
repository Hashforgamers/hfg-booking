import unittest
from unittest.mock import Mock, patch
from services.booking_realtime import DeferredBookingRealtime


class BookingRealtimeTests(unittest.TestCase):
    @patch('services.booking_realtime._executor')
    def test_delivery_is_deferred_and_payload_is_snapshotted(self, executor):
        socket = Mock()
        queue = DeferredBookingRealtime(socket)
        payload = {'bookingId': 7, 'details': {'status': 'confirmed'}}
        queue.emit('booking', payload, to='vendor_41')
        payload['details']['status'] = 'changed'
        queue.dispatch()
        socket.emit.assert_not_called()
        executor.submit.call_args.args[0]()
        socket.emit.assert_called_once_with('booking', {'bookingId': 7, 'details': {'status': 'confirmed'}}, to='vendor_41')
        queue.dispatch()
        executor.submit.assert_called_once()

    @patch('services.booking_realtime._executor')
    def test_failure_does_not_prevent_later_events(self, executor):
        socket = Mock()
        socket.emit.side_effect = [ConnectionError('Redis unavailable'), None]
        queue = DeferredBookingRealtime(socket)
        queue.emit('booking', {})
        queue.emit('booking_admin', {})
        queue.dispatch()
        with self.assertLogs('services.booking_realtime', level='ERROR'):
            executor.submit.call_args.args[0]()
        self.assertEqual(socket.emit.call_count, 2)

    @patch('services.booking_realtime._pending')
    @patch('services.booking_realtime._executor')
    def test_queue_saturation_never_blocks_booking(self, executor, pending):
        pending.acquire.return_value = False
        queue = DeferredBookingRealtime(Mock())
        queue.emit('booking', {})
        with self.assertLogs('services.booking_realtime', level='WARNING'):
            queue.dispatch()
        pending.acquire.assert_called_once_with(blocking=False)
        executor.submit.assert_not_called()

    @patch('services.booking_realtime._pending')
    @patch('services.booking_realtime._executor')
    def test_shutdown_does_not_fail_a_committed_booking(self, executor, pending):
        executor.submit.side_effect = RuntimeError('shutdown')
        queue = DeferredBookingRealtime(Mock())
        queue.emit('booking', {})
        with self.assertLogs('services.booking_realtime', level='ERROR'):
            queue.dispatch()
        pending.release.assert_called_once()


if __name__ == '__main__':
    unittest.main()
