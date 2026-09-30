# Mobile checkout: cafe context required

Updated against local source on 30 September 2026. Production request bodies and
cafe policy data have not been inspected.

## Why the payment screen fails

The message `Supply vendor_id, game_id or booking_id for payment policy validation.`
is returned by `services/cafe_payment_policy.py`, registered as a Flask
`before_request` hook. It returns HTTP 400 with `code: cafe_context_required` for
`create_order`, `generate_payment_link` and `capture_payment` when it cannot
resolve a cafe. The route's Razorpay call has not run for that rejected request.
A failure at capture does not establish whether an earlier payment was charged;
retain gateway IDs and inspect/recover the existing payment instead of paying again.

The old create-order README example omitted cafe context. That example is now
corrected. A retry with the same missing fields will continue to fail.

## Client changes

Keep the selected cafe's actual numeric vendor ID in checkout state and forward
it through every payment request, including capture after the SDK callback. A
cafe name such as “Gear 5” is not its ID. Do not use a hard-coded fallback or guess
an ID. These examples use illustrative ID 123, not Gear 5's verified ID.

All URLs below use the BOOKING host, with the existing Hash gamer bearer token
and `Content-Type: application/json`.

### POST /api/create_order

```json
{
  "amount": 20000,
  "currency": "INR",
  "vendor_id": 123
}
```

For the screenshot's ₹200 payment, order amount is 20000 paise. Calculate the
actual amount from the current checkout, rather than hard-coding this example.
The server generates the receipt; user-provided receipt/notes are not booking proof.

### POST /api/capture_payment

```json
{
  "razorpay_payment_id": "<SDK payment ID>",
  "razorpay_order_id": "<SDK order ID>",
  "razorpay_signature": "<SDK signature>",
  "vendor_id": 123
}
```

Keep the same checkout cafe through the SDK callback. Do not fix order creation
alone: capture has the same policy requirement. Existing order/user/signature
checks remain required.

### POST /api/generate_payment_link (if used)

```json
{
  "amount": 200,
  "customer_email": "gamer@example.com",
  "customer_contact": "<gamer contact>",
  "vendor_id": 123
}
```

This legacy endpoint expects **rupees**, unlike create_order's **paise**. Do not
reuse an amount value across these APIs without converting the unit.

Instead of `vendor_id`, the guard can resolve an existing top-level `game_id`,
or `booking_id` (one ID or a list) through the database. Unknown game/booking IDs
do not resolve context. Nested `notes.vendor_id`, `vendorId`, cafe names and
query parameters are not read by the current guard. Prefer top-level vendor_id
for a checkout where no booking has been created yet.

## Different errors need different UI handling

- 400 `cafe_context_required`: fix the request context; repeated payment retry is
  not a recovery. Preserve the selected cafe across navigation and SDK callbacks.
- 403 `payment_method_disabled`: this cafe has disabled the requested method. Reload
  `/api/vendor/{vendor_id}/paymentMethods` on the dashboard API origin and show only
  enabled methods. A saved cafe-wallet policy does not disable other methods.
- Other gateway/auth errors: handle according to the endpoint response; do not
  label every failure as missing cafe context.

Do not remove the policy check to let unidentified payments through. Without
cafe context, the backend cannot determine whether online collection is allowed.
The selected cafe is known by the client; the backend cannot safely infer it from
amount, currency or a screen title.

## Validation completed

The payment-policy regression covers missing context (400), a saved wallet cafe
with gateway enabled (allowed), the same cafe after gateway is disabled (403),
and a different cafe with gateway enabled (allowed). No live payment was created.

For the six-method contract, pass purchase and rollout requirements, see
[six-method-payments.md](six-method-payments.md).
