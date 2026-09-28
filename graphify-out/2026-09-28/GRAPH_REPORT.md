# Graph Report - hfg-booking  (2026-09-28)

## Corpus Check
- 90 files · ~57,801 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 686 nodes · 1583 edges · 54 communities (45 shown, 9 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 28 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8e9ebcec`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- cancel_bookings_with_refund
- booking_controller.py
- game_controller.py
- kiosk_book_next_slot
- booking_service.py
- HFG Booking Service
- mail_service.py
- slot_controller.py
- route
- Flask
- get_pending_pay_at_cafe_bookings
- gaming_type_controller.py
- BookingBatchWritesTests
- pass_controller.py
- extensions.py
- DeferredBookingRealtime
- ReleaseTests
- search_booked_customers
- new_booking
- CafePass
- Voucher
- pay_at_cafe_email_action
- credit_unused_slots_to_wallet
- App Booking Cancellation API
- ConsolePricingOffer
- test_slot_cache.py
- BookingService
- accept_pay_at_cafe_booking
- trigger_once
- main_loop
- vendor_console_overrides
- vendor_booking_field_preferences
- AGENTS.md
- jobs/__init__.py
- 20260817_booking_gateway_payment_reconciliation.sql
- extra_service_menus
- transactions
- release_slot_controller
- Booking
- Slot
- _load_vendor_booking_field_config

## God Nodes (most connected - your core abstractions)
1. `new_booking()` - 51 edges
2. `confirm_booking()` - 35 edges
3. `BookingService` - 31 edges
4. `accept_pay_at_cafe_booking()` - 21 edges
5. `Transaction` - 20 edges
6. `auth_required_self()` - 19 edges
7. `extra_booking()` - 18 edges
8. `Slot` - 18 edges
9. `kiosk_book_next_slot()` - 17 edges
10. `add_meals_to_booking()` - 16 edges

## Surprising Connections (you probably didn't know these)
- `BookingService` --uses--> `AvailableGame`  [INFERRED]
  services/booking_service.py → models/availableGame.py
- `BookingService` --uses--> `Booking`  [INFERRED]
  services/booking_service.py → models/booking.py
- `BookingService` --uses--> `BookingExtraService`  [INFERRED]
  services/booking_service.py → models/bookingExtraService.py
- `BookingService` --uses--> `ExtraServiceMenu`  [INFERRED]
  services/booking_service.py → models/extraServiceMenu.py
- `BookingService` --uses--> `ExtraServiceMenuImage`  [INFERRED]
  services/booking_service.py → models/extraServiceMenuImage.py

## Import Cycles
- None detected.

## Communities (54 total, 9 thin omitted)

### Community 0 - "cancel_bookings_with_refund"
Cohesion: 0.13
Nodes (20): _append_cancellation_note(), _booking_slot_start_datetime_ist(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), cancel_bookings_with_refund(), _credit_wallet_for_cancellation(), _default_repayment_type() (+12 more)

### Community 1 - "booking_controller.py"
Cohesion: 0.08
Nodes (28): _build_squad_member_bindings(), _collect_vendor_user_ids(), _ensure_vendor_pay_at_cafe_settings_table(), get_pay_at_cafe_settings(), get_user_details(), _get_vendor_pay_at_cafe_settings(), _menu_stock_unit(), _normalize_slot_ids() (+20 more)

### Community 2 - "game_controller.py"
Cohesion: 0.13
Nodes (31): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+23 more)

### Community 3 - "kiosk_book_next_slot"
Cohesion: 0.10
Nodes (32): BlockLike, _coerce_int_value(), _ensure_vendor_slot_rows_for_date(), _ist_now_naive(), kiosk_book_next_slot(), kiosk_check_next_slot(), _precheck_slot_booking_eligibility(), datetime (+24 more)

### Community 4 - "booking_service.py"
Cohesion: 0.16
Nodes (6): BookingExtraService, ExtraServiceMenu, ExtraServiceMenuImage, HashWallet, HashWalletTransaction, User

### Community 5 - "HFG Booking Service"
Cohesion: 0.05
Nodes (40): Client changes, Different errors need different UI handling, Mobile checkout: cafe context required, POST /api/capture_payment, POST /api/create_order, POST /api/generate_payment_link (if used), Validation completed, Why the payment screen fails (+32 more)

### Community 6 - "mail_service.py"
Cohesion: 0.16
Nodes (18): Reject a direct booking and handle slot release & repayment., reject_booking(), HTMLParser, Updates the booking status in the vendor dashboard table for a given…, build_hfg_email_html(), email_text(), _EmailText, _extract_body() (+10 more)

### Community 7 - "slot_controller.py"
Cohesion: 0.13
Nodes (23): _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots(), get_slots_batch(), get_slots_on_game_id() (+15 more)

### Community 8 - "route"
Cohesion: 0.07
Nodes (29): booking_payment_summary(), capture_payment(), create_order(), create_render_one_off_job(), generate_payment_link(), get_all_booking(), get_booking_details(), get_console_status() (+21 more)

### Community 9 - "Flask"
Cohesion: 0.10
Nodes (22): Config, create_app(), _is_insecure_secret(), _validate_production_config(), cafe_checkout_token(), digest(), issue_token(), Short-lived gamer checkout identity, using existing Hash auth or email OTP. (+14 more)

### Community 10 - "get_pending_pay_at_cafe_bookings"
Cohesion: 0.21
Nodes (11): _ensure_pay_at_cafe_action_logs_table(), _fetch_pay_at_cafe_queue_id_sets(), get_pay_at_cafe_queue_list(), get_pay_at_cafe_queue_summary(), get_pending_pay_at_cafe_bookings(), get_user_bookings(), _parse_pay_at_cafe_queue_date_filters(), _pay_at_cafe_queue_date_predicate() (+3 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 13 - "pass_controller.py"
Cohesion: 0.05
Nodes (54): cancel_redemption(), _cleanup_pass_otp_cache(), _consume_pass_verification_token(), create_hour_pass(), _find_live_otp_session(), get_available_passes_for_purchase(), get_dashboard_user_valid_passes(), get_pass_history() (+46 more)

### Community 14 - "extensions.py"
Cohesion: 0.21
Nodes (5): configure_socketio(), Configures SocketIO with the Flask app., HashCoinTransaction, PassType, Vendor

### Community 15 - "DeferredBookingRealtime"
Cohesion: 0.18
Nodes (6): patch, DeferredBookingRealtime, Keep best-effort realtime delivery outside committed booking responses., BookingMailTests, Test the production background mail helper without booting network services., BookingRealtimeTests

### Community 17 - "search_booked_customers"
Cohesion: 0.33
Nodes (3): Bounded customer lookup across a cafe's complete booking history., search_booked_customers(), CustomerSearchTests

### Community 18 - "new_booking"
Cohesion: 0.09
Nodes (61): add_meals_to_booking(), booking_pricing_estimate(), booking_pricing_preview(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), calculate_gst_breakdown(), _coerce_date_value(), compute_booking_financial_summary() (+53 more)

### Community 20 - "Voucher"
Cohesion: 0.47
Nodes (3): redeem_voucher(), Voucher, create_referral_voucher()

### Community 21 - "pay_at_cafe_email_action"
Cohesion: 0.24
Nodes (10): _build_pay_at_cafe_email_action_url(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url(), _resolve_dashboard_public_url() (+2 more)

### Community 22 - "credit_unused_slots_to_wallet"
Cohesion: 0.40
Nodes (5): calculate_slot_minutes(), credit_unused_slots_to_wallet(), Credit unused booked slots to user's time wallet. Body: { "user_id": 1,…, TimeWalletAccount, TimeWalletLedger

### Community 23 - "App Booking Cancellation API"
Cohesion: 0.20
Nodes (9): App Booking Cancellation API, Cancellation fee envs, Endpoint, Failure responses, Real-time socket events emitted, Request, Request fields, Strategy implemented (+1 more)

### Community 24 - "ConsolePricingOffer"
Cohesion: 0.24
Nodes (5): ConsolePricingOffer, Time-based promotional pricing for console types (AvailableGames) Allows…, Check if this offer is active RIGHT NOW using IST. Returns True if current IST…, Calculate discount percentage, Convert to dictionary for API responses

### Community 25 - "test_slot_cache.py"
Cohesion: 0.47
Nodes (3): load(), Exercise actual slot readers with a warm cache and mocked database boundary., SlotCacheTests

### Community 26 - "BookingService"
Cohesion: 0.12
Nodes (7): PaymentTransactionMapping, BookingService, Create a booking with specified mode. Args: booking_mode: 'regular' or…, Batch dashboard/promo writes in the caller's transaction using loaded data., Inserts booking and transaction details into the vendor dashboard table., Inserts promo details into the vendor-specific promo table., Return the best valid pass or None.

### Community 28 - "accept_pay_at_cafe_booking"
Cohesion: 0.22
Nodes (13): accept_pay_at_cafe_booking(), _invalidate_pay_at_cafe_vendor_cache(), _json_text_equals(), _log_pay_at_cafe_action(), _parse_json_details(), Dialect-safe JSON text comparison (SQLAlchemy 2.0 removed .astext)., Resolve pay-at-cafe squad bookings by batch_id with a safe fallback that avoids…, Accept a pay-at-cafe booking and change status to confirmed (+5 more)

### Community 29 - "trigger_once"
Cohesion: 0.53
Nodes (5): build_headers(), http_post_with_retries(), main(), Call the scanner endpoint once and log the outcome., trigger_once()

### Community 30 - "main_loop"
Cohesion: 0.50
Nodes (4): main_loop(), Find unverified bookings older than 2 minutes from transactions in the last 1…, Run every 30 seconds for 30 days., release_unverified_slots()

### Community 31 - "vendor_console_overrides"
Cohesion: 0.67
Nodes (3): console_catalog, vendors, vendor_console_overrides

### Community 49 - "release_slot_controller"
Cohesion: 0.29
Nodes (6): now_utc(), Releases bookings stuck in 'pending_verified' that are older than 2 minutes.…, release_slot(), release_slot_controller(), to_utc(), Release an unverified booking once, atomically with its capacity.

### Community 51 - "Booking"
Cohesion: 0.22
Nodes (5): AccessBookingCode, AvailableGame, Booking, Updated to include private booking fields, BookingSquadMember

### Community 52 - "Slot"
Cohesion: 0.19
Nodes (4): Return a dictionary representation of the Slot object., Return a dictionary representation of the Slot object., Slot, SlotService

### Community 53 - "_load_vendor_booking_field_config"
Cohesion: 0.47
Nodes (6): _ensure_vendor_booking_field_preferences_table(), _load_vendor_booking_field_config(), _normalize_vendor_booking_field_config(), _save_vendor_booking_field_config(), _to_bool(), vendor_booking_field_config()

## Knowledge Gaps
- **39 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeferredBookingRealtime` connect `DeferredBookingRealtime` to `booking_controller.py`, `new_booking`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Why does `BookingService` connect `BookingService` to `cancel_bookings_with_refund`, `booking_controller.py`, `game_controller.py`, `booking_service.py`, `mail_service.py`, `get_pending_pay_at_cafe_bookings`, `pass_controller.py`, `release_slot_controller`, `new_booking`, `CafePass`, `Booking`, `Slot`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `Slot` connect `Slot` to `booking_controller.py`, `booking_service.py`, `slot_controller.py`, `pass_controller.py`, `extensions.py`, `Booking`, `credit_unused_slots_to_wallet`, `BookingService`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `cancel_bookings_with_refund` be split into smaller, more focused modules?**
  _Cohesion score 0.13333333333333333 - nodes in this community are weakly interconnected._
- **Should `booking_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07560975609756097 - nodes in this community are weakly interconnected._