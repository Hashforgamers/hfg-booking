# Graph Report - hfg-booking  (2026-10-31)

## Corpus Check
- 108 files · ~64,159 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 803 nodes · 1894 edges · 66 communities (58 shown, 8 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 84 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4b575919`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- extensions.py
- booking_controller.py
- game_controller.py
- kiosk_book_next_slot
- BookingService
- HFG Booking Service
- mail_service.py
- slot_controller.py
- ValueError
- Flask
- confirm_booking
- gaming_type_controller.py
- BookingBatchWritesTests
- pass_controller.py
- new_booking
- DeferredBookingRealtime
- ReleaseTests
- PassService
- _compute_pay_at_cafe_pricing
- accept_pay_at_cafe_booking
- test_payment_integrity.py
- pay_at_cafe_email_action
- Slot
- App Booking Cancellation API
- ConsolePricingOffer
- test_slot_cache.py
- Booking
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
- API Endpoints
- move_slot
- search_booked_customers
- Transaction
- Cafe payment methods: app handoff and rollout
- Mobile checkout: cafe context required
- Game Controller
- UserPass
- _ensure_menu_stock_available
- Client changes
- Slot Controller
- Voucher
- Hash app team integration prompt
- test_operating_hours_availability.py

## God Nodes (most connected - your core abstractions)
1. `new_booking()` - 59 edges
2. `confirm_booking()` - 37 edges
3. `BookingService` - 33 edges
4. `accept_pay_at_cafe_booking()` - 22 edges
5. `require_vendor_permission()` - 22 edges
6. `Transaction` - 21 edges
7. `auth_required_self()` - 21 edges
8. `extra_booking()` - 20 edges
9. `Slot` - 19 edges
10. `cancel_bookings_with_refund()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `BookingService` --uses--> `AvailableGame`  [INFERRED]
  services/booking_service.py → models/availableGame.py
- `BookingService` --uses--> `Booking`  [INFERRED]
  services/booking_service.py → models/booking.py
- `PassService` --uses--> `Booking`  [INFERRED]
  services/pass_service.py → models/booking.py
- `env()` --calls--> `Booking`  [INFERRED]
  tests/test_payment_integrity.py → models/booking.py
- `BookingService` --uses--> `BookingExtraService`  [INFERRED]
  services/booking_service.py → models/bookingExtraService.py

## Import Cycles
- None detected.

## Communities (66 total, 8 thin omitted)

### Community 0 - "extensions.py"
Cohesion: 0.18
Nodes (6): configure_socketio(), Configures SocketIO with the Flask app., ExtraServiceMenu, ExtraServiceMenuImage, HashCoinTransaction, HashWallet

### Community 1 - "booking_controller.py"
Cohesion: 0.08
Nodes (29): _build_squad_member_bindings(), calculate_slot_minutes(), _collect_vendor_user_ids(), credit_unused_slots_to_wallet(), _ensure_vendor_booking_field_preferences_table(), get_user_details(), _load_vendor_booking_field_config(), monthly_credit_accounts() (+21 more)

### Community 2 - "game_controller.py"
Cohesion: 0.14
Nodes (30): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+22 more)

### Community 3 - "kiosk_book_next_slot"
Cohesion: 0.11
Nodes (31): BlockLike, _coerce_int_value(), direct_booking(), _ist_now_naive(), kiosk_book_next_slot(), kiosk_check_next_slot(), _log_pricing_event(), _pricing_log_enabled() (+23 more)

### Community 4 - "BookingService"
Cohesion: 0.13
Nodes (6): get_user_bookings(), PaymentTransactionMapping, BookingService, Batch dashboard/promo writes in the caller's transaction using loaded data., Updates the booking status in the vendor dashboard table for a given…, Return the best valid pass or None.

### Community 5 - "HFG Booking Service"
Cohesion: 0.17
Nodes (12): Booking (`models/booking.py`), BookingService (`services/booking_service.py`), Core Services, HFG Booking Service, Key Features, Models, Overview, Setup (+4 more)

### Community 6 - "mail_service.py"
Cohesion: 0.20
Nodes (15): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., booking_mail(), extra_booking_time_mail() (+7 more)

### Community 7 - "slot_controller.py"
Cohesion: 0.12
Nodes (25): _ensure_vendor_slot_rows_for_date(), Self-heal missing VENDOR_<id>_SLOT rows for selected date/slots so direct…, _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots() (+17 more)

### Community 8 - "ValueError"
Cohesion: 0.07
Nodes (38): _append_cancellation_note(), _booking_slot_start_datetime_ist(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), cancel_bookings_with_refund(), _credit_wallet_for_cancellation(), _default_repayment_type() (+30 more)

### Community 9 - "Flask"
Cohesion: 0.07
Nodes (33): Config, create_app(), _is_insecure_secret(), _validate_production_config(), create_order(), cafe_checkout_token(), digest(), gamer_payment_methods() (+25 more)

### Community 10 - "confirm_booking"
Cohesion: 0.20
Nodes (17): _coerce_date_value(), confirm_booking(), _ensure_pay_at_cafe_action_logs_table(), _fetch_pay_at_cafe_queue_id_sets(), get_effective_price_for_schedule(), get_pay_at_cafe_queue_list(), get_pay_at_cafe_queue_summary(), get_pending_pay_at_cafe_bookings() (+9 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 13 - "pass_controller.py"
Cohesion: 0.06
Nodes (46): capture_payment(), cancel_redemption(), _cleanup_pass_otp_cache(), _consume_pass_verification_token(), _find_live_otp_session(), get_available_passes_for_purchase(), get_dashboard_user_valid_passes(), get_pass_history() (+38 more)

### Community 14 - "new_booking"
Cohesion: 0.09
Nodes (33): add_meals_to_booking(), booking_payment_summary(), calculate_gst_breakdown(), compute_booking_financial_summary(), compute_credit_due_date(), extra_booking(), _is_slot_live_now_ist(), new_booking() (+25 more)

### Community 15 - "DeferredBookingRealtime"
Cohesion: 0.18
Nodes (6): patch, DeferredBookingRealtime, Keep best-effort realtime delivery outside committed booking responses., BookingMailTests, Test the production background mail helper without booting network services., BookingRealtimeTests

### Community 17 - "PassService"
Cohesion: 0.12
Nodes (12): Decimal, AvailableGame, CafePass, PassRedemptionLog, PassType, Vendor, PassService, Deduct hours from pass and create redemption log. Args: user_pass_id: UserPass… (+4 more)

### Community 18 - "_compute_pay_at_cafe_pricing"
Cohesion: 0.18
Nodes (27): booking_pricing_estimate(), booking_pricing_preview(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), _compute_pay_at_cafe_pricing(), create_booking(), _default_squad_policy_for_max_players(), get_effective_price() (+19 more)

### Community 19 - "accept_pay_at_cafe_booking"
Cohesion: 0.11
Nodes (21): accept_pay_at_cafe_booking(), _invalidate_pay_at_cafe_vendor_cache(), _json_text_equals(), _log_pay_at_cafe_action(), now_utc(), _parse_json_details(), Dialect-safe JSON text comparison (SQLAlchemy 2.0 removed .astext)., Resolve pay-at-cafe squad bookings by batch_id with a safe fallback that avoids… (+13 more)

### Community 20 - "test_payment_integrity.py"
Cohesion: 0.20
Nodes (13): parametrize, body(), Payment invariants against real ORM code in isolated PostgreSQL schemas.…, test_disabled_cafe_pass_purchase_does_not_debit(), test_failed_booking_rolls_back_pass_and_verification_consumption(), test_gateway_owner_pass_binding_and_cross_checkout_replay(), test_gateway_requires_exact_captured_inr_payment(), test_gateway_success_and_replay() (+5 more)

### Community 21 - "pay_at_cafe_email_action"
Cohesion: 0.24
Nodes (11): _build_pay_at_cafe_email_action_url(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url(), _resolve_dashboard_public_url() (+3 more)

### Community 22 - "Slot"
Cohesion: 0.19
Nodes (4): Return a dictionary representation of the Slot object., Return a dictionary representation of the Slot object., Slot, SlotService

### Community 23 - "App Booking Cancellation API"
Cohesion: 0.20
Nodes (9): App Booking Cancellation API, Cancellation fee envs, Endpoint, Failure responses, Real-time socket events emitted, Request, Request fields, Strategy implemented (+1 more)

### Community 24 - "ConsolePricingOffer"
Cohesion: 0.24
Nodes (5): ConsolePricingOffer, Time-based promotional pricing for console types (AvailableGames) Allows…, Check if this offer is active RIGHT NOW using IST. Returns True if current IST…, Calculate discount percentage, Convert to dictionary for API responses

### Community 25 - "test_slot_cache.py"
Cohesion: 0.47
Nodes (3): load(), Exercise actual slot readers with a warm cache and mocked database boundary., SlotCacheTests

### Community 26 - "Booking"
Cohesion: 0.25
Nodes (4): AccessBookingCode, Booking, Updated to include private booking fields, BookingSquadMember

### Community 28 - "route"
Cohesion: 0.09
Nodes (23): create_render_one_off_job(), _ensure_vendor_pay_at_cafe_settings_table(), get_all_booking(), get_booking_details(), get_console_status(), get_pay_at_cafe_settings(), get_slot_bookings(), get_time_wallet() (+15 more)

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

### Community 51 - "move_slot"
Cohesion: 0.12
Nodes (12): manage_upcoming_slot(), Legacy editor uses the same atomic move as the upcoming-slot editor., update_booking(), booking_units(), Use persisted units rather than reinterpreting mutable console settings., move_slot(), Atomic schedule changes for upcoming bookings; financial records stay intact., fixture (+4 more)

### Community 52 - "search_booked_customers"
Cohesion: 0.33
Nodes (3): Bounded customer lookup across a cafe's complete booking history., search_booked_customers(), CustomerSearchTests

### Community 53 - "Transaction"
Cohesion: 0.25
Nodes (8): BookingGatewayPayment, One consumed Razorpay payment for one booking-confirmation batch., PassPurchase, Transaction, User, purchase(), PurchaseError, Authenticated, atomic pass purchase. Caller commits before responding.

### Community 54 - "Cafe payment methods: app handoff and rollout"
Cohesion: 0.25
Nodes (8): Acceptance rule, Booking payment, Cafe payment methods: app handoff and rollout, Cafe wallet and the unified QR, Dashboard flow and refunds, Deploy in this order, Discover enabled methods, Pass purchase

### Community 55 - "Mobile checkout: cafe context required"
Cohesion: 0.29
Nodes (4): Different errors need different UI handling, Mobile checkout: cafe context required, Validation completed, Why the payment screen fails

### Community 56 - "Game Controller"
Cohesion: 0.29
Nodes (7): DELETE /bookings/<int:booking_id>, Game Controller, GET /bookings/user/<int:user_id>, GET /games, GET /games/vendor/<int:vendor_id>, GET /getAllConsole/vendor/<int:vendor_id>, POST /bookings

### Community 57 - "UserPass"
Cohesion: 0.20
Nodes (6): Generate unique pass UID for hour-based passes, UserPass, date, Cancel a redemption and restore hours to pass. Args: redemption_id:…, Create hour-based user pass after purchase. Args: user_id: User ID…, Get valid hour-based pass for user. Priority: 1. If pass_uid provided, validate…

### Community 58 - "_ensure_menu_stock_available"
Cohesion: 0.33
Nodes (6): _consume_menu_stock(), _ensure_menu_stock_available(), _menu_stock_qty(), _menu_stock_unit(), Returns (is_available, error_message_or_none). stock_quantity=None means…, Decrement stock in-memory; caller transaction controls commit/rollback.

### Community 59 - "Client changes"
Cohesion: 0.50
Nodes (4): Client changes, POST /api/capture_payment, POST /api/create_order, POST /api/generate_payment_link (if used)

### Community 60 - "Slot Controller"
Cohesion: 0.50
Nodes (4): GET /getSlotList/vendor/<int:vendor_id>/game/<int:game_id>, GET /getSlots/vendor/<int:vendorId>/game/<int:gameId>/<string:date>, GET /slots, Slot Controller

### Community 67 - "Voucher"
Cohesion: 0.47
Nodes (3): redeem_voucher(), Voucher, create_referral_voucher()

### Community 68 - "Hash app team integration prompt"
Cohesion: 0.33
Nodes (5): Discovery, Hash app team integration prompt, UI and existing flow mapping, Updated 13 October 2026, Verification

### Community 69 - "test_operating_hours_availability.py"
Cohesion: 0.43
Nodes (7): compile_functions(), Saved hours must win over spare capacity in booking readers and preflight., test_batch_listing_does_not_offer_disabled_capacity(), test_closed_day_is_distinct_from_missing_legacy_configuration(), test_direct_booking_does_not_recreate_closed_day_slots(), test_precheck_rejects_disabled_slot_with_positive_capacity(), test_single_slot_listing_does_not_offer_disabled_capacity()

## Knowledge Gaps
- **50 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+45 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeferredBookingRealtime` connect `DeferredBookingRealtime` to `booking_controller.py`, `new_booking`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `move_slot()` connect `move_slot` to `ValueError`, `booking_controller.py`, `_compute_pay_at_cafe_pricing`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `BookingService` connect `BookingService` to `extensions.py`, `booking_controller.py`, `game_controller.py`, `ValueError`, `new_booking`, `PassService`, `accept_pay_at_cafe_booking`, `Transaction`, `Slot`, `UserPass`, `Booking`?**
  _High betweenness centrality (0.031) - this node is a cross-community bridge._
- **Are the 33 inferred relationships involving `ValueError` (e.g. with `calculate_extra_controller_fare()` and `cancel_bookings_with_refund()`) actually correct?**
  _`ValueError` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 14 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _50 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `booking_controller.py` be split into smaller, more focused modules?**
  _Cohesion score 0.08478513356562137 - nodes in this community are weakly interconnected._