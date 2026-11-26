# Flex-start bookings ("start at any minute")

A gamer walks in at 10:12 and wants 2 hours. The cafe's slots are 1 hour.
With flex start the desk books **10:12 – 12:12**, holds the 10:00, 11:00 and
12:00 slots so the app and website never oversell, keeps the exact window on
the dashboard, kiosk and live-session cards, and prices the real 120 minutes.

Flex is **opt-in per cafe** and **additive**. With the cafe setting off, or
when a request does not send `timingMode: "flex"`, every existing slot flow
(Hash app, HFG-frontend, website, kiosk, desk) runs exactly as before.

## 1. How the current model works (what flex builds on)

| Piece | Where | Used for |
|---|---|---|
| `slots` | template rows per device type (`gaming_type_id`) with `start_time`/`end_time` | the cafe's slot grid = its opening hours |
| `VENDOR_<id>_SLOT(date, slot_id, available_slot, is_available)` | dated capacity, one unit per station | every booking path reserves/releases here (`services/slot_capacity.py`, identical copy in hfg-dashboard) |
| `bookings.slot_id` + `squad_details.booked_date` / `transactions.booked_date` | the slot a booking holds | app/website booking lists, cancellations, the slot grid's leak-repair floor |
| `VENDOR_<id>_DASHBOARD(date, start_time, end_time, console_id, book_status)` | one row per booking | **source of truth for the actual window**: landing page cards, kiosk `booking_window` / `reserved_until`, console-conflict triggers (`cafe_guard_assignment`, `desk_guard_assignment`), overtime `chain_end`, follow-on adoption |
| `cafe_slot_reservations(session_id, vendor_id, date, slot_id, units, released_at)` | extra dated holds (QR play, kiosk extensions) | counted by the slot grid's repair floor (`_load_qr_held_units`) |
| Desk walk-in | hash-dashboard `newSlot.tsx` → `POST /api/newBooking/vendor/<id>` | one booking per selected slot, transactions, meals, squads, pass, credit |
| Live session / extend / end | hfg-dashboard `session_extensions.py` (`attach`, `quote`/`grant`, `finish` → `release_base_booking`), `kiosk_runtime.py` (`adopt_follow_on_bookings`, `_stretch_runtime`) | kiosk time, extensions, base slot release at end |
| Desk overtime | hfg-booking `overtime_quote.py`, `/extraBooking` | bills play after the dashboard chain end |

Key consequence: because kiosk, overview, conflict guards and overtime all read
the **dashboard row's times**, writing the exact flex window there makes them
flex-aware without changing their code. The slot grid's repair floor counts
`booking.slot_id` plus `cafe_slot_reservations`, so the *other* overlapped slots
must be recorded in `cafe_slot_reservations` or the repair would hand the units
back (oversell).

## 2. Data

Migration: `sql/20261126_flex_start_bookings.sql` (additive, idempotent, not applied by code).

* `bookings.start_at timestamptz`, `end_at timestamptz`, `duration_minutes int`,
  `timing_mode varchar(10)` – all nullable. `NULL` = legacy slot booking
  (window derived from the slot). Check constraints (`NOT VALID`, so no table
  scan): `timing_mode IN ('slot','flex')`, and a flex row must have a window.
* `vendor_flex_booking_settings` (one row per cafe; no row = off):
  `flex_enabled false`, `min_minutes 30`, `step_minutes 15`,
  `late_arrival_policy 'keep_end' | 'shift_if_free'`, `allow_past_closing false`,
  `partial_slot_grace_minutes 0`.
* Flex holds reuse `cafe_slot_reservations` with `session_id = 'flex:<booking_id>'`.
* The SQLAlchemy `Booking` model is **not** changed: the new columns are written
  and read with SQL only, so code deployed before the migration keeps working
  and flex endpoints answer `503 migration_required` until it is applied.

A flex booking still has `slot_id` (the **base** slot, dated on the window's
start date) and a booked date, so the Hash app / HFG-frontend booking lists
render it; they ignore the new fields.

Intervals are half-open `[start, end)`: a booking ending 12:00 never conflicts
with one starting 12:00. All times are IST wall-clock; aware inputs (`Z`,
`+05:30`) are converted, naive inputs are IST.

## 3. Rules

### Blocking and availability
* A window consumes one unit (one per player for PC squads) on **every dated
  slot it overlaps**. 10:12–12:12 consumes 10:00, 11:00 and 12:00. The base
  slot is reserved by the normal `BookingService.create_booking`; the others by
  `slot_capacity.reserve_slot` + a `flex:<id>` row.
* Optional `partial_slot_grace_minutes = N`: an *edge* slot overlapped by ≤ N
  minutes is not consumed, **only if that slot still has at least one more free
  station than this booking needs** (otherwise the overlap would oversell it).
  Default 0 = any overlap consumes. Must be shorter than `min_minutes`.
* Station level: a flex booking is assigned specific station(s) at creation that
  are free for the whole window, checking dashboard rows (slot windows and flex
  windows, including squad `assigned_console_ids` minus released ones), live
  sessions (held until the next half hour + 1h, same as `live_slot_capacity`),
  QR claims (`cafe_play_sessions`) and maintenance.
* Slot capacity also limits the window: unassigned app bookings have no station
  yet, so the first overlapped slot without room ends the window (walk-in 10:12
  wants 2h, the 12:00 slot is full → "only 108 minutes fit", offered in the UI).
* Concurrency: overlapped `VENDOR_<id>_SLOT` rows are locked `FOR UPDATE` in
  `(date, slot_id)` order, then the device type's `consoles` rows in id order
  (the same lock the desk guard and QR claims take); capacity is re-checked
  under the lock. The DB triggers on the dashboard table remain the last line.
* Closing time: the cafe's slot grid is its opening hours. A window must stay
  inside the contiguous run of slots containing its start (24h cafes run across
  midnight), unless `allow_past_closing`; the refusal carries `max_minutes`
  until close. Starts with no slot at all are refused (`closed`).
* Start may be up to 30 minutes in the past (desk entering a walk-in late).

### Pricing
* Rate card (desk picked a session rate): `desk_pricing.quote(card, minutes, players)`
  through the existing card selection/revision/game checks
  (`desk_operations.checked_desk_card`, shared with slot pricing).
* No card: per-slot price (`get_effective_price_for_schedule`, so offers apply)
  prorated per minute, **billed in `step_minutes` increments, rounded up to the
  rupee, never more than ceil(minutes / slot length) × slot price**. PC squads
  multiply by players and get the same squad discount as slot bookings.
* Extensions are priced marginally: `price(previous + extra) - price(previous)`
  (the same formula as the extra-play rate-card work).
* Taxes, waive-off, meals, controllers, wallet/credit and receipts go through
  the unchanged `newBooking` billing path. Pass checkout keeps slot times
  (refused for flex with a clear message).

### Lifecycle
* **Cancel / reject / no-show** (any hfg-booking path that calls
  `_release_slot_for_booking`): base slot released as before, then every
  `flex:<id>` hold. No-op for slot bookings.
* **End session** (hfg-dashboard `finish` → `release_base_booking`): when every
  station of the booking is released, the `flex:<id>` holds go back too.
  *Deviation from the brief:* the brief says a partly used slot stays consumed.
  The live code already releases the (partly used) base slot when a session
  ends because the station is physically free, so flex follows the same rule
  for all its holds; otherwise a 10:12–12:12 session ended at 11:05 would keep
  the 11:00 slot blocked while its station sits empty. Refund behaviour is not
  changed. The pure rule `released_after(held, new_end)` (slots starting at or
  after a new end) exists and is tested for a future "shorten" action.
* **Extension** at the desk = a contiguous flex booking for the same gamer on
  the same station (`extendsBookingId`), so payment, holds, overtime chain and
  kiosk adoption all reuse existing paths; the quote returns the longest
  extension that fits (partial offer) when the next booking is in the way. The
  kiosk's own extension (`session_extensions.grant`) now treats slots already
  held under `flex:<booking_id>` as held, so it never holds them twice.
* **Late arrival** for an upcoming booking (`/arrival`): `keep_end` → start now,
  same end, same price; `shift_if_free` → start now, keep the duration if the
  station and the newly overlapped slots are free (refused when the booking
  continues into another booked slot). **Early arrival** → start now, keep the
  duration, if the station is free. Price is unchanged in every case.
* Kiosk: `booking_window` already derives `start_time`/`end_time` and
  `reserved_until` from the dashboard row, so it follows the flex window; it now
  also returns optional `timing_mode`, `start_at`, `end_at` for flex bookings.

## 4. Use cases covered (tests)

| # | Case | Result | Test |
|---|---|---|---|
| 1 | Walk-in 10:12 × 2h | 10:12–12:12, slots 10/11/12 held, price 2 slots | `test_flex_timing::test_walk_in_window…`, `test_flex_booking_db::test_quote_walk_in…`, `…test_create_consumes…` |
| 2 | Station has a later booking | that station offers 108 min, other station suggested; overlap refused | `test_station_with_later_booking…` (pure + DB) |
| 3 | Back-to-back flex on one station | allowed; overlapping refused | `test_half_open…`, `test_create_consumes_slots_back_to_back…` |
| 4 | App books 12:00 while flex holds a station | allowed while capacity remains, refused when full; hold rows match the grid's repair floor | `test_slot_bookings_share_capacity_with_flex_windows`, `test_full_slot_limits_window…` |
| 5 | Extension crossing into a new slot / conflict | marginal price, partial offer (48 min) | `test_extension_quote_marginal_price…`, `test_marginal_extension_price…`, hfg-dashboard `test_kiosk_follows_flex_window_extension…` |
| 6 | Early end / cancel | holds released once; legacy no-op | `test_release_holds_returns_units_once`, hfg-dashboard `test_kiosk_follows…`, `test_partial_squad_release…`, `test_shorten_releases_only_untouched_slots` |
| 7 | Late arrival 11:20 for 11:00–12:00 | keep_end 11:20–12:00; shift_if_free 11:20–12:20 (+12:00 slot) or refused if busy | `test_late_arrival_policies`, `test_late_arrival_keep_end_and_shift_if_free`, `test_shift_refused_when_station_has_next_booking` |
| 8 | Early arrival 10:45 | 10:45–11:45, 10:00 slot added | `test_early_arrival…` (pure + DB) |
| 9 | 23:30 × 2h; closing | slots on both dates; refused past close with `max_minutes`, allowed with `allow_past_closing` | `test_overnight_window…`, `test_closing_time…`, `test_overnight_window_and_closing` |
| 10 | Squad | one station + one unit per PC player, per-player price and squad discount | `test_squad_units…`, `test_squad_needs_two_stations…` |
| 11 | IST | UTC/IST/naive inputs agree; no device-zone math in the UI | `test_start_parsing_is_ist…`, `test_quote_walk_in…`, `flex-booking.test.cjs` |
| 12 | Flex off / not migrated | 403 `flex_disabled` / 503 `migration_required`; slot flows unchanged | `test_flex_disabled…`, `test_missing_migration…` |
| 13 | Legacy slot booking | every flex call in `new_booking` sits behind a flex guard; dashboard rows keep slot windows; release path unchanged + no-op | `test_flex_legacy_guard.py`, full existing suites unchanged |
| 14 | Kiosk / overview | kiosk window, `reserved_until` = flex end; overview rows carry `timingMode/startAt/endAt` | hfg-dashboard `test_flex_bookings.py` |
| 15 | Two requests for the last unit | exactly one wins | `test_concurrent_requests_for_last_unit` |
| + | Base slot dated on window start (cross-midnight slot) | base chosen on start date, previous-day slot held as extra | `test_base_slot_is_dated_on_the_window_start` |
| + | Grace only when another station is free | | `test_partial_slot_grace…` |
| + | Rate card prices exact duration | 100 min at ₹90/h → ₹150 | `test_rate_card_prices_exact_duration` |

## 5. API (hfg-booking, all under `/api`)

### `GET /vendor/<vendor_id>/flex-booking/settings` (booking.manage)
`{"success": true, "settings": {flex_enabled, min_minutes, step_minutes, late_arrival_policy, allow_past_closing, partial_slot_grace_minutes}, "schema_ready": true}`

### `PUT /vendor/<vendor_id>/flex-booking/settings` (account.manage)
Body: any subset of the settings. Returns the merged settings. 400 on invalid values.

### `POST /vendor/<vendor_id>/flex-booking/quote` (booking.manage, read-only)
```json
{"gameId": 3, "startAt": "2026-11-26T10:12:00+05:30" | "now", "durationMinutes": 120,
 "players": 1, "squadDetails": {"enabled": false, "playerCount": 1},
 "deskProfile": "std", "deskRevision": 4, "pricingGame": "", "extendsBookingId": 1234}
```
200:
```json
{"success": true, "timing_mode": "flex", "game_id": 3,
 "window": {"start_at": "2026-11-26T10:12:00+05:30", "end_at": "2026-11-26T12:12:00+05:30",
            "date": "2026-11-26", "start": "10:12", "end": "12:12", "duration_minutes": 120,
            "label": "10:12 – 12:12", "crosses_midnight": false},
 "live": false, "booked_date": "2026-11-26", "base_slot_id": 110,
 "blocked_slots": [{"slot_id": 110, "date": "2026-11-26", "start_time": "10:00", "end_time": "11:00", "available_slot": 2}, "…"],
 "units": 1,
 "stations": [{"console_id": 11, "name": "PC 1", "available": false, "max_minutes_available": 108,
               "next_busy_at": "2026-11-26T12:00:00+05:30"}, "…"],
 "available": true, "recommended_console_ids": [12], "max_minutes_available": 720,
 "closes_at": "2026-11-27T00:00:00+05:30",
 "price": {"basis": "slot_prorated" | "rate_card", "unit_price": 200.0, "base_amount": 200.0,
           "squad_discount_percent": 0.0, "squad_discount_amount": 0.0, "net_amount": 200.0,
           "billed_minutes": 120, "players": 1, "multiplier": 1},
 "extends_booking_id": null, "settings": {"…": "…"}}
```
Errors: `{"success": false, "code": "...", "message": "...", "max_minutes"?: 108, "limit_at"?: "...", "stations"?: [...]}` with codes
`flex_disabled` 403, `migration_required` 503, `invalid_game` 400/404, `invalid_start` 400, `too_short` 400,
`start_in_past` 400, `window_ended` 400, `closed` 409, `too_long` 409, `slot_full` 409, `no_base_slot` 409,
`station_busy` 409, `extension_gap` 409, `not_extendable` 409.

### Create: existing `POST /newBooking/vendor/<vendor_id>` + optional fields
`timingMode: "flex"`, `gameId`, `startAt`, `durationMinutes`, optional `flexConsoleIds`,
`extendsBookingId`. Every existing field (customer, payment, meals, squad,
deskProfile/deskRevision/deskSubtotal, waive-off …) works as today; `slotId`
and `bookedDate` may be omitted (derived). The response adds `timing_mode`,
`start_at`, `end_at`, `duration_minutes`, `blocked_slots`, `console_ids`,
`flex_price`, `extends_booking_id`. Socket events keep their names
(`booking`, `booking_admin`, `current_slot`, `console_availability`) and add
the same optional `timing_mode/start_at/end_at/duration_minutes`; their
`time[].start_time/end_time` carry the exact window.

### `POST /vendor/<vendor_id>/flex-booking/<booking_id>/arrival` (booking.manage)
Body: `{"arrivedAt": "now" | ISO, "policy"?: "keep_end" | "shift_if_free"}` (default = cafe setting).
200: `{"success": true, "booking_id", "timing_mode": "flex", "policy", "start_at", "end_at", "console_id", "added_slots": [...], "released_slots": [...], "price_change": 0.0}`.
Emits `booking_updated` with the new window.

### hfg-dashboard (read side)
`GET /getLandingPage/vendor/<id>` rows of flex bookings add `timingMode`, `startAt`, `endAt`, `durationMinutes`
(times shown were already the flex window). Kiosk `booking_window` adds `timing_mode/start_at/end_at`.

## 6. hash-dashboard
* New Gaming Session → Session Time → **"Custom start (any minute)"** (only when
  the cafe enabled flex): start time (Now), duration in `step_minutes`, live
  quote with window, held slots, price, per-station availability with
  "Use 1h 48m" offers; submits through the same form with the flex fields.
* Settings → **Session Timing**: enable, shortest session, step, overlap grace,
  late-arrival policy, run past last slot (edit needs account.manage).
* Upcoming and live-session cards show the exact window (from the backend) and
  a small "Custom" tag for flex bookings.

## 7. Not done / follow-ups
* No hash-dashboard button yet for the `/arrival` (late/early) and desk
  extension flows; the endpoints are ready.
* Next-day `VENDOR_<id>_SLOT` rows are not self-healed by the flex path; if they
  are missing, an overnight window is limited to midnight (safe refusal).
* No-show sweeps leave `flex:<id>` holds on past slots (harmless: past capacity).
* The `bookings` partial index is created inside the migration transaction (a
  short write lock on `bookings`); run it `CONCURRENTLY` by hand if the table is large.
