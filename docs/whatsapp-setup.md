# HFG WhatsApp: shared sender, café preferences and prepaid credits

Implemented in hfg-booking, hash-dashboard and vendor-Onboard. Flutter is unchanged. Deployment and real provider configuration are still required; no live messages or payments were sent during development.

## What each team manages

Super-admin → WhatsApp:
- One shared Hash for Gamers Meta sender; phone number ID, API version, access token, app secret and verification token.
- Razorpay webhook signing secret (payment API credentials use the existing HFG server configuration).
- Approved template allowlist and the INR price of a 100-message pack.
- Café balances. Sender secrets are encrypted in the database and never returned to browsers; blank secret inputs preserve saved values.

Café dashboard → Settings → Notification Preferences → WhatsApp:
- Buy a 100-message pack through Razorpay; captured and verified payment automatically activates credits.
- Enable/disable confirmations, reminders, manual updates, promotions and booking-link replies independently.
- Choose confirmation/reminder/link templates and a reminder lead time of 5–1440 minutes.
- Set a café HTTPS booking URL.
- Record or revoke service and marketing consent separately for a country-code phone number.
- Queue individual updates/promotions, see delivery history, remaining balance and credit activity.

All features start disabled per café. There is no free starting balance. Enabling preferences does not purchase credits.

## Deployment

1. Apply `sql/20261116_whatsapp.sql` to the booking PostgreSQL database. It is rerunnable.
2. Set `WHATSAPP_CONFIG_KEY` on the booking server to a Fernet key. Generate once using `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` in a secure operator environment. Back up this key securely; do not regenerate on every deployment. Existing credentials cannot be decrypted if it is lost. Rotation requires decrypt/re-encrypt migration.
3. Set the same server-only `SUPER_ADMIN_API_KEY` in booking backend and the super-admin Next.js deployment. Existing super-admin Basic authentication still protects the proxy.
4. Set server-only `BOOKING_BACKEND_URL` in the super-admin deployment to the booking origin. Only `/api/backend/admin/whatsapp/*` is routed there.
5. Verify the existing booking-server `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` belong to the HFG collection account, and configure automatic capture. Test mode and live mode must match the frontend key and webhook setup. Pack prices are in INR; configure your intended all-inclusive customer price. This pack price is an HFG product price, not a live quotation of Meta's per-message charges.
6. Deploy booking backend, café dashboard and super-admin.
7. In super-admin, save the sender credentials and approved templates while sending is disabled.
8. Configure Meta webhook URL `https://<booking-origin>/api/whatsapp/webhook`. Use the saved verification token and subscribe the WhatsApp Business Account to message events. The app secret verifies `X-Hub-Signature-256`; status events are restricted to the configured phone-number ID. Meta setup/business verification/template approval is performed in Meta's console.
9. Configure Razorpay webhook URL `https://<booking-origin>/api/whatsapp/payment-webhook`, subscribe to `payment.captured`, and save its signing secret in super-admin. Both webhook and browser verification fetch the payment server-side and validate captured status, matching order, amount, currency and café ownership before granting credits. Repeated callbacks grant only once.
10. The booking Docker deployment runs `flask --app app whatsapp-dispatch` every 30 seconds alongside the API and RQ worker. Each run scans enabled booking automations and dispatches up to 100 queued messages. Confirm the dispatcher loop is present in deployment logs; no sending occurs if it is stopped. Multiple dispatchers use row locks to claim separate messages. Scale dispatch frequency/workers as volume grows.
11. Enable the shared sender, purchase a test pack, record test consent, configure café rules and verify end-to-end delivery before switching to live payments.

## Approved template examples

This first version supports templates with text body parameters only. Header/media/button parameter templates and free-form agent chat are not supported. Template names/languages must exactly match Meta approvals. The fields array names the parameters in the exact approved order; it does not create templates at Meta.

```json
[
  {"name":"hfg_booking_confirmation","language":"en","fields":["customer","cafe","booking_id","date and time"]},
  {"name":"hfg_booking_reminder","language":"en","fields":["customer","cafe","date and time"]},
  {"name":"hfg_booking_link","language":"en","fields":["cafe","booking_url"]},
  {"name":"hfg_customer_update","language":"en","fields":["Customer","Update"]},
  {"name":"hfg_promotion","language":"en","fields":["Customer","Offer"]}
]
```

Approve marketing templates for promotions and utility templates for service messages. Café staff choose only from this central allowlist. The super-admin must ensure the allowlist remains aligned with approved template content/category and account status.

Automation fields supported: `customer`, `cafe`, `booking_id`, `date`, `time`, `date and time`, `booking_url` (case-insensitive). Booking-link templates support only `cafe` and `booking_url`. Manual messages allow custom field labels.

## Behavior and limits

- Confirmation automation processes persisted `confirmed` booking records created after confirmation automation was enabled, with future start times. It does not backfill older bookings or message pending requests. Each booking record has an idempotent event key; multi-slot bookings stored as separate records may receive separate notices.
- Reminder automation uses Asia/Kolkata, the saved booking date/start, the café's lead time and recorded service consent. It scans bookings through the next three days and never sends after the start. Queued confirmations/reminders expire at their start time. It processes at most 1,000 upcoming records per café per run.
- Automatic booking messages cover the existing confirmed booking records from both channels without changing Flutter. Consent must first be recorded in the dashboard. Ten-digit stored Indian booking phone numbers are normalized with +91; consent entries require full country code.
- Promotions are individual template sends in this release, not bulk campaigns or scheduled marketing. Separate recorded marketing consent is required. Manual updates additionally require a per-message consent record.
- Customers send `BOOK <cafe-id>` (e.g. `BOOK 112`) to the shared number to receive the café's link. Requests are routed explicitly rather than guessing which café owns a phone number. Link replies use one café credit, require an enabled rule/template, and are limited to one per recipient/café per hour. Customer-initiated requests do not automatically grant marketing consent. Actual reservation and payment happen on the existing booking page; WhatsApp does not bypass availability checks.
- `STOP`, `STOP ALL`, or `UNSUBSCRIBE` opt the customer out globally from the shared HFG sender. Dashboard consent changes cannot override that opt-out. Re-subscription is not exposed in this release.
- Preferences and applicable consent are checked again before dispatch. Disabled rules, expired notices or opt-outs suppress pending messages and return their credits.
- Unknown incoming text is not auto-replied to. There is no full support inbox/conversational booking engine in this release.

## Credits and failure handling

One credit is reserved atomically when a message is queued. Retries do not consume another credit. Successful delivery uses that credit. Confirmed API/delivery failures and suppressed messages return it exactly once. A timeout or interrupted dispatch has an unknown outcome and keeps the credit reserved to avoid duplicate sends/refunds. Inspect provider status before any manual repair. The next worker run marks stale `sending` rows as `unknown` after five minutes. Delivery callbacks can still resolve an unknown message.

HTTP 429 retries after five minutes, with at most five attempts. Other API errors fail visibly rather than repeatedly charging/sending. Pack creation is idempotent by request UUID; uncertain provider order creation is flagged for operator reconciliation, not silently retried. Manual dashboard sending is limited to 100 queue requests per café/hour; pack order creation to 10/hour.

Reconcile unknown payment orders using their purchase UUID stored as Razorpay receipt. Do not grant credits based on a browser success screen or screenshot. Credit changes are recorded in `whatsapp_credit_ledger` with unique purchase/send/refund references. Cash refunds, chargebacks, disputes, tax invoices and operator adjustments are not automated by this integration; monitor the HFG payment account and handle those through your finance process.

## Verification

Automated tests use disposable PostgreSQL and mocked Meta/Razorpay calls. They cover secret encryption/redaction, authorization boundaries, insufficient credits, idempotent grants/debits, captured payment validation, signed webhooks, out-of-order status callbacks, opt-out, consent, automation timing, booking-link routing and duplicate events. Real provider acceptance still requires configured sender/template/account and sandbox end-to-end testing.

## Operations reporting and connection checks

Super-admin WhatsApp now includes a guided setup checklist, secure verification-token generator, copyable callback URLs, and read-only validation of the saved Meta sender, WABA/sender ownership, configured template approval, and Razorpay API credentials. Save before validating. Razorpay keys remain in the existing booking-server configuration; a successful API check does not prove payment capture or webhook delivery. Webhook evidence is recorded only after a successful verification challenge or valid signed callback for the configured sender. Saving configuration marks older evidence as needing a fresh test.

Add the numeric `WABA_ID` in super-admin (Meta Business Settings → Accounts → WhatsApp Accounts). The sender phone-number ID is a different ID. Use a supported Graph API version; v1.0 is rejected. Use a production system-user access token with `whatsapp_business_management` and `whatsapp_business_messaging` permissions and access to the intended WABA.

The backend URL error means the super-admin host needs server-side `BOOKING_BACKEND_URL` set to the booking origin and a redeployment. The proxy also accepts the existing `NEXT_PUBLIC_BOOKING_URL` as a fallback. It does not guess a production host. Save is disabled while configuration loading fails, and missing reports are not displayed as empty businesses.

Reapply the SQL migration to add `whatsapp_provider_checks`. The operations report provides 7/30/90-day gross captured pack collections, paid packs, current credit balances, message statuses, café totals and CSV export. Collections are not net profit; refunds/taxes/provider fees are not subtracted. Delivery statistics are grouped by the message's queue date, not callback date.

Fetch Meta report calls the official WABA `pricing_analytics` edge, using the account's own currency. This covers the whole WABA, potentially including traffic outside HFG. Empty, denied or missing cost data is not replaced with zero. The report does not expose an authoritative account balance; use the Meta Billing link for payable/prepaid balance and invoices. Café credits are an HFG entitlement, not Meta money. Do not subtract WABA cost from HFG pack collections to claim profit without reconciling currency, timing and account scope.

Provider references:
- https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account/pricing_analytics/
- https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account
- https://razorpay.com/security/checklist/
