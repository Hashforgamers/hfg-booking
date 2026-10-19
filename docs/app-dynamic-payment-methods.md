# Updated 13 October 2026

Cafe Wallet scheduled confirmation is now implemented locally: use payment_mode: cafe_wallet on /api/bookings/confirm after deploying the updated booking backend. The QR-only limitation in the original handoff below is superseded. See artifacts/unified-session-integration-20261013.md in the Hash workspace for the full contract.

# Hash app team integration prompt

Implement dynamic cafe payment choices in HFG-frontend. The backend change is additive; existing payment payloads remain unchanged. Deploy hfg-booking first. Do not use staff or kiosk credentials in the app.

## Discovery

Call `GET {BOOKING_BASE}/api/vendor/{vendor_id}/payment-methods` when opening booking checkout, changing cafe, resuming checkout and immediately before initiating a purchase. This public endpoint contains acceptance metadata only. Payment requests still require the existing app user bearer token.

Example:
```json
{
  "success": true,
  "vendor_id": 41,
  "enabled_payment_methods": ["hash_wallet", "payment_gateway", "pay_at_cafe"],
  "payment_methods": [
    {"method_name":"hash_wallet","display_name":"Hash Wallet","is_enabled":true},
    {"method_name":"cafe_wallet","display_name":"Cafe Wallet","is_enabled":false},
    {"method_name":"hash_global_pass","display_name":"Hash Game Pass","is_enabled":false},
    {"method_name":"cafe_specific_pass","display_name":"Cafe Game Pass","is_enabled":false},
    {"method_name":"payment_gateway","display_name":"UPI / Card","is_enabled":true},
    {"method_name":"pay_at_cafe","display_name":"Pay at Cafe","is_enabled":true}
  ]
}
```

Use the actual cafe/vendor ID, not console ID. Backend reads the same payment_vendor_map configured in Hash Dashboard; no cache, no migration needed. Existing dashboard discovery `/api/vendor/{vendor_id}/paymentMethods` remains available unchanged.

## UI and existing flow mapping

Replace hard-coded chips in `lib/app/modules/arena/views/booking_summary_screen.dart` with enabled supported options:
- hash_wallet -> existing wallet selection and wallet confirmation.
- payment_gateway -> existing gateway selection and Razorpay flow.
- pay_at_cafe -> existing is_pay_at_cafe true flow.
- hash_global_pass / cafe_specific_pass -> show only passes of the matching scope. Derive scope from the pass catalog vendor_id; null means global. Keep existing date_pass/hour_pass confirmation payloads. The current 'none' UI value is not an API payment method.
- cafe_wallet -> only expose where a supported cafe-wallet checkout exists (the existing QR checkout). Do not map it to global wallet or offer it on scheduled checkout without implementing that supported flow. Acceptance alone does not mean funds, passes, slots or QR self-service eligibility are available; use the corresponding checkout quote.

If a selected method becomes disabled, clear it and require reselection. An empty enabled list means no app payment options; show a clear message and disable purchase. A 404 means cafe unavailable. On 503/network failure, show retry and disable purchase until settings load; do not silently assume all methods are enabled. Discard late responses for a previously selected cafe.

On a payment request returning 403 with code payment_method_disabled, refresh discovery, clear the invalid selection and display the readable message. Do not automatically create another gateway order or charge. Captured/uncertain gateway payments must use the existing reconciliation flow. A settings switch does not invalidate a previously accepted booking, end a running session, or remove wallet/history access.

## Verification

Test each dashboard switch enabled/disabled, two cafes with different settings, empty options, stale checkout after a switch, slow/out-of-order discovery, load failure, and existing paid-booking access. Ensure disabled methods cannot initiate payment and no duplicate payments occur on retry.

Backend local validation: two tests exercise all six options, legacy wallet alias, cafe isolation, changes on the next read, missing cafe and database failure. Frontend repository was not edited. Production deployment and app integration remain pending.
