# App Booking Cancellation API

## Endpoint
- `POST /api/bookings/cancel/app`
- Auth: `Authorization: Bearer <app_jwt>` (same app token used for `/api/bookings`)

## Request
```json
{
  "booking_ids": [724, 725],
  "reason": "Plan changed",
  "repayment_type": "credit"
}
```

### Request fields
- `booking_ids` or `booking_id` (required)
- `reason` (optional)
- `repayment_type` (optional): `refund | credit | none`
  - If omitted: backend auto-picks per payment type

## Success response (200)
```json
{
  "success": true,
  "message": "Booking cancelled",
  "cancelled_ids": [724],
  "skipped_ids": [],
  "unauthorized_ids": [],
  "refund_total": 95.0,
  "cancellation_fee_total": 5.0,
  "pass_hours_restored_total": 0.0,
  "repayment_type": "auto",
  "reason": "Plan changed",
  "bookings": [
    {
      "booking_id": 724,
      "repayment_type": "credit",
      "refund_amount": 95.0,
      "cancellation_fee": 5.0,
      "wallet_credit_amount": 95.0,
      "payment_use_case": "hash_wallet",
      "is_pay_at_cafe": false,
      "pass_hours_restored": 0.0,
      "status": "cancelled"
    }
  ]
}
```

## Failure responses
- `400`: no eligible booking cancelled
- `403`: booking does not belong to token user
- `404`: booking not found
- `500`: internal failure

## Real-time socket events emitted
On successful cancellation, backend emits:
- `booking`
  - `{ booking_id, vendor_id, slot_id, status: "cancelled", booking_status: "cancelled", ... }`
- `booking_payment_update`
  - `{ event: "booking_cancelled", bookingId, repayment_type, refund_total, cancellation_fee, wallet_credit_amount, pass_hours_restored, ... }`

These events are already consumed by dashboard bridge and upcoming/live UI.

## Cancellation fee envs
- `CANCELLATION_FEE_ENABLED` (default `true`)
- `CANCELLATION_FEE_PERCENT` (default `5`)
- `CANCELLATION_FEE_FLAT` (default `0`)
- `CANCELLATION_FEE_MIN` (default `0`)
- `CANCELLATION_FEE_MAX` (default `50`)
- `CANCELLATION_FREE_BEFORE_MINUTES` (default `180`)
- `CANCELLATION_FEE_APPLY_ON_PAY_AT_CAFE` (default `false`)
- `CANCELLATION_FEE_APPLY_ON_PASS` (default `false`)

## Strategy implemented
- `hash_wallet`: cancel + refund to wallet when repayment type is `credit`
- `pass`:
  - hour-pass redemption is restored automatically (`pass_redemption_logs` cancellation)
  - date/global pass cancellations do not create cash refunds by default
- `pay_at_cafe`: pending/unpaid bookings cancel without refund by default (low-noise), fee on this path is opt-in via env
