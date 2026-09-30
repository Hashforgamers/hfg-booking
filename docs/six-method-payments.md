# Cafe payment methods: app handoff and rollout

Local implementation, 30 September 2026. These changes have not been deployed or exercised against live Razorpay payments.

## Acceptance rule

Each cafe independently enables any combination of these canonical keys:

| Key | App flow | Money unit |
| --- | --- | --- |
| `hash_wallet` | Confirm a booking with `payment_mode: "wallet"` | Global wallet stores whole INR rupees |
| `cafe_wallet` | Cafe wallet reads; instant QR session checkout | Integer INR paise |
| `hash_global_pass` | Confirm with the user's global date/hour pass | Hours or validity dates |
| `cafe_specific_pass` | Confirm with a pass issued by this cafe | Hours or validity dates |
| `payment_gateway` | Create order, complete Razorpay payment, confirm booking | Order amount in integer INR paise |
| `pay_at_cafe` | Create a booking with `is_pay_at_cafe: true`; cafe accepts and collects | Booking totals in INR rupees |

Enabling cafe wallet does not disable any other method. Global versus cafe pass is derived from the pass catalog's `vendor_id`, not a label supplied by the app. A global pass has `vendor_id: null`. Disabling a method blocks new charges; wallet history and previously paid bookings remain usable. Cafe pass catalog edits no longer switch payment acceptance on automatically.

`BOOKING_BASE` and `DASHBOARD_BASE` mean service origins for the selected environment, not website origins. Never ship `X-Wallet-Credit-Token`, staff credentials, gateway secrets, or PC agent tokens in the app.

## Discover enabled methods

```http
GET {DASHBOARD_BASE}/api/vendor/{vendor_id}/paymentMethods
```

Response includes `success`, `vendor_id`, and `payment_methods`, an array of six entries with `pay_method_id`, `method_name`, `display_name`, `description`, `is_enabled`, and `is_auto_managed: false`. Show enabled methods only. Re-fetch after a `payment_method_disabled` response; the server remains authoritative.

Cafe settings are changed only by an authorized named staff session with `account.manage`:

```http
POST {DASHBOARD_BASE}/api/vendor/{vendor_id}/paymentMethods/toggle
Authorization: Bearer <staff_access_token>
Content-Type: application/json

{"pay_method_id": 12, "is_enabled": true}
```

Use the ID from discovery. Send the desired boolean state so a retry cannot flip the setting back. Read the result from `response.data.is_enabled`. Cafe-specific pricing/QR settings remain separate from payment acceptance. Notification preferences only configure notifications.

## Booking payment

Use the existing Hash app JWT on booking API calls.

1. Create the hold with `POST {BOOKING_BASE}/api/bookings`, using `game_id`, `slot_id` (array), and `book_date`. Use `is_pay_at_cafe: true` only for the cafe acceptance flow; it must be a JSON boolean.
2. For gateway payment, use `POST /api/create_order` with `amount` in paise and `vendor_id` (or existing booking/game context). Keep the returned order ID through SDK capture and confirmation. See [gateway context](mobile-payment-cafe-context.md).
3. Confirm with `POST /api/bookings/confirm` (alias `/api/confirm/bookings`):

```json
{
  "booking_id": [123],
  "book_date": "2026-10-01",
  "payment_mode": "wallet"
}
```

Use `payment_mode: "payment_gateway"` plus `payment_id` and `razorpay_order_id` for Razorpay; `"hour_pass"` plus `hour_pass_uid` (alias `pass_uid`) for hour passes; `"date_pass"` plus `user_pass_id` for date passes. The same pass payload applies to global and cafe-specific passes. The backend checks the owner, cafe scope, validity, remaining hours and enabled method.

Do not call `/pass/redeem/app` separately: it returns 409 directing clients to atomic booking confirmation. Direct `/pass/redemption/{id}/cancel` is also disabled; cancel the owned booking so pass restoration and booking state change happen together. Food/extras cannot be paid for with a gaming pass. Unknown payment modes and cash confirmation are rejected.

Confirmation binds `book_date` to the reserved date and prices the selected slot schedule. Old unpaid holds without a stored date must be recreated after deployment. Confirmation verifies captured INR amount, payment ownership and replay protection. A repeated gateway confirmation returns 409 rather than charging again. Preserve payment and booking IDs and refresh booking status; never create a replacement payment automatically after a timeout.

## Pass purchase

Read catalog: `GET {BOOKING_BASE}/api/vendor/{vendor_id}/passes/available`.
Read owned active hour passes: `GET {BOOKING_BASE}/api/pass/user/active?vendor_id={vendor_id}` with app JWT. History: `GET /api/pass/{user_pass_id}/history`, restricted to the owner.

For gateway purchase, first create an order with `POST /api/create_order` and `{"cafe_pass_id": 45}`. The server selects the catalog price; the client does not choose the purchase amount. Complete payment through Razorpay, then:

```http
POST {BOOKING_BASE}/api/user/passes/purchase
Authorization: Bearer <hash_app_jwt>
Content-Type: application/json

{
  "cafe_pass_id": 45,
  "payment_mode": "payment_gateway",
  "payment_id": "pay_from_sdk",
  "idempotency_key": "unique-purchase-request-id"
}
```

For Hash Wallet use `payment_mode: "wallet"`, omit `payment_id`, and retain the same idempotency key for retries (8–100 characters). The user ID comes from the verified JWT; another user's ID is rejected. Successful new purchases return 201; identical retries return 200 without another debit or pass. Reusing a key with different purchase details returns 409. A gateway payment/order cannot buy both a pass and a booking.

The legacy `/api/pass/create-hour-pass` now delegates to the same paid, authenticated purchase handler. It cannot mint free passes. Cafe-specific pass sales require cafe-pass acceptance and the selected purchase payment method to be enabled.

## Cafe wallet and the unified QR

The app displays cafe wallet balance and history, with top-ups handled exclusively by cafe staff. Share the detailed [read-only wallet API guide](../../hfg-dashboard-service/docs/cafe-wallet-app-api.md) with the app team:

- `POST {BOOKING_BASE}/api/cafe-checkout/token`: exchange existing app JWT for a short-lived cafe gamer token.
- `GET {DASHBOARD_BASE}/api/cafe/wallets`: paginated wallets belonging to the gamer.
- `GET {DASHBOARD_BASE}/api/cafe/{vendor_id}/wallet`: balance, reserved and available balance.
- `GET {DASHBOARD_BASE}/api/cafe/{vendor_id}/wallet/history`: paginated ledger.

All three reads use the cafe gamer token and integer paise. They work without scanning a QR. Do not show an online cafe-wallet top-up button.

The single PC QR resolves via `GET {DASHBOARD_BASE}/api/cafe/checkout?qr=...`. The response now includes `enabled_payment_methods`, cafe/PC details, wallet availability and eligible existing bookings. `POST /api/cafe/checkout` either starts an existing paid booking or reserves a new cafe-wallet session. It does not directly charge a global wallet/pass/gateway: complete those through the booking API, then scan/start that booking without paying twice. Existing PC acknowledgement, timeout release and reconciliation still apply. See [agent and QR contract](../../hfg-dashboard-service/docs/cafe-wallet-rollout.md).

## Dashboard flow and refunds

All financial booking mutations require a signed cafe-scoped vendor/staff identity; named staff sessions are checked for expiry/logout. The server verifies booking/game ownership. Automatic and signed-email pay-at-cafe actions use a server-generated 60-second capability restricted to one booking and action.

The dashboard obtains customer pass approval first, then submits `pass_uid` and `pass_verification_token` together with `/api/newBooking/vendor/{vendor_id}`. Hours are calculated from actual slots/catalog configuration and deducted in the same transaction that creates the booking. OTP state is shared in PostgreSQL across workers and consumed transactionally. Desk wallet/gateway labels cannot mark a booking paid; use the authenticated app checkout. Cash/card/UPI and monthly credit remain desk collection methods.

Cancellation locks bookings to prevent duplicate refunds and restores pass hours once. An unpaid booking cannot create wallet credit, even if the caller asks for it. Gateway/original-payment refunds are recorded as **pending** until handled operationally; this release does not submit provider refunds. Do not tell customers that a pending refund has reached their bank. Hash Wallet's integer schema rejects fractional debits/credits instead of silently rounding; use gateway for fractional amounts.

## Deploy in this order

1. Apply existing cafe-wallet/QR migrations from the cafe rollout guide and `hfg-booking/sql/20260817_booking_gateway_payment_reconciliation.sql` if not already deployed.
2. Apply `hfg-dashboard-service/sql/20260929_payment_methods.sql`. Its one-time seed preserves prior wallet/gateway acceptance and existing cafe-wallet/cafe-pass adoption. Rerunning the migration does not re-enable methods disabled after rollout. Review each cafe's selections afterward. New cafes explicitly choose their methods in settings.
3. Apply `hfg-booking/sql/20260929_pass_purchases.sql` and `hfg-booking/sql/20260930_pass_otp_states.sql` to the shared database.
4. Deploy booking service, dashboard service and dashboard frontend together. Have staff unlock again if their sessions predate the cafe session records. Deploy app request changes before retiring any old app workflow that pre-redeems passes.
5. Verify all six combinations on a test cafe, including one disabled method, insufficient balances, duplicate requests, declined payments, expired OTP, booking failure after approval and cancellation. Use Razorpay test mode and a simulated PC first; native PC integration and live settlement require separate environment verification.

Local tests cover payment settings, migration reruns, database concurrency, purchase replay, owner/cafe isolation, pass rollback/restoration, OTP persistence, wallet reads and PC reservation reconciliation. They do not certify a production deployment or real bank settlement.
