# Flutter pricing API integration

Status: implemented in backend source; requires backend deployment before app integration. No Flutter files changed. Existing app bookings continue to use standard slot pricing.

## Read rates

Call `GET {bookingBaseUrl}/api/games/vendor/{vendor_id}/pricing`.
This is a public, read-only endpoint, like the existing vendor games endpoint. No staff credentials are needed. The existing `GET /api/games/vendor/{vendor_id}` response now includes `pricing_url` pointing to it. Resolve that relative URL against the booking service origin. Existing fields are unchanged.

Example response (illustrative prices):

```json
{
  "schema_version": 1,
  "vendor_id": 112,
  "currency": "INR",
  "display_only": true,
  "app_booking_policy": "standard_slot_pricing",
  "app_game_specific_booking_supported": false,
  "standard_quote_url": "/api/bookings/pricing-estimate",
  "platforms": [{
    "available_game_id": 10,
    "platform_name": "PlayStation",
    "standard": {
      "app_pricing_mode": "slot",
      "dashboard_pricing_mode": "slot",
      "base_slot_price": "50.00",
      "rate_cards": []
    },
    "game_specific": [{
      "profile": "gta6",
      "revision": 1,
      "pricing_type": "game_specific",
      "name": "GTA 6 Premium",
      "model_name": "PlayStation",
      "screen_size_inches": 55,
      "game_variant": "GTA 6",
      "controllers_included": true,
      "booking_channels": ["dashboard"],
      "rules": [{
        "min_minutes": 1, "max_minutes": null,
        "min_players": 1, "max_players": 4,
        "amount": "250", "unit_minutes": 60, "per_player": false
      }]
    }]
  }]
}
```

`available_game_id` identifies the café's platform/device pricing row. It is NOT the video-game catalog ID. Match it to `games[].id` in the existing vendor games response. Do not send a GTA catalog ID as the booking `game_id`.

`base_slot_price` is a decimal string in rupees per configured slot, before scheduled offers, squad/controller adjustments, and app fees. Do not assume a slot is one hour. Use the quote endpoint for estimates and the booking/payment response for the payable amount.

`standard.rate_cards` contains effective dashboard standard cards only when `dashboard_pricing_mode` is `variants`; otherwise it is empty. Their shape matches the example card, with `pricing_type: "standard"` and an empty `game_variant`. Game-specific cards remain listed even when dashboard standard pricing uses slots. Only active, nonarchived cards belonging to this vendor/platform are returned. Physical console IDs and staff settings are omitted. No platforms returns `platforms: []` (also for unknown vendors). Database failures return HTTP 503; show pricing unavailable and allow retry, never interpret failure as a zero price.

## Display rules

Show separate sections for “Standard pricing” and “Game-specific pricing”. Label all returned rate cards “Café dashboard bookings only” while `booking_channels` excludes the app. The Flutter app should continue booking with standard slot pricing while `app_game_specific_booking_supported` is false. Do not offer a premium-game purchase or calculate a premium payment locally.

Rules use inclusive minute/player ranges; null `max_minutes` is unbounded. Within the selected card, exactly one rule must match. Its amount is multiplied by player count only when `per_player` is true, and by `minutes / unit_minutes` when `unit_minutes` is nonzero. Zero means a flat session amount. Round the result to two decimals, half-up. This describes display estimates, not an authorization to collect payment.

Game-specific matching currently uses normalized `game_variant` text (lowercase, punctuation and spaces removed), not a catalog game ID. “GTA 6” matches “GTA6”; “Grand Theft Auto VI” is not automatically an alias. When a matching special card exists, the dashboard does not fall back to a cheaper standard card if no duration/player rule matches. Multiple model/screen cards can exist for the same title.

Responses use `Cache-Control: no-store`. Refresh rates when entering pricing and before starting checkout. Revisions identify changes; never treat a previously displayed rate as a guaranteed booking price.

## Standard app estimate

```http
GET /api/bookings/pricing-estimate?vendor_id=112&game_id=10&book_date=2026-12-01
X-Client-Source: app
```

Optional squad query fields are `squadEnabled=true&playerCount=2`. Use the same booking date and platform as checkout. The existing response has `success`, `matched_game_id`, `estimate_scope: "per_slot"`, `price_basis`, `squad_details`, and `pricing_engine` fields: `slot_unit_price`, `slot_base_total`, `squad_discount_percent`, `squad_discount_amount`, `extra_controller_qty`, `extra_controller_total`, `app_fee_amount`, `estimated_final_amount`. The final estimate field is before the separately returned app fee. Do not add fees twice or assume this per-slot estimate is the final multi-slot order total; use the server's booking/payment total.

## Future game-specific app checkout

Not enabled by this change. It requires coordinated support for game selection, model/card selection, server-side premium quotes, revision validation and premium booking/payment calculation in the app booking flow. Sending `pricingGame` or a displayed card amount to the current app booking endpoint does not enable this support. Keep the capability flag false until that end-to-end flow is implemented and tested.

## Backend rollout

Deploy hfg-booking with its existing desk-rate migrations applied (`20261103_desk_rates_and_history.sql`, `20261108_unified_pricing.sql`, `20261109_custom_desk_pricing.sql`, and existing console-assignment migrations where applicable). This addition needs no new migration. Configure standard and selective-game cards in the dashboard rate-card editor. Verify standard-only, mixed and special-only platforms, disabled/archived cards, and vendor isolation before app release.
