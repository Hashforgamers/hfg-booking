# Graph Report - hfg-booking  (2026-09-22)

## Corpus Check
- 82 files · ~56,043 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 637 nodes · 1515 edges · 51 communities (42 shown, 9 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 25 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6f9bffbc`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- new_booking
- booking_controller.py
- game_controller.py
- kiosk_book_next_slot
- extensions.py
- HFG Booking Service
- mail_service.py
- slot_controller.py
- route
- Flask
- cancel_bookings_with_refund
- gaming_type_controller.py
- BookingService
- pass_controller.py
- pass_service.py
- reject_pay_at_cafe_booking
- ReleaseTests
- PassService
- _safe_decode_jwt_claims
- .redeem_pass_hours
- auth_required_self
- create_booking
- credit_unused_slots_to_wallet
- App Booking Cancellation API
- ConsolePricingOffer
- test_slot_cache.py
- UserPass
- trigger_once
- main_loop
- vendor_console_overrides
- vendor_booking_field_preferences
- AGENTS.md
- jobs/__init__.py
- 20260817_booking_gateway_payment_reconciliation.sql
- extra_service_menus
- transactions
- _load_vendor_booking_field_config
- _invalidate_pay_at_cafe_vendor_cache
- VendorTaxProfile

## God Nodes (most connected - your core abstractions)
1. `new_booking()` - 51 edges
2. `confirm_booking()` - 35 edges
3. `BookingService` - 30 edges
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

## Communities (51 total, 9 thin omitted)

### Community 0 - "new_booking"
Cohesion: 0.06
Nodes (78): accept_pay_at_cafe_booking(), add_meals_to_booking(), booking_pricing_estimate(), booking_pricing_preview(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), calculate_gst_breakdown(), _coerce_date_value() (+70 more)

### Community 1 - "booking_controller.py"
Cohesion: 0.09
Nodes (22): _build_squad_member_bindings(), _collect_vendor_user_ids(), get_user_details(), _menu_stock_unit(), _normalize_slot_ids(), _pricing_log_enabled(), _release_reserved_consoles(), _reserve_multiple_consoles() (+14 more)

### Community 2 - "game_controller.py"
Cohesion: 0.13
Nodes (31): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+23 more)

### Community 3 - "kiosk_book_next_slot"
Cohesion: 0.10
Nodes (32): BlockLike, _coerce_int_value(), _ensure_vendor_slot_rows_for_date(), _ist_now_naive(), kiosk_book_next_slot(), kiosk_check_next_slot(), _precheck_slot_booking_eligibility(), datetime (+24 more)

### Community 4 - "extensions.py"
Cohesion: 0.19
Nodes (6): configure_socketio(), Configures SocketIO with the Flask app., ExtraServiceMenu, ExtraServiceMenuImage, HashCoinTransaction, User

### Community 5 - "HFG Booking Service"
Cohesion: 0.06
Nodes (32): API Endpoints, Booking Controller, Booking (`models/booking.py`), BookingService (`services/booking_service.py`), Core Services, DELETE /bookings/<int:booking_id>, DELETE /gaming-types/<int:gaming_type_id>, Game Controller (+24 more)

### Community 6 - "mail_service.py"
Cohesion: 0.19
Nodes (16): _send_booking_mail_async(), HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., booking_mail() (+8 more)

### Community 7 - "slot_controller.py"
Cohesion: 0.07
Nodes (31): _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots(), get_slots_batch(), get_slots_on_game_id() (+23 more)

### Community 8 - "route"
Cohesion: 0.09
Nodes (23): booking_payment_summary(), create_render_one_off_job(), get_all_booking(), get_booking_details(), get_console_status(), get_slot_bookings(), get_time_wallet(), get_vendor_booking_stats() (+15 more)

### Community 9 - "Flask"
Cohesion: 0.13
Nodes (15): Config, create_app(), _is_insecure_secret(), _validate_production_config(), Register WebSocket events with the given SocketIO instance. Provides vendor-…, register_socketio_events(), Flask, enforce_cafe_payment_policy() (+7 more)

### Community 10 - "cancel_bookings_with_refund"
Cohesion: 0.14
Nodes (18): _append_cancellation_note(), _booking_slot_start_datetime_ist(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), cancel_bookings_with_refund(), _credit_wallet_for_cancellation(), _default_repayment_type() (+10 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 12 - "BookingService"
Cohesion: 0.12
Nodes (8): get_user_bookings(), Reject a direct booking and handle slot release & repayment., reject_booking(), HashWalletTransaction, PaymentTransactionMapping, BookingService, Updates the booking status in the vendor dashboard table for a given…, Return the best valid pass or None.

### Community 13 - "pass_controller.py"
Cohesion: 0.15
Nodes (22): _cleanup_pass_otp_cache(), _consume_pass_verification_token(), create_hour_pass(), _find_live_otp_session(), get_available_passes_for_purchase(), get_pass_history(), _hash_otp(), _mask_email() (+14 more)

### Community 14 - "pass_service.py"
Cohesion: 0.19
Nodes (4): AvailableGame, PassRedemptionLog, PassType, Vendor

### Community 15 - "reject_pay_at_cafe_booking"
Cohesion: 0.15
Nodes (13): _json_text_equals(), now_utc(), _parse_json_details(), Dialect-safe JSON text comparison (SQLAlchemy 2.0 removed .astext)., Resolve pay-at-cafe squad bookings by batch_id with a safe fallback that avoids…, Releases bookings stuck in 'pending_verified' that are older than 2 minutes.…, Reject a pay-at-cafe booking and change status to cancelled, reject_pay_at_cafe_booking() (+5 more)

### Community 17 - "PassService"
Cohesion: 0.14
Nodes (10): get_dashboard_user_valid_passes(), get_user_active_passes(), Dashboard helper: Return valid hour-based passes for a selected user at a…, Get all active passes for authenticated user., Decimal, CafePass, Validate pass configuration, PassService (+2 more)

### Community 19 - ".redeem_pass_hours"
Cohesion: 0.16
Nodes (11): cancel_redemption(), Redeem pass from dashboard (vendor scans pass). Staff ID removed - vendor scans…, Redeem pass during app booking flow. Called during booking confirmation., Cancel a redemption and restore hours., redeem_pass_app(), redeem_pass_dashboard(), date, Deduct hours from pass and create redemption log. Args: user_pass_id: UserPass… (+3 more)

### Community 20 - "auth_required_self"
Cohesion: 0.11
Nodes (21): capture_payment(), create_order(), generate_payment_link(), Creates a Razorpay Payment Link and returns the URL. Expects JSON: { "amount":…, redeem_voucher(), cafe_checkout_token(), digest(), issue_token() (+13 more)

### Community 21 - "create_booking"
Cohesion: 0.19
Nodes (13): _build_pay_at_cafe_email_action_url(), create_booking(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url() (+5 more)

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

### Community 26 - "UserPass"
Cohesion: 0.28
Nodes (5): purchase_pass(), User purchases a pass after Razorpay payment. Creates UserPass record with…, Generate unique pass UID for hour-based passes, UserPass, Create hour-based user pass after purchase. Args: user_id: User ID…

### Community 29 - "trigger_once"
Cohesion: 0.53
Nodes (5): build_headers(), http_post_with_retries(), main(), Call the scanner endpoint once and log the outcome., trigger_once()

### Community 30 - "main_loop"
Cohesion: 0.50
Nodes (4): main_loop(), Find unverified bookings older than 2 minutes from transactions in the last 1…, Run every 30 seconds for 30 days., release_unverified_slots()

### Community 31 - "vendor_console_overrides"
Cohesion: 0.67
Nodes (3): console_catalog, vendors, vendor_console_overrides

### Community 49 - "_load_vendor_booking_field_config"
Cohesion: 0.60
Nodes (5): _ensure_vendor_booking_field_preferences_table(), _load_vendor_booking_field_config(), _normalize_vendor_booking_field_config(), _save_vendor_booking_field_config(), vendor_booking_field_config()

### Community 50 - "_invalidate_pay_at_cafe_vendor_cache"
Cohesion: 0.29
Nodes (7): _ensure_vendor_pay_at_cafe_settings_table(), get_pay_at_cafe_settings(), _get_vendor_pay_at_cafe_settings(), _invalidate_pay_at_cafe_vendor_cache(), _read_cache_invalidate_prefix(), _save_vendor_pay_at_cafe_settings(), update_pay_at_cafe_settings()

## Knowledge Gaps
- **33 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Slot` connect `slot_controller.py` to `booking_controller.py`, `extensions.py`, `BookingService`, `pass_controller.py`, `pass_service.py`, `PassService`, `credit_unused_slots_to_wallet`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Why does `BookingService` connect `BookingService` to `new_booking`, `booking_controller.py`, `game_controller.py`, `extensions.py`, `slot_controller.py`, `cancel_bookings_with_refund`, `pass_service.py`, `reject_pay_at_cafe_booking`, `PassService`, `create_booking`, `UserPass`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `auth_required_self()` connect `auth_required_self` to `new_booking`, `booking_controller.py`, `cancel_bookings_with_refund`, `BookingService`, `pass_controller.py`, `PassService`, `.redeem_pass_hours`, `create_booking`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _33 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `new_booking` be split into smaller, more focused modules?**
  _Cohesion score 0.06481481481481481 - nodes in this community are weakly interconnected._
- **Should `booking_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0928030303030303 - nodes in this community are weakly interconnected._