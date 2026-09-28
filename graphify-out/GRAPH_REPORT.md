# Graph Report - hfg-booking  (2026-09-28)

## Corpus Check
- 92 files · ~58,557 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 699 nodes · 1609 edges · 54 communities (46 shown, 8 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 28 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `844f263c`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- cancel_bookings_with_refund
- booking_controller.py
- game_controller.py
- realtime.py
- extensions.py
- HFG Booking Service
- mail_service.py
- slot_controller.py
- route
- Flask
- date
- gaming_type_controller.py
- BookingBatchWritesTests
- pass_controller.py
- extra_booking
- DeferredBookingRealtime
- ReleaseTests
- get_user_details
- new_booking
- PassService
- kiosk_book_next_slot
- pay_at_cafe_email_action
- route
- App Booking Cancellation API
- ConsolePricingOffer
- test_slot_cache.py
- .redeem_pass_hours
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
- UpcomingSlotTests
- auth_required_self
- UserPass

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
- `BookingService` --uses--> `CafePass`  [INFERRED]
  services/booking_service.py → models/passModels.py
- `BookingService` --uses--> `UserPass`  [INFERRED]
  services/booking_service.py → models/passModels.py
- `PassService` --uses--> `UserPass`  [INFERRED]
  services/pass_service.py → models/passModels.py
- `BookingService` --uses--> `Slot`  [INFERRED]
  services/booking_service.py → models/slot.py
- `PassService` --uses--> `Slot`  [INFERRED]
  services/pass_service.py → models/slot.py

## Import Cycles
- None detected.

## Communities (54 total, 8 thin omitted)

### Community 0 - "cancel_bookings_with_refund"
Cohesion: 0.17
Nodes (16): _append_cancellation_note(), _booking_slot_start_datetime_ist(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), cancel_bookings_with_refund(), _credit_wallet_for_cancellation(), _default_repayment_type() (+8 more)

### Community 1 - "booking_controller.py"
Cohesion: 0.12
Nodes (17): calculate_slot_minutes(), credit_unused_slots_to_wallet(), _ensure_vendor_pay_at_cafe_settings_table(), get_pay_at_cafe_settings(), _get_vendor_pay_at_cafe_settings(), Credit unused booked slots to user's time wallet. Body: { "user_id": 1,…, _save_vendor_pay_at_cafe_settings(), update_pay_at_cafe_settings() (+9 more)

### Community 2 - "game_controller.py"
Cohesion: 0.13
Nodes (30): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+22 more)

### Community 3 - "realtime.py"
Cohesion: 0.20
Nodes (18): BlockLike, direct_booking(), TimeLike, _as_date_str(), _as_mapping(), build_booking_event_payload(), _canonical_payload(), _coalesce() (+10 more)

### Community 4 - "extensions.py"
Cohesion: 0.05
Nodes (28): Reject a direct booking and handle slot release & repayment., redeem_voucher(), reject_booking(), configure_socketio(), Configures SocketIO with the Flask app., AccessBookingCode, AvailableGame, Booking (+20 more)

### Community 5 - "HFG Booking Service"
Cohesion: 0.05
Nodes (40): Client changes, Different errors need different UI handling, Mobile checkout: cafe context required, POST /api/capture_payment, POST /api/create_order, POST /api/generate_payment_link (if used), Validation completed, Why the payment screen fails (+32 more)

### Community 6 - "mail_service.py"
Cohesion: 0.20
Nodes (15): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., booking_mail(), extra_booking_time_mail() (+7 more)

### Community 7 - "slot_controller.py"
Cohesion: 0.08
Nodes (27): _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots(), get_slots_batch(), get_slots_on_game_id() (+19 more)

### Community 8 - "route"
Cohesion: 0.10
Nodes (23): capture_payment(), create_order(), create_render_one_off_job(), generate_payment_link(), get_all_booking(), get_booking_details(), get_console_status(), get_time_wallet() (+15 more)

### Community 9 - "Flask"
Cohesion: 0.10
Nodes (22): Config, create_app(), _is_insecure_secret(), _validate_production_config(), cafe_checkout_token(), digest(), issue_token(), Short-lived gamer checkout identity, using existing Hash auth or email OTP. (+14 more)

### Community 10 - "date"
Cohesion: 0.16
Nodes (17): _coerce_date_value(), _ensure_pay_at_cafe_action_logs_table(), _fetch_pay_at_cafe_queue_id_sets(), get_pay_at_cafe_queue_list(), get_pay_at_cafe_queue_summary(), get_pending_pay_at_cafe_bookings(), get_slot_bookings(), get_user_bookings() (+9 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 13 - "pass_controller.py"
Cohesion: 0.22
Nodes (15): _cleanup_pass_otp_cache(), _consume_pass_verification_token(), _find_live_otp_session(), get_available_passes_for_purchase(), _hash_otp(), _mask_email(), _otp_secret(), _passes_cache_get() (+7 more)

### Community 14 - "extra_booking"
Cohesion: 0.15
Nodes (19): add_meals_to_booking(), booking_payment_summary(), calculate_gst_breakdown(), compute_booking_financial_summary(), extra_booking(), normalize_payment_use_case(), Settle monthly credit outstanding at month-end. Body: { "user_id": 1, "amount":…, Records extra booking (time extended) played by the user in a gaming cafe, with… (+11 more)

### Community 15 - "DeferredBookingRealtime"
Cohesion: 0.18
Nodes (6): patch, DeferredBookingRealtime, Keep best-effort realtime delivery outside committed booking responses., BookingMailTests, Test the production background mail helper without booting network services., BookingRealtimeTests

### Community 17 - "get_user_details"
Cohesion: 0.10
Nodes (17): _build_squad_member_bindings(), _collect_vendor_user_ids(), _ensure_vendor_booking_field_preferences_table(), get_user_details(), _load_vendor_booking_field_config(), _normalize_vendor_booking_field_config(), _resolve_or_create_squad_member_user(), _save_vendor_booking_field_config() (+9 more)

### Community 18 - "new_booking"
Cohesion: 0.08
Nodes (51): booking_pricing_estimate(), booking_pricing_preview(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), _compute_pay_at_cafe_pricing(), confirm_booking(), _consume_menu_stock(), create_booking() (+43 more)

### Community 19 - "PassService"
Cohesion: 0.17
Nodes (7): Decimal, CafePass, PassRedemptionLog, PassType, Validate pass configuration, PassService, Calculate hours for a slot based on pass configuration. Args: slot_id: Slot ID…

### Community 20 - "kiosk_book_next_slot"
Cohesion: 0.17
Nodes (17): _coerce_int_value(), compute_credit_due_date(), _ensure_vendor_slot_rows_for_date(), _ist_now_naive(), kiosk_book_next_slot(), kiosk_check_next_slot(), _precheck_slot_booking_eligibility(), datetime (+9 more)

### Community 21 - "pay_at_cafe_email_action"
Cohesion: 0.24
Nodes (10): _build_pay_at_cafe_email_action_url(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url(), _resolve_dashboard_public_url() (+2 more)

### Community 22 - "route"
Cohesion: 0.17
Nodes (12): cancel_redemption(), get_dashboard_user_valid_passes(), get_pass_history(), get_user_active_passes(), route, Validate pass UID and return pass details. Used by dashboard before redemption., Dashboard helper: Return valid hour-based passes for a selected user at a…, Get all active passes for authenticated user. (+4 more)

### Community 23 - "App Booking Cancellation API"
Cohesion: 0.20
Nodes (9): App Booking Cancellation API, Cancellation fee envs, Endpoint, Failure responses, Real-time socket events emitted, Request, Request fields, Strategy implemented (+1 more)

### Community 24 - "ConsolePricingOffer"
Cohesion: 0.24
Nodes (5): ConsolePricingOffer, Time-based promotional pricing for console types (AvailableGames) Allows…, Check if this offer is active RIGHT NOW using IST. Returns True if current IST…, Calculate discount percentage, Convert to dictionary for API responses

### Community 25 - "test_slot_cache.py"
Cohesion: 0.47
Nodes (3): load(), Exercise actual slot readers with a warm cache and mocked database boundary., SlotCacheTests

### Community 26 - ".redeem_pass_hours"
Cohesion: 0.20
Nodes (9): Redeem pass from dashboard (vendor scans pass). Staff ID removed - vendor scans…, Redeem pass during app booking flow. Called during booking confirmation., redeem_pass_app(), redeem_pass_dashboard(), date, Deduct hours from pass and create redemption log. Args: user_pass_id: UserPass…, Cancel a redemption and restore hours to pass. Args: redemption_id:…, Get valid hour-based pass for user. Priority: 1. If pass_uid provided, validate… (+1 more)

### Community 28 - "accept_pay_at_cafe_booking"
Cohesion: 0.15
Nodes (15): accept_pay_at_cafe_booking(), _invalidate_pay_at_cafe_vendor_cache(), _json_text_equals(), _log_pay_at_cafe_action(), _parse_json_details(), Dialect-safe JSON text comparison (SQLAlchemy 2.0 removed .astext)., Resolve pay-at-cafe squad bookings by batch_id with a safe fallback that avoids…, Accept a pay-at-cafe booking and change status to confirmed (+7 more)

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

### Community 51 - "UpcomingSlotTests"
Cohesion: 0.27
Nodes (3): move_slot(), Atomic schedule changes for upcoming bookings; financial records stay intact., UpcomingSlotTests

### Community 52 - "auth_required_self"
Cohesion: 0.20
Nodes (9): create_hour_pass(), Create hour-based pass after purchase (called after payment confirmation)., auth_required(), auth_required_self(), decode_user(), encode_user(), Encode a user ID using RSA public key PEM string. Returns a base64-encoded…, Decode the encrypted user ID using RSA private key PEM string. (+1 more)

### Community 53 - "UserPass"
Cohesion: 0.28
Nodes (5): purchase_pass(), User purchases a pass after Razorpay payment. Creates UserPass record with…, Generate unique pass UID for hour-based passes, UserPass, Create hour-based user pass after purchase. Args: user_id: User ID…

## Knowledge Gaps
- **39 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeferredBookingRealtime` connect `DeferredBookingRealtime` to `booking_controller.py`, `new_booking`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Why does `Slot` connect `slot_controller.py` to `booking_controller.py`, `PassService`, `extensions.py`, `pass_controller.py`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `BookingService` connect `extensions.py` to `cancel_bookings_with_refund`, `booking_controller.py`, `game_controller.py`, `slot_controller.py`, `date`, `release_slot_controller`, `new_booking`, `PassService`, `UserPass`, `accept_pay_at_cafe_booking`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `booking_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.11965811965811966 - nodes in this community are weakly interconnected._
- **Should `game_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.13205128205128205 - nodes in this community are weakly interconnected._