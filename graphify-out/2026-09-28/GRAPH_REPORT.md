# Graph Report - hfg-booking  (2026-09-28)

## Corpus Check
- 85 files · ~57,304 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 663 nodes · 1544 edges · 48 communities (38 shown, 10 thin omitted)
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
- kiosk_book_next_slot
- booking_service.py
- HFG Booking Service
- mail_service.py
- slot_controller.py
- route
- Flask
- date
- gaming_type_controller.py
- BookingBatchWritesTests
- pass_controller.py
- extensions.py
- BookingMailTests
- ReleaseTests
- CafePass
- new_booking
- PassService
- auth_required_self
- create_booking
- get_effective_price_for_schedule
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
- `BookingService` --uses--> `AvailableGame`  [INFERRED]
  services/booking_service.py → models/availableGame.py
- `BookingService` --uses--> `Booking`  [INFERRED]
  services/booking_service.py → models/booking.py
- `BookingService` --uses--> `BookingExtraService`  [INFERRED]
  services/booking_service.py → models/bookingExtraService.py
- `BookingService` --uses--> `CafePass`  [INFERRED]
  services/booking_service.py → models/passModels.py
- `PassService` --uses--> `CafePass`  [INFERRED]
  services/pass_service.py → models/passModels.py

## Import Cycles
- None detected.

## Communities (48 total, 10 thin omitted)

### Community 0 - "booking_pricing_estimate"
Cohesion: 0.15
Nodes (30): booking_pricing_estimate(), booking_pricing_preview(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), _compute_pay_at_cafe_pricing(), _default_squad_policy_for_max_players(), get_effective_price(), get_pending_pay_at_cafe_bookings() (+22 more)

### Community 1 - "booking_controller.py"
Cohesion: 0.08
Nodes (33): _build_squad_member_bindings(), _collect_vendor_user_ids(), _ensure_vendor_booking_field_preferences_table(), _ensure_vendor_pay_at_cafe_settings_table(), get_pay_at_cafe_settings(), get_user_details(), _get_vendor_pay_at_cafe_settings(), _load_vendor_booking_field_config() (+25 more)

### Community 2 - "game_controller.py"
Cohesion: 0.14
Nodes (30): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+22 more)

### Community 3 - "kiosk_book_next_slot"
Cohesion: 0.10
Nodes (34): BlockLike, _coerce_int_value(), direct_booking(), _ensure_vendor_slot_rows_for_date(), _ist_now_naive(), kiosk_book_next_slot(), kiosk_check_next_slot(), _precheck_slot_booking_eligibility() (+26 more)

### Community 4 - "booking_service.py"
Cohesion: 0.10
Nodes (11): _credit_wallet_for_cancellation(), ExtraServiceMenu, ExtraServiceMenuImage, HashWallet, HashWalletTransaction, PaymentTransactionMapping, Transaction, User (+3 more)

### Community 5 - "HFG Booking Service"
Cohesion: 0.05
Nodes (40): Client changes, Different errors need different UI handling, Mobile checkout: cafe context required, POST /api/capture_payment, POST /api/create_order, POST /api/generate_payment_link (if used), Validation completed, Why the payment screen fails (+32 more)

### Community 6 - "mail_service.py"
Cohesion: 0.16
Nodes (18): Reject a direct booking and handle slot release & repayment., reject_booking(), HTMLParser, Updates the booking status in the vendor dashboard table for a given…, build_hfg_email_html(), email_text(), _EmailText, _extract_body() (+10 more)

### Community 7 - "slot_controller.py"
Cohesion: 0.06
Nodes (32): _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots(), get_slots_batch(), get_slots_on_game_id() (+24 more)

### Community 8 - "route"
Cohesion: 0.11
Nodes (20): booking_payment_summary(), create_render_one_off_job(), get_booking_details(), get_console_status(), get_time_wallet(), get_vendor_bookings(), monthly_credit_accounts(), monthly_credit_eligibility() (+12 more)

### Community 9 - "Flask"
Cohesion: 0.13
Nodes (15): Config, create_app(), _is_insecure_secret(), _validate_production_config(), Register WebSocket events with the given SocketIO instance. Provides vendor-…, register_socketio_events(), Flask, enforce_cafe_payment_policy() (+7 more)

### Community 10 - "date"
Cohesion: 0.06
Nodes (47): accept_pay_at_cafe_booking(), _append_cancellation_note(), _booking_slot_start_datetime_ist(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), cancel_bookings_with_refund(), _coerce_date_value() (+39 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 13 - "pass_controller.py"
Cohesion: 0.12
Nodes (28): cancel_redemption(), _cleanup_pass_otp_cache(), _consume_pass_verification_token(), _find_live_otp_session(), get_available_passes_for_purchase(), get_dashboard_user_valid_passes(), get_pass_history(), get_user_active_passes() (+20 more)

### Community 14 - "extensions.py"
Cohesion: 0.17
Nodes (6): configure_socketio(), Configures SocketIO with the Flask app., HashCoinTransaction, PassRedemptionLog, PassType, Vendor

### Community 18 - "new_booking"
Cohesion: 0.10
Nodes (34): add_meals_to_booking(), calculate_gst_breakdown(), compute_booking_financial_summary(), compute_credit_due_date(), confirm_booking(), _consume_menu_stock(), _ensure_menu_stock_available(), extra_booking() (+26 more)

### Community 19 - "PassService"
Cohesion: 0.17
Nodes (11): Redeem pass during app booking flow. Called during booking confirmation., redeem_pass_app(), Decimal, PassService, date, Deduct hours from pass and create redemption log. Args: user_pass_id: UserPass…, Calculate hours for a slot based on pass configuration. Args: slot_id: Slot ID…, Cancel a redemption and restore hours to pass. Args: redemption_id:… (+3 more)

### Community 20 - "auth_required_self"
Cohesion: 0.09
Nodes (22): capture_payment(), create_order(), generate_payment_link(), get_user_bookings(), Creates a Razorpay Payment Link and returns the URL. Expects JSON: { "amount":…, redeem_voucher(), cafe_checkout_token(), digest() (+14 more)

### Community 21 - "create_booking"
Cohesion: 0.23
Nodes (12): _build_pay_at_cafe_email_action_url(), create_booking(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url() (+4 more)

### Community 22 - "get_effective_price_for_schedule"
Cohesion: 0.22
Nodes (9): calculate_slot_minutes(), credit_unused_slots_to_wallet(), get_effective_price_for_schedule(), _log_pricing_event(), _pricing_log_enabled(), Credit unused booked slots to user's time wallet. Body: { "user_id": 1,…, Returns offered price for the selected booking date/slot window if an active…, TimeWalletAccount (+1 more)

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

### Community 29 - "trigger_once"
Cohesion: 0.53
Nodes (5): build_headers(), http_post_with_retries(), main(), Call the scanner endpoint once and log the outcome., trigger_once()

### Community 30 - "main_loop"
Cohesion: 0.50
Nodes (4): main_loop(), Find unverified bookings older than 2 minutes from transactions in the last 1…, Run every 30 seconds for 30 days., release_unverified_slots()

### Community 31 - "vendor_console_overrides"
Cohesion: 0.67
Nodes (3): console_catalog, vendors, vendor_console_overrides

## Knowledge Gaps
- **39 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BookingService` connect `booking_service.py` to `booking_controller.py`, `game_controller.py`, `kiosk_book_next_slot`, `mail_service.py`, `slot_controller.py`, `date`, `CafePass`, `new_booking`, `auth_required_self`, `UserPass`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `Slot` connect `slot_controller.py` to `booking_controller.py`, `booking_service.py`, `pass_controller.py`, `extensions.py`, `PassService`, `get_effective_price_for_schedule`?**
  _High betweenness centrality (0.038) - this node is a cross-community bridge._
- **Why does `auth_required_self()` connect `auth_required_self` to `booking_controller.py`, `date`, `pass_controller.py`, `new_booking`, `PassService`, `create_booking`, `UserPass`?**
  _High betweenness centrality (0.021) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 13 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `booking_pricing_estimate` be split into smaller, more focused modules?**
  _Cohesion score 0.1471264367816092 - nodes in this community are weakly interconnected._
- **Should `booking_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07536231884057971 - nodes in this community are weakly interconnected._