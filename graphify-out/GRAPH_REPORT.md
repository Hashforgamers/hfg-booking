# Graph Report - hfg-booking  (2026-09-28)

## Corpus Check
- 88 files · ~57,548 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 673 nodes · 1558 edges · 51 communities (42 shown, 9 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 25 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `420d9332`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- booking_pricing_estimate
- booking_controller.py
- game_controller.py
- realtime.py
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
- BookingMailTests
- ReleaseTests
- get_user_details
- new_booking
- PassService
- Voucher
- create_booking
- credit_unused_slots_to_wallet
- App Booking Cancellation API
- ConsolePricingOffer
- test_slot_cache.py
- UserPass
- route
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

## God Nodes (most connected - your core abstractions)
1. `new_booking()` - 50 edges
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
- `BookingService` --uses--> `BookingExtraService`  [INFERRED]
  services/booking_service.py → models/bookingExtraService.py
- `BookingService` --uses--> `CafePass`  [INFERRED]
  services/booking_service.py → models/passModels.py
- `BookingService` --uses--> `UserPass`  [INFERRED]
  services/booking_service.py → models/passModels.py
- `PassService` --uses--> `UserPass`  [INFERRED]
  services/pass_service.py → models/passModels.py
- `PassService` --uses--> `PassRedemptionLog`  [INFERRED]
  services/pass_service.py → models/passModels.py

## Import Cycles
- None detected.

## Communities (51 total, 9 thin omitted)

### Community 0 - "booking_pricing_estimate"
Cohesion: 0.18
Nodes (26): booking_pricing_estimate(), booking_pricing_preview(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), _compute_pay_at_cafe_pricing(), _default_squad_policy_for_max_players(), get_effective_price(), get_squad_pricing_policy() (+18 more)

### Community 1 - "booking_controller.py"
Cohesion: 0.08
Nodes (26): _append_cancellation_note(), _ensure_vendor_pay_at_cafe_settings_table(), get_pay_at_cafe_settings(), _get_vendor_pay_at_cafe_settings(), _invalidate_pay_at_cafe_vendor_cache(), monthly_credit_accounts(), monthly_credit_eligibility(), monthly_credit_statement() (+18 more)

### Community 2 - "game_controller.py"
Cohesion: 0.14
Nodes (30): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+22 more)

### Community 3 - "realtime.py"
Cohesion: 0.29
Nodes (10): BlockLike, TimeLike, _as_date_str(), _canonical_payload(), _coalesce(), _derive_status_label(), _fmt_time(), _normalize_block() (+2 more)

### Community 4 - "booking_service.py"
Cohesion: 0.05
Nodes (19): AccessBookingCode, AvailableGame, Booking, Updated to include private booking fields, BookingSquadMember, ExtraServiceMenu, ExtraServiceMenuImage, HashWallet (+11 more)

### Community 5 - "HFG Booking Service"
Cohesion: 0.05
Nodes (40): Client changes, Different errors need different UI handling, Mobile checkout: cafe context required, POST /api/capture_payment, POST /api/create_order, POST /api/generate_payment_link (if used), Validation completed, Why the payment screen fails (+32 more)

### Community 6 - "mail_service.py"
Cohesion: 0.20
Nodes (15): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., booking_mail(), extra_booking_time_mail() (+7 more)

### Community 7 - "slot_controller.py"
Cohesion: 0.13
Nodes (23): _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots(), get_slots_batch(), get_slots_on_game_id() (+15 more)

### Community 8 - "route"
Cohesion: 0.08
Nodes (28): booking_payment_summary(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), capture_payment(), create_order(), create_render_one_off_job(), generate_payment_link() (+20 more)

### Community 9 - "Flask"
Cohesion: 0.08
Nodes (28): Config, create_app(), _is_insecure_secret(), _validate_production_config(), cafe_checkout_token(), digest(), issue_token(), Short-lived gamer checkout identity, using existing Hash auth or email OTP. (+20 more)

### Community 10 - "get_pending_pay_at_cafe_bookings"
Cohesion: 0.15
Nodes (17): _ensure_pay_at_cafe_action_logs_table(), _fetch_pay_at_cafe_queue_id_sets(), get_pay_at_cafe_queue_summary(), get_pending_pay_at_cafe_bookings(), get_user_bookings(), _json_text_equals(), _log_pay_at_cafe_action(), _parse_json_details() (+9 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 13 - "pass_controller.py"
Cohesion: 0.22
Nodes (15): _cleanup_pass_otp_cache(), _consume_pass_verification_token(), _find_live_otp_session(), get_available_passes_for_purchase(), _hash_otp(), _mask_email(), _otp_secret(), _passes_cache_get() (+7 more)

### Community 14 - "extensions.py"
Cohesion: 0.14
Nodes (8): configure_socketio(), Configures SocketIO with the Flask app., BookingGatewayPayment, One consumed Razorpay payment for one booking-confirmation batch., HashCoinTransaction, PassRedemptionLog, PassType, Vendor

### Community 17 - "get_user_details"
Cohesion: 0.10
Nodes (17): _build_squad_member_bindings(), _collect_vendor_user_ids(), _ensure_vendor_booking_field_preferences_table(), get_user_details(), _load_vendor_booking_field_config(), _normalize_vendor_booking_field_config(), _resolve_or_create_squad_member_user(), _save_vendor_booking_field_config() (+9 more)

### Community 18 - "new_booking"
Cohesion: 0.05
Nodes (83): accept_pay_at_cafe_booking(), add_meals_to_booking(), _booking_slot_start_datetime_ist(), calculate_gst_breakdown(), cancel_bookings_with_refund(), _coerce_date_value(), _coerce_int_value(), compute_booking_financial_summary() (+75 more)

### Community 19 - "PassService"
Cohesion: 0.14
Nodes (12): Redeem pass during app booking flow. Called during booking confirmation., redeem_pass_app(), Decimal, CafePass, Validate pass configuration, PassService, date, Deduct hours from pass and create redemption log. Args: user_pass_id: UserPass… (+4 more)

### Community 20 - "Voucher"
Cohesion: 0.47
Nodes (3): redeem_voucher(), Voucher, create_referral_voucher()

### Community 21 - "create_booking"
Cohesion: 0.23
Nodes (12): _build_pay_at_cafe_email_action_url(), create_booking(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url() (+4 more)

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
Cohesion: 0.22
Nodes (7): create_hour_pass(), purchase_pass(), Create hour-based pass after purchase (called after payment confirmation)., User purchases a pass after Razorpay payment. Creates UserPass record with…, Generate unique pass UID for hour-based passes, UserPass, Create hour-based user pass after purchase. Args: user_id: User ID…

### Community 28 - "route"
Cohesion: 0.14
Nodes (14): cancel_redemption(), get_dashboard_user_valid_passes(), get_pass_history(), get_user_active_passes(), route, Validate pass UID and return pass details. Used by dashboard before redemption., Dashboard helper: Return valid hour-based passes for a selected user at a…, Redeem pass from dashboard (vendor scans pass). Staff ID removed - vendor scans… (+6 more)

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

## Knowledge Gaps
- **39 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BookingService` connect `booking_service.py` to `booking_controller.py`, `game_controller.py`, `get_user_details`, `new_booking`, `PassService`, `release_slot_controller`, `UserPass`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `Slot` connect `booking_service.py` to `booking_controller.py`, `slot_controller.py`, `pass_controller.py`, `extensions.py`, `PassService`, `credit_unused_slots_to_wallet`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `auth_required_self()` connect `route` to `booking_controller.py`, `Flask`, `get_pending_pay_at_cafe_bookings`, `pass_controller.py`, `new_booking`, `PassService`, `Voucher`, `create_booking`, `UserPass`, `route`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `booking_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08258258258258258 - nodes in this community are weakly interconnected._
- **Should `game_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.13630229419703105 - nodes in this community are weakly interconnected._