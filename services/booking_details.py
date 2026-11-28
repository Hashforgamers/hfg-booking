"""Booking details for the dashboard: how a booking was made and paid.

Pure helpers (no DB) so the labels can be tested; the route in
controllers/booking_details_controller.py feeds them rows.
"""

SOURCE_LABELS = {
    "dashboard": "Walk-in desk",
    "app": "Hash app",
    "kiosk": "Kiosk",
    "web": "Booking link",
    "website": "Booking link",
    "booking_link": "Booking link",
    "whatsapp": "WhatsApp",
    "excel_import": "Imported",
}

PAYMENT_LABELS = {
    "cash": "Cash",
    "upi": "UPI",
    "card": "Card",
    "pay_at_cafe": "Pay at Cafe",
    "monthly_credit": "Gamer Credit",
    "payment_gateway": "Online (gateway)",
    "hash_wallet": "Hash wallet",
    "cafe_wallet": "Cafe wallet",
    "pass": "Pass",
    "hash_global_pass": "Hash pass",
    "cafe_specific_pass": "Cafe pass",
    "free": "Free",
    "upi_qr": "UPI QR",
}

PAID = {"completed", "settled", "paid", "done"}
DUE = {"pending", "unpaid", "due"}


def source_label(source_channel, payment_use_case=None):
    source = str(source_channel or "").strip().lower()
    use = str(payment_use_case or "").strip().lower()
    label = SOURCE_LABELS.get(source, source.replace("_", " ").title() if source else "Unknown")
    if use == "pay_at_cafe" and source == "app":
        return "Hash app · Pay at Cafe"
    if use in {"pass", "hash_global_pass", "cafe_specific_pass"}:
        return f"{label} · Pass"
    return label


def payment_label(payment_use_case, mode_of_payment=None):
    use = str(payment_use_case or "").strip().lower()
    if use in PAYMENT_LABELS:
        return PAYMENT_LABELS[use]
    mode = str(mode_of_payment or "").strip().lower()
    return PAYMENT_LABELS.get(mode, mode.replace("_", " ").title() if mode else "Not recorded")


def payment_state(transactions):
    """Paid / Due / Part paid over the booking's positive transactions."""
    rows = [t for t in transactions if float(t.get("amount") or 0) > 0]
    if not rows:
        return {"status": "unknown", "label": "No payment recorded", "paid": 0.0, "due": 0.0}
    paid = round(sum(float(t["amount"]) for t in rows if str(t.get("settlement_status") or "").lower() in PAID), 2)
    due = round(sum(float(t["amount"]) for t in rows if str(t.get("settlement_status") or "").lower() in DUE), 2)
    if due and not paid:
        status, label = "due", f"Due ₹{due:,.0f}"
    elif due:
        status, label = "part_paid", f"Part paid · ₹{due:,.0f} due"
    elif paid:
        status, label = "paid", "Paid"
    else:
        status, label = "unverified", "Payment unverified"
    if any(str(t.get("payment_use_case") or "").lower() == "pay_at_cafe" for t in rows) and status == "due":
        label = f"Pay later · ₹{due:,.0f} due"
    return {"status": status, "label": label, "paid": paid, "due": due}


def details_payload(booking, transactions, customer, meals):
    """booking/transactions/customer/meals are plain dicts (see the route)."""
    txs = sorted(transactions, key=lambda t: str(t.get("created_at") or ""))
    first = txs[0] if txs else {}
    squad = booking.get("squad_details") if isinstance(booking.get("squad_details"), dict) else {}
    staff = next((t.get("initiated_by_staff_name") for t in txs if t.get("initiated_by_staff_name")), None)
    role = next((t.get("initiated_by_staff_role") for t in txs if t.get("initiated_by_staff_name")), None)
    total = round(sum(float(t.get("total_with_tax") or t.get("amount") or 0) for t in txs if float(t.get("amount") or 0) > 0), 2)
    return {
        "booking_id": booking["id"],
        "status": booking.get("status"),
        "booking_mode": booking.get("booking_mode"),
        "created_at": booking.get("created_at"),
        "source_channel": first.get("source_channel"),
        "source_label": source_label(first.get("source_channel"), first.get("payment_use_case")),
        "created_by": {"name": staff, "role": role} if staff else None,
        "customer": {k: v for k, v in (customer or {}).items() if v not in (None, "", "N/A")},
        "payment": {
            "method": first.get("payment_use_case") or first.get("mode_of_payment"),
            "method_label": payment_label(first.get("payment_use_case"), first.get("mode_of_payment")),
            "total": total,
            **payment_state(txs),
        },
        "rate_card": squad.get("desk_profile_label") or squad.get("desk_profile") or squad.get("rate_label"),
        "meals": meals,
        "squad_players": int(squad.get("player_count") or squad.get("playerCount") or 1),
    }
