# Graph Report - hfg-booking  (2026-10-03)

## Corpus Check
- 103 files · ~62,404 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 767 nodes · 1839 edges · 64 communities (55 shown, 9 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 78 edges (avg confidence: 0.67)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c822e356`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- _release_slot_for_booking
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
- Transaction
- DeferredBookingRealtime
- ReleaseTests
- Booking
- new_booking
- accept_pay_at_cafe_booking
- test_payment_integrity.py
- vendor_access.py
- Slot
- App Booking Cancellation API
- ConsolePricingOffer
- test_slot_cache.py
- extensions.py
- date
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
- Booking Controller
- search_booked_customers
- pass_purchase_service.py
- Cafe payment methods: app handoff and rollout
- Mobile checkout: cafe context required
- Game Controller
- PassOtpStore
- Voucher
- Client changes
- credit_unused_slots_to_wallet
- kiosk_book_next_slot

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
- `BookingService` --uses--> `UserPass`  [INFERRED]
  services/booking_service.py → models/passModels.py

## Import Cycles
- None detected.

## Communities (64 total, 9 thin omitted)

### Community 0 - "_release_slot_for_booking"
Cohesion: 0.13
Nodes (10): release_slot(), _release_slot_for_booking(), Release an unverified booking once, atomically with its capacity., booking_units(), Dated capacity contract shared by independently deployed booking services. The…, Use persisted units rather than reinterpreting mutable console settings., release_slot(), move_slot() (+2 more)

### Community 1 - "booking_controller.py"
Cohesion: 0.08
Nodes (29): _collect_vendor_user_ids(), _ensure_vendor_booking_field_preferences_table(), _ensure_vendor_pay_at_cafe_settings_table(), get_pay_at_cafe_settings(), get_user_details(), _get_vendor_pay_at_cafe_settings(), _load_vendor_booking_field_config(), _log_pricing_event() (+21 more)

### Community 2 - "game_controller.py"
Cohesion: 0.14
Nodes (30): cancel_booking(), create_booking(), create_or_update_console_type_override(), deactivate_console_type_override(), _games_cache_get(), _games_cache_set(), get_all_console_by_vendor_id(), get_all_games() (+22 more)

### Community 3 - "realtime.py"
Cohesion: 0.22
Nodes (15): BlockLike, TimeLike, _as_date_str(), _as_mapping(), _canonical_payload(), _coalesce(), _derive_status_label(), _fmt_time() (+7 more)

### Community 4 - "booking_service.py"
Cohesion: 0.11
Nodes (10): Decimal, BookingExtraService, ExtraServiceMenu, ExtraServiceMenuImage, HashWallet, HashWalletTransaction, PaymentTransactionMapping, BookingService (+2 more)

### Community 5 - "HFG Booking Service"
Cohesion: 0.17
Nodes (12): Booking (`models/booking.py`), BookingService (`services/booking_service.py`), Core Services, HFG Booking Service, Key Features, Models, Overview, Setup (+4 more)

### Community 6 - "mail_service.py"
Cohesion: 0.20
Nodes (15): HTMLParser, build_hfg_email_html(), email_text(), _EmailText, _extract_body(), Generate a useful plain-text alternative, retaining links and table values., booking_mail(), extra_booking_time_mail() (+7 more)

### Community 7 - "slot_controller.py"
Cohesion: 0.13
Nodes (23): _ensure_slots_for_date(), _expected_blocks_for_date(), _force_slot_refresh(), _generate_blocks(), get_next_six_slot_for_game(), get_slots(), get_slots_batch(), get_slots_on_game_id() (+15 more)

### Community 8 - "route"
Cohesion: 0.09
Nodes (26): booking_payment_summary(), cancel_booking(), cancel_bookings_app_route(), cancel_bookings_route(), capture_payment(), create_render_one_off_job(), generate_payment_link(), get_booking_details() (+18 more)

### Community 9 - "Flask"
Cohesion: 0.06
Nodes (45): Config, create_app(), _is_insecure_secret(), _validate_production_config(), create_order(), cafe_checkout_token(), digest(), issue_token() (+37 more)

### Community 10 - "get_pending_pay_at_cafe_bookings"
Cohesion: 0.21
Nodes (11): _ensure_pay_at_cafe_action_logs_table(), _fetch_pay_at_cafe_queue_id_sets(), get_pay_at_cafe_queue_list(), get_pay_at_cafe_queue_summary(), get_pending_pay_at_cafe_bookings(), get_user_bookings(), _parse_pay_at_cafe_queue_date_filters(), _pay_at_cafe_queue_date_predicate() (+3 more)

### Community 11 - "gaming_type_controller.py"
Cohesion: 0.23
Nodes (8): create_gaming_type(), delete_gaming_type(), get_gaming_types(), route, GamingTypeService, Create a new gaming type. :param data: Dictionary containing 'name', Delete an existing gaming type. :param gaming_type_id: ID of the gaming type to…, Fetch all available gaming types.

### Community 13 - "pass_controller.py"
Cohesion: 0.22
Nodes (15): _cleanup_pass_otp_cache(), _consume_pass_verification_token(), _find_live_otp_session(), get_available_passes_for_purchase(), _hash_otp(), _mask_email(), _otp_secret(), _passes_cache_get() (+7 more)

### Community 14 - "Transaction"
Cohesion: 0.14
Nodes (23): add_meals_to_booking(), calculate_gst_breakdown(), compute_booking_financial_summary(), direct_booking(), extra_booking(), normalize_payment_use_case(), Settle monthly credit outstanding at month-end. Body: { "user_id": 1, "amount":…, Resolve app fee (platform fee) for transparency. App fee must be applied only… (+15 more)

### Community 15 - "DeferredBookingRealtime"
Cohesion: 0.18
Nodes (6): patch, DeferredBookingRealtime, Keep best-effort realtime delivery outside committed booking responses., BookingMailTests, Test the production background mail helper without booting network services., BookingRealtimeTests

### Community 17 - "Booking"
Cohesion: 0.15
Nodes (10): fixture, AvailableGame, Booking, Updated to include private booking fields, CafePass, PassRedemptionLog, PassType, Vendor (+2 more)

### Community 18 - "new_booking"
Cohesion: 0.05
Nodes (73): booking_pricing_estimate(), booking_pricing_preview(), _build_squad_member_bindings(), _build_vendor_platform_rules(), calculate_extra_controller_fare(), _coerce_date_value(), _compute_pay_at_cafe_pricing(), confirm_booking() (+65 more)

### Community 19 - "accept_pay_at_cafe_booking"
Cohesion: 0.14
Nodes (16): accept_pay_at_cafe_booking(), _invalidate_pay_at_cafe_vendor_cache(), _json_text_equals(), _log_pay_at_cafe_action(), _parse_json_details(), Dialect-safe JSON text comparison (SQLAlchemy 2.0 removed .astext)., Resolve pay-at-cafe squad bookings by batch_id with a safe fallback that avoids…, Accept a pay-at-cafe booking and change status to confirmed (+8 more)

### Community 20 - "test_payment_integrity.py"
Cohesion: 0.20
Nodes (13): parametrize, body(), Payment invariants against real ORM code in isolated PostgreSQL schemas.…, test_disabled_cafe_pass_purchase_does_not_debit(), test_failed_booking_rolls_back_pass_and_verification_consumption(), test_gateway_owner_pass_binding_and_cross_checkout_replay(), test_gateway_requires_exact_captured_inr_payment(), test_gateway_success_and_replay() (+5 more)

### Community 21 - "vendor_access.py"
Cohesion: 0.17
Nodes (14): _build_pay_at_cafe_email_action_url(), _decode_pay_at_cafe_email_action_token(), _pay_at_cafe_action_serializer(), pay_at_cafe_email_action(), One-click email action endpoint for vendor to accept/reject pay-at-cafe…, _render_pay_at_cafe_email_action_page(), _resolve_booking_public_base_url(), _resolve_dashboard_public_url() (+6 more)

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

### Community 26 - "extensions.py"
Cohesion: 0.20
Nodes (5): configure_socketio(), Configures SocketIO with the Flask app., AccessBookingCode, BookingSquadMember, HashCoinTransaction

### Community 28 - "date"
Cohesion: 0.17
Nodes (19): _append_cancellation_note(), _booking_slot_start_datetime_ist(), cancel_bookings_with_refund(), _credit_wallet_for_cancellation(), _default_repayment_type(), get_all_booking(), get_vendor_booking_stats(), _is_no_show_eligible() (+11 more)

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
Nodes (9): API Endpoints, DELETE /gaming-types/<int:gaming_type_id>, Gaming Type Controller, GET /gaming-types, GET /getSlotList/vendor/<int:vendor_id>/game/<int:game_id>, GET /getSlots/vendor/<int:vendorId>/game/<int:gameId>/<string:date>, GET /slots, POST /gaming-types (+1 more)

### Community 51 - "Booking Controller"
Cohesion: 0.50
Nodes (4): Booking Controller, GET /bookings/<booking_id>, POST /bookings, POST /create_order

### Community 52 - "search_booked_customers"
Cohesion: 0.33
Nodes (3): Bounded customer lookup across a cafe's complete booking history., search_booked_customers(), CustomerSearchTests

### Community 53 - "pass_purchase_service.py"
Cohesion: 0.18
Nodes (10): BookingGatewayPayment, One consumed Razorpay payment for one booking-confirmation batch., Generate unique pass UID for hour-based passes, UserPass, PassPurchase, User, purchase(), PurchaseError (+2 more)

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
Cohesion: 0.27
Nodes (4): cleanup(), PassOtpState, PassOtpStore, Database-backed OTP state shared by all booking workers. Writes participate in…

### Community 59 - "Client changes"
Cohesion: 0.50
Nodes (4): Client changes, POST /api/capture_payment, POST /api/create_order, POST /api/generate_payment_link (if used)

### Community 64 - "credit_unused_slots_to_wallet"
Cohesion: 0.40
Nodes (5): calculate_slot_minutes(), credit_unused_slots_to_wallet(), Credit unused booked slots to user's time wallet. Body: { "user_id": 1,…, TimeWalletAccount, TimeWalletLedger

### Community 65 - "kiosk_book_next_slot"
Cohesion: 0.17
Nodes (17): _coerce_int_value(), compute_credit_due_date(), _ensure_vendor_slot_rows_for_date(), _ist_now_naive(), kiosk_book_next_slot(), kiosk_check_next_slot(), _precheck_slot_booking_eligibility(), datetime (+9 more)

## Knowledge Gaps
- **46 isolated node(s):** `HashCoinTransaction`, `booking_gateway_payments`, `graphify`, `Overview`, `Key Features` (+41 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **9 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeferredBookingRealtime` connect `DeferredBookingRealtime` to `booking_controller.py`, `new_booking`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `Slot` connect `Slot` to `credit_unused_slots_to_wallet`, `booking_controller.py`, `booking_service.py`, `slot_controller.py`, `pass_controller.py`, `Booking`, `extensions.py`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `BookingService` connect `booking_service.py` to `_release_slot_for_booking`, `booking_controller.py`, `game_controller.py`, `get_pending_pay_at_cafe_bookings`, `Transaction`, `Booking`, `new_booking`, `accept_pay_at_cafe_booking`, `pass_purchase_service.py`, `Slot`?**
  _High betweenness centrality (0.033) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `BookingService` (e.g. with `AvailableGame` and `Booking`) actually correct?**
  _`BookingService` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `ValueError` (e.g. with `calculate_extra_controller_fare()` and `cancel_bookings_with_refund()`) actually correct?**
  _`ValueError` has 31 INFERRED edges - model-reasoned connections that need verification._
- **What connects `HashCoinTransaction`, `booking_gateway_payments`, `graphify` to the rest of the system?**
  _46 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `_release_slot_for_booking` be split into smaller, more focused modules?**
  _Cohesion score 0.12987012987012986 - nodes in this community are weakly interconnected._