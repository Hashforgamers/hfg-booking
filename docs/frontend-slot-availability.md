# Flutter: live slot availability

Backend source updated; deploy hfg-booking before validating in the app. Flutter remains read-only and unchanged.

## Existing app endpoint (no URL or payload change)

`GET {bookingBaseUrl}/api/getSlots/vendor/{vendorId}/game/{gameId}/{YYYYMMDD}`

The current app calls this from `lib/core/repositories/remote/remote_repo.dart`. Its booking controller and screen already filter on `is_available`, so no Flutter change is needed to hide fully occupied slots after the backend fix is deployed.

```json
{
  "slots": [
    {
      "slot_id": 123,
      "start_time": "12:30:00",
      "end_time": "13:00:00",
      "is_available": false,
      "available_slot": 0,
      "single_slot_price": 50
    }
  ]
}
```

Illustrative values. The API retains unavailable rows for compatibility with dashboard schedules. The app must display/select only rows where `is_available == true` AND `available_slot > 0`. An unavailable row is not an offer to book.

## Meaning of availability

Scheduled capacity is capped by mapped physical consoles free of current sessions and overlapping assigned upcoming bookings. A current session continues holding its consoles past its scheduled end, including across midnight, until checkout/release changes its status. Squad assignments and duplicate dashboard rows are counted by distinct physical console. Current holds conservatively block future slot offers too until released; the API does not predict when an overtime gamer will leave. Existing scheduled capacity limits remain in force.

Example: three PlayStations held by live sessions => `available_slot: 0`, `is_available: false`. Releasing one => up to one available, subject to other reservations and scheduled capacity. The batch endpoint `/api/getSlotsBatch/vendor/{vendorId}` uses the same check.

## Frontend team checklist

- Fetch again on date/platform changes, screen resume and immediately before checkout. A response is a snapshot, not a reservation.
- Respect `Cache-Control: no-store`; do not persist/reuse slot responses as live availability.
- Clear selected slots that disappear or become unavailable after refresh.
- For a squad needing multiple consoles, require `available_slot >= required console count`.
- On booking rejection, refresh availability and prompt the customer to choose again. The server booking/payment response remains authoritative.
- On network failure, show retry/unavailable; do not assume missing flags mean available. Some current app fallback branches default to available; the frontend team should change those to fail closed.
- With no eligible slots, show “No consoles available for this time. Please choose another time or try again later.”

## Acceptance checks

1. Occupy all three PS consoles, let their booked end times pass: no eligible PS slots appear after refresh.
2. Check out one session: at most one free PS is offered after refresh.
3. Keep a session active overnight: the hold is still applied the next day.
4. Complete/cancel an assigned reservation: it no longer blocks the console.
5. Verify independent café/platform queries do not inherit another café's holds.

No new database migration is needed for this fix. This does not change app pricing or enable game-specific app checkout.
