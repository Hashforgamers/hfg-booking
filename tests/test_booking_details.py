"""Booking details card: how a booking was made and paid (pure helpers)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("booking_details", Path(__file__).resolve().parents[1] / "services/booking_details.py")
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)


def tx(**kw):
    base = {"amount": 100.0, "total_with_tax": 100.0, "settlement_status": "completed", "payment_use_case": "cash",
            "mode_of_payment": "cash", "source_channel": "dashboard", "initiated_by_staff_name": None,
            "initiated_by_staff_role": None, "created_at": "2026-11-28T10:00:00"}
    base.update(kw)
    return base


def test_source_labels():
    assert bd.source_label("dashboard", "cash") == "Walk-in desk"
    assert bd.source_label("app", "pay_at_cafe") == "Hash app · Pay at Cafe"
    assert bd.source_label("kiosk") == "Kiosk"
    assert bd.source_label("app", "hash_global_pass") == "Hash app · Pass"
    assert bd.source_label(None) == "Unknown"


def test_payment_state():
    assert bd.payment_state([tx()])["label"] == "Paid"
    due = bd.payment_state([tx(settlement_status="pending", payment_use_case="pay_at_cafe", amount=150)])
    assert due["status"] == "due" and due["label"] == "Pay later · ₹150 due"
    part = bd.payment_state([tx(), tx(settlement_status="pending", amount=60)])
    assert part["status"] == "part_paid" and part["due"] == 60
    assert bd.payment_state([tx(amount=0)])["status"] == "unknown"


def test_details_payload_hides_empty_and_names_staff():
    out = bd.details_payload(
        {"id": 7, "status": "confirmed", "booking_mode": "regular", "created_at": "2026-11-28T10:00:00+05:30",
         "squad_details": {"desk_profile_label": "1 Hour PC", "player_count": 2}},
        [tx(initiated_by_staff_name="Asha", initiated_by_staff_role="manager", payment_use_case="upi")],
        {"name": "Simran Kaur", "phone": "9876543210", "email": "N/A"},
        [{"name": "Cold coffee", "quantity": 1, "total": 80.0}],
    )
    assert out["customer"] == {"name": "Simran Kaur", "phone": "9876543210"}
    assert out["created_by"] == {"name": "Asha", "role": "manager"}
    assert out["source_label"] == "Walk-in desk"
    assert out["payment"]["method_label"] == "UPI" and out["payment"]["label"] == "Paid"
    assert out["rate_card"] == "1 Hour PC" and out["squad_players"] == 2
