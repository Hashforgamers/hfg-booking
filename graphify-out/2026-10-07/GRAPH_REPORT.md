# Graph Report - hfg-booking  (2026-10-07)

## Corpus Check
- 103 files · ~62,505 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 768 nodes · 1841 edges · 65 communities (55 shown, 10 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 79 edges (avg confidence: 0.67)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `9158ec3d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- UpcomingSlotTests
- booking_controller.py
- game_controller.py
- confirm_booking
- booking_service.py
- HFG Booking Service
- mail_service.py
- get_slots_on_game_id
- route
- Flask
- date
- gaming_type_controller.py
- BookingBatchWritesTests
- pass_controller.py
- extra_booking
- DeferredBookingRealtime
- ReleaseTests
- Booking
- new_booking
- accept_pay_at_cafe_booking
- test_payment_integrity.py
- create_booking
- slot_controller.py
- App Booking Cancellation API
- ConsolePricingOffer
- test_slot_cache.py
- extensions.py
- cancel_bookings_with_refund
- trigger_once
- main_loop
- vendor_console_overrides
- vendor_booking_field_preferences
- AGENTS.md
- jobs/__init__.py
- 20260817_booking_gateway_payment_reconciliation.sql
- extra_service_menus
- transactions
- API Endpoints
- CafePass
- search_booked_customers
- Transaction
- Cafe payment methods: app handoff and rollout
- Mobile checkout: cafe context required
- Game Controller
- PassOtpStore
- auth_required_self
- Client changes
- Slot Controller
- credit_unused_slots_to_wallet
- kiosk_check_next_slot

## God Nodes (most connected - your core abstractions)
1. `new_booking()` - 59 edges
2. `confirm_booking()` - 36 edges
3. `BookingService` - 33 edges
4. `accept_pay_at_cafe_booking()` - 22 edges
5. `require_vendor_permission()` - 22 edges
6. `Transaction` - 21 edges
7. `auth_required_self()` - 21 edges
8. `extra_booking()` - 20 edges
9. `Slot` - 19 edges
10. `Booking` - 18 edges

## Surprising Connections (you probably didn't know these)
- `BookingService` --uses--> `AvailableGame`  [INFERRED]
  services/booking_service.py → models/availableGame.py
- `BookingService` --uses--> `Booking`  [INFERRED]
  services/booking_service.py → models/booking.py
- `BookingService` --uses--> `CafePass`  [INFERRED]
  services/booking_service.py → models/passModels.py
- `PurchaseError` --uses--> `CafePass`  [INFERRED]
  services/pass_purchase_service.py → models/passModels.py
- `PassService` --uses--> `CafePass`  [INFERRED]
  services/pass_service.py → models/passModels.py

## Import Cycles
- None detected.

## Communities (65 total, 10 thin omitted)

### Community 1 - "booking_controller.py"
Cohesion: 0.10
Nodes (25): _build_squad_member_bindings(), _collect_vendor_user_ids(), _ensure_vendor_booking_field_preferences_table(), _ensure_vendor_pay_at_cafe_settings_table(), get_pay_at_cafe_settings(), get_user_details(), _get_vendor_pay_at_cafe_settings(), _load_vendor_booking_field_config() (+17 more)

### Community 2 - "game_controller.py"
Cohesion: 0.13
Nodes (31): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+23 more)

### Community 3 - "confirm_booking"
Cohesion: 0.12
Nodes (27): BlockLike, confirm_booking(), direct_booking(), kiosk_book_next_slot(), _log_pricing_event(), _pricing_log_enabled(), Books the immediate next slot for kiosk continuation. - Charges are recorded as…, Resolve app fee (platform fee) for transparency. App fee must be applied only… (+19 more)

### Community 4 - "booking_service.py"
Cohesion: 0.11
Nodes (9): BookingExtraService, ExtraServiceMenu, ExtraServiceMenuImage, HashWallet, HashWalletTransaction, PaymentTransactionMapping, BookingService, Updates the booking status in the vendor dashboard table for a given… (+1 more)

### Community 5 - "HFG Booking Service"
Cohesion: 0.17
Nodes (12): Booking (`models/booking.py`), BookingService (`services/booking_service.py`), Core Services, HFG Booking Service, Key Features, Models, Overview, Setup (+4 more)

### Community 6 - "mail_service.py"
Cohesion: 0.20
Nodes (15): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., booking_mail(), extra_booking_time_mail() (+7 more)

### Community 7 - "get_slots_on_game_id"
Cohesion: 0.15
Nodes (19): _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots(), get_slots_batch(), get_slots_on_game_id() (+11 more)

### Community 8 - "route"
Cohesion: 0.12
Nodes (20): create_render_one_off_job(), get_booking_details(), get_console_status(), get_time_wallet(), get_vendor_booking_stats(), get_vendor_bookings(), manage_upcoming_slot(), monthly_credit_eligibility() (+12 more)

### Community 9 - "Flask"
Cohesion: 0.10
Nodes (22): Config, create_app(), _is_insecure_secret(), _validate_production_config(), create_order(), Register WebSocket events with the given SocketIO instance. Provides vendor-…, register_socketio_events(), Flask (+14 more)

### Community 10 - "date"
Cohesion: 0.16
Nodes (18): _coerce_date_value(), _ensure_pay_at_cafe_action_logs_table(), _fetch_pay_at_cafe_queue_id_sets(), get_all_booking(), get_pay_at_cafe_queue_list(), get_pay_at_cafe_queue_summary(), get_pending_pay_at_cafe_bookings(), get_slot_bookings() (+10 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 13 - "pass_controller.py"
Cohesion: 0.16
Nodes (19): _cleanup_pass_otp_cache(), _consume_pass_verification_token(), _find_live_otp_session(), get_available_passes_for_purchase(), _hash_otp(), _mask_email(), _otp_secret(), _passes_cache_get() (+11 more)

### Community 14 - "extra_booking"
Cohesion: 0.12
Nodes (22): add_meals_to_booking(), booking_payment_summary(), calculate_gst_breakdown(), compute_booking_financial_summary(), extra_booking(), monthly_credit_accounts(), normalize_payment_use_case(), Settle monthly credit outstanding at month-end. Body: { "user_id": 1, "amount":… (+14 more)

### Community 15 - "DeferredBookingRealtime"
Cohesion: 0.18
Nodes (6): patch, DeferredBookingRealtime, Keep best-effort realtime delivery outside committed booking responses., BookingMailTests, Test the production background mail helper without booting network services., BookingRealtimeTests

### Community 17 - "Booking"
Cohesion: 0.11
Nodes (17): get_dashboard_user_valid_passes(), Dashboard helper: Return valid hour-based passes for a selected user at a…, Decimal, fixture, AvailableGame, Booking, Updated to include private booking fields, PassRedemptionLog (+9 more)

### Community 18 - "new_booking"
Cohesion: 0.06
Nodes (61): booking_pricing_estimate(), booking_pricing_preview(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), _compute_pay_at_cafe_pricing(), _consume_menu_stock(), _default_squad_policy_for_max_players(), _ensure_menu_stock_available() (+53 more)

### Community 19 - "accept_pay_at_cafe_booking"
Cohesion: 0.13
Nodes (19): accept_pay_at_cafe_booking(), _invalidate_pay_at_cafe_vendor_cache(), _json_text_equals(), _log_pay_at_cafe_action(), now_utc(), _parse_json_details(), Dialect-safe JSON text comparison (SQLAlchemy 2.0 removed .astext)., Resolve pay-at-cafe squad bookings by batch_id with a safe fallback that avoids… (+11 more)

### Community 20 - "test_payment_integrity.py"
Cohesion: 0.20
Nodes (13): parametrize, body(), Payment invariants against real ORM code in isolated PostgreSQL schemas.…, test_disabled_cafe_pass_purchase_does_not_debit(), test_failed_booking_rolls_back_pass_and_verification_consumption(), test_gateway_owner_pass_binding_and_cross_checkout_replay(), test_gateway_requires_exact_captured_inr_payment(), test_gateway_success_and_replay() (+5 more)

### Community 21 - "create_booking"
Cohesion: 0.22
Nodes (13): _build_pay_at_cafe_email_action_url(), create_booking(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url() (+5 more)

### Community 22 - "slot_controller.py"
Cohesion: 0.12
Nodes (8): Return positive duration in minutes for HH:MM:SS times, handling overnight edge., Register WebSocket events with the given SocketIO instance., register_socketio_events(), _slot_duration_minutes(), Return a dictionary representation of the Slot object., Return a dictionary representation of the Slot object., Slot, SlotService

### Community 23 - "App Booking Cancellation API"
Cohesion: 0.20
Nodes (9): App Booking Cancellation API, Cancellation fee envs, Endpoint, Failure responses, Real-time socket events emitted, Request, Request fields, Strategy implemented (+1 more)

### Community 24 - "ConsolePricingOffer"
Cohesion: 0.24
Nodes (5): ConsolePricingOffer, Time-based promotional pricing for console types (AvailableGames) Allows…, Check if this offer is active RIGHT NOW using IST. Returns True if current IST…, Calculate discount percentage, Convert to dictionary for API responses

### Community 25 - "test_slot_cache.py"
Cohesion: 0.47
Nodes (3): load(), Exercise actual slot readers with a warm cache and mocked database boundary., SlotCacheTests

### Community 26 - "extensions.py"
Cohesion: 0.20
Nodes (5): configure_socketio(), Configures SocketIO with the Flask app., AccessBookingCode, BookingSquadMember, HashCoinTransaction

### Community 28 - "cancel_bookings_with_refund"
Cohesion: 0.19
Nodes (15): _append_cancellation_note(), _booking_slot_start_datetime_ist(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), cancel_bookings_with_refund(), _credit_wallet_for_cancellation(), _default_repayment_type() (+7 more)

### Community 29 - "trigger_once"
Cohesion: 0.53
Nodes (5): build_headers(), http_post_with_retries(), main(), Call the scanner endpoint once and log the outcome., trigger_once()

### Community 30 - "main_loop"
Cohesion: 0.50
Nodes (4): main_loop(), Find unverified bookings older than 2 minutes from transactions in the last 1…, Run every 30 seconds for 30 days., release_unverified_slots()

### Community 31 - "vendor_console_overrides"
Cohesion: 0.67
Nodes (3): console_catalog, vendors, vendor_console_overrides

### Community 49 - "API Endpoints"
Cohesion: 0.22
Nodes (9): API Endpoints, Booking Controller, DELETE /gaming-types/<int:gaming_type_id>, Gaming Type Controller, GET /bookings/<booking_id>, GET /gaming-types, POST /bookings, POST /create_order (+1 more)

### Community 52 - "search_booked_customers"
Cohesion: 0.33
Nodes (3): Bounded customer lookup across a cafe's complete booking history., search_booked_customers(), CustomerSearchTests

### Community 53 - "Transaction"
Cohesion: 0.16
Nodes (11): BookingGatewayPayment, One consumed Razorpay payment for one booking-confirmation batch., Generate unique pass UID for hour-based passes, UserPass, PassPurchase, Transaction, User, purchase() (+3 more)

### Community 54 - "Cafe payment methods: app handoff and rollout"
Cohesion: 0.25
Nodes (8): Acceptance rule, Booking payment, Cafe payment methods: app handoff and rollout, Cafe wallet and the unified QR, Dashboard flow and refunds, Deploy in this order, Discover enabled methods, Pass purchase

### Community 55 - "Mobile checkout: cafe context required"
Cohesion: 0.29
Nodes (4): Different errors need different UI handling, Mobile checkout: cafe context required, Validation completed, Why the payment screen fails

### Community 56 - "Game Controller"
Cohesion: 0.29
Nodes (7): DELETE /bookings/<int:booking_id>, Game Controller, GET /bookings/user/<int:user_id>, GET /games, GET /games/vendor/<int:vendor_id>, GET /getAllConsole/vendor/<int:vendor_id>, POST /bookings

### Community 57 - "PassOtpStore"
Cohesion: 0.31
Nodes (3): PassOtpState, PassOtpStore, Database-backed OTP state shared by all booking workers. Writes participate in…

### Community 58 - "auth_required_self"
Cohesion: 0.08
Nodes (30): capture_payment(), generate_payment_link(), Creates a Razorpay Payment Link and returns the URL. Expects JSON: { "amount":…, redeem_voucher(), cafe_checkout_token(), digest(), issue_token(), Short-lived gamer checkout identity, using existing Hash auth or email OTP. (+22 more)

### Community 59 - "Client changes"
Cohesion: 0.50
Nodes (4): Client changes, POST /api/capture_payment, POST /api/create_order, POST /api/generate_payment_link (if used)

### Community 60 - "Slot Controller"
Cohesion: 0.50
Nodes (4): GET /getSlotList/vendor/<int:vendor_id>/game/<int:game_id>, GET /getSlots/vendor/<int:vendorId>/game/<int:gameId>/<string:date>, GET /slots, Slot Controller

### Community 64 - "credit_unused_slots_to_wallet"
Cohesion: 0.40
Nodes (5): calculate_slot_minutes(), credit_unused_slots_to_wallet(), Credit unused booked slots to user's time wallet. Body: { "user_id": 1,…, TimeWalletAccount, TimeWalletLedger

### Community 65 - "kiosk_check_next_slot"
Cohesion: 0.15
Nodes (15): _coerce_int_value(), compute_credit_due_date(), _ensure_vendor_slot_rows_for_date(), _ist_now_naive(), kiosk_check_next_slot(), _precheck_slot_booking_eligibility(), datetime, Self-heal missing VENDOR_<id>_SLOT rows for selected date/slots so direct… (+7 more)

## Knowledge Gaps
- **46 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+41 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeferredBookingRealtime` connect `DeferredBookingRealtime` to `booking_controller.py`, `new_booking`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `Slot` connect `slot_controller.py` to `credit_unused_slots_to_wallet`, `booking_controller.py`, `booking_service.py`, `get_slots_on_game_id`, `pass_controller.py`, `Booking`, `extensions.py`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `BookingService` connect `booking_service.py` to `booking_controller.py`, `game_controller.py`, `date`, `extra_booking`, `Booking`, `new_booking`, `CafePass`, `accept_pay_at_cafe_booking`, `Transaction`, `slot_controller.py`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `ValueError` (e.g. with `calculate_extra_controller_fare()` and `cancel_bookings_with_refund()`) actually correct?**
  _`ValueError` has 31 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _46 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `booking_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10420168067226891 - nodes in this community are weakly interconnected._