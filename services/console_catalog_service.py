from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import time
from threading import Lock

from db.extensions import db
from models.consoleCatalog import ConsoleCatalog
from models.vendorConsoleOverride import VendorConsoleOverride


DEFAULT_CONSOLE_CATALOG: List[Dict[str, Any]] = [
    {
        "slug": "pc",
        "display_name": "PC",
        "family": "computer",
        "icon": "Monitor",
        "input_mode": "keyboard_mouse",
        "supports_multiplayer": True,
        "default_capacity": 10,
        "controller_policy": "none",
        "is_active": True,
    },
    {
        "slug": "playstation",
        "display_name": "PlayStation",
        "family": "console",
        "icon": "Tv",
        "input_mode": "controller",
        "supports_multiplayer": True,
        "default_capacity": 4,
        "controller_policy": "per_player",
        "is_active": True,
    },
    {
        "slug": "xbox",
        "display_name": "Xbox",
        "family": "console",
        "icon": "Gamepad2",
        "input_mode": "controller",
        "supports_multiplayer": True,
        "default_capacity": 4,
        "controller_policy": "per_player",
        "is_active": True,
    },
    {
        "slug": "vr_headset",
        "display_name": "VR Headset",
        "family": "immersive",
        "icon": "Headset",
        "input_mode": "motion",
        "supports_multiplayer": False,
        "default_capacity": 1,
        "controller_policy": "none",
        "is_active": True,
    },
    {
        "slug": "nintendo_switch",
        "display_name": "Nintendo Switch",
        "family": "console",
        "icon": "Gamepad2",
        "input_mode": "controller",
        "supports_multiplayer": True,
        "default_capacity": 4,
        "controller_policy": "per_player",
        "is_active": True,
    },
    {
        "slug": "steam_deck",
        "display_name": "Steam Deck",
        "family": "handheld",
        "icon": "Gamepad2",
        "input_mode": "hybrid",
        "supports_multiplayer": True,
        "default_capacity": 2,
        "controller_policy": "optional",
        "is_active": True,
    },
    {
        "slug": "arcade_cabinet",
        "display_name": "Arcade Cabinet",
        "family": "arcade",
        "icon": "Gamepad2",
        "input_mode": "joystick",
        "supports_multiplayer": True,
        "default_capacity": 2,
        "controller_policy": "none",
        "is_active": True,
    },
    {
        "slug": "racing_rig",
        "display_name": "Racing Rig",
        "family": "simulator",
        "icon": "Joystick",
        "input_mode": "wheel",
        "supports_multiplayer": False,
        "default_capacity": 1,
        "controller_policy": "none",
        "is_active": True,
    },
    {
        "slug": "simulator",
        "display_name": "Simulator",
        "family": "simulator",
        "icon": "Rocket",
        "input_mode": "specialized",
        "supports_multiplayer": False,
        "default_capacity": 1,
        "controller_policy": "none",
        "is_active": True,
    },
    {
        "slug": "private_room",
        "display_name": "Private Room",
        "family": "zone",
        "icon": "DoorOpen",
        "input_mode": "room",
        "supports_multiplayer": True,
        "default_capacity": 8,
        "controller_policy": "none",
        "is_active": True,
    },
    {
        "slug": "vip_room",
        "display_name": "VIP Room",
        "family": "zone",
        "icon": "Crown",
        "input_mode": "room",
        "supports_multiplayer": True,
        "default_capacity": 10,
        "controller_policy": "none",
        "is_active": True,
    },
    {
        "slug": "bootcamp_room",
        "display_name": "Bootcamp Room",
        "family": "zone",
        "icon": "Users",
        "input_mode": "room",
        "supports_multiplayer": True,
        "default_capacity": 12,
        "controller_policy": "none",
        "is_active": True,
    },
]

LEGACY_CONSOLE_ALIAS: Dict[str, str] = {
    "pc": "pc",
    "computer": "pc",
    "gaming_pc": "pc",
    "ps": "playstation",
    "ps4": "playstation",
    "ps5": "playstation",
    "playstation": "playstation",
    "play_station": "playstation",
    "sony": "playstation",
    "xbox": "xbox",
    "x_box": "xbox",
    "vr": "vr_headset",
    "virtual_reality": "vr_headset",
    "virtual": "vr_headset",
    "reality": "vr_headset",
    "private_room": "private_room",
    "privatezone": "private_room",
    "private_zone": "private_room",
    "vip_room": "vip_room",
    "vipzone": "vip_room",
    "vip_zone": "vip_room",
    "bootcamp_room": "bootcamp_room",
    "bootcamp": "bootcamp_room",
    "room": "private_room",
}

_CATALOG_MERGE_CACHE: Dict[str, Dict[str, Any]] = {}
_CATALOG_MERGE_CACHE_LOCK = Lock()
_CATALOG_MERGE_CACHE_TTL_SEC = 300
_DEFAULT_CATALOG_SEEDED = False
_DEFAULT_CATALOG_SEEDED_LOCK = Lock()


def _slugify(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def normalize_console_slug(raw: Any) -> str:
    slug = _slugify(raw)
    if not slug:
        return ""
    return LEGACY_CONSOLE_ALIAS.get(slug, slug)


def ensure_default_console_catalog_seed() -> None:
    global _DEFAULT_CATALOG_SEEDED
    with _DEFAULT_CATALOG_SEEDED_LOCK:
        if _DEFAULT_CATALOG_SEEDED:
            return
    try:
        existing = {row.slug for row in ConsoleCatalog.query.with_entities(ConsoleCatalog.slug).all()}
        missing = [entry for entry in DEFAULT_CONSOLE_CATALOG if entry["slug"] not in existing]
        if not missing:
            with _DEFAULT_CATALOG_SEEDED_LOCK:
                _DEFAULT_CATALOG_SEEDED = True
            return

        for entry in missing:
            db.session.add(ConsoleCatalog(**entry))
        db.session.commit()
        with _DEFAULT_CATALOG_SEEDED_LOCK:
            _DEFAULT_CATALOG_SEEDED = True
    except Exception:
        db.session.rollback()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "slug": row.slug,
        "display_name": row.display_name,
        "family": row.family,
        "icon": row.icon,
        "input_mode": row.input_mode,
        "supports_multiplayer": bool(row.supports_multiplayer),
        "default_capacity": int(row.default_capacity or 1),
        "controller_policy": row.controller_policy,
        "is_active": bool(row.is_active),
    }


def get_merged_console_catalog(vendor_id: Optional[int] = None, include_inactive: bool = False) -> List[Dict[str, Any]]:
    cache_key = f"{int(vendor_id) if vendor_id is not None else 0}:{int(include_inactive)}"
    now_ts = time.time()
    with _CATALOG_MERGE_CACHE_LOCK:
        cached = _CATALOG_MERGE_CACHE.get(cache_key)
        if cached and float(cached.get("expires_at", 0)) > now_ts:
            return cached["payload"]

    ensure_default_console_catalog_seed()

    q = ConsoleCatalog.query
    if not include_inactive:
        q = q.filter(ConsoleCatalog.is_active.is_(True))

    merged: Dict[str, Dict[str, Any]] = {}
    for row in q.order_by(ConsoleCatalog.display_name.asc()).all():
        item = _row_to_dict(row)
        item["source"] = "global"
        merged[item["slug"]] = item

    if vendor_id is None:
        payload = sorted(merged.values(), key=lambda x: str(x.get("display_name") or x["slug"]).lower())
        with _CATALOG_MERGE_CACHE_LOCK:
            _CATALOG_MERGE_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + _CATALOG_MERGE_CACHE_TTL_SEC}
        return payload

    override_q = VendorConsoleOverride.query.filter(VendorConsoleOverride.vendor_id == int(vendor_id))
    if not include_inactive:
        override_q = override_q.filter(VendorConsoleOverride.is_active.is_(True))

    for override in override_q.all():
        base_slug = normalize_console_slug(override.slug)
        if not base_slug and override.console_catalog_id:
            base_row = ConsoleCatalog.query.get(int(override.console_catalog_id))
            base_slug = normalize_console_slug(base_row.slug if base_row else "")
        if not base_slug and override.display_name:
            base_slug = normalize_console_slug(override.display_name)
        if not base_slug:
            continue

        base = merged.get(base_slug, {
            "id": None,
            "slug": base_slug,
            "display_name": base_slug.replace("_", " ").title(),
            "family": "other",
            "icon": "Monitor",
            "input_mode": "controller",
            "supports_multiplayer": False,
            "default_capacity": 1,
            "controller_policy": "none",
            "is_active": True,
            "source": "vendor_override",
        })

        merged[base_slug] = {
            "id": base.get("id"),
            "slug": base_slug,
            "display_name": override.display_name or base.get("display_name"),
            "family": override.family or base.get("family"),
            "icon": override.icon or base.get("icon"),
            "input_mode": override.input_mode or base.get("input_mode"),
            "supports_multiplayer": bool(
                override.supports_multiplayer
                if override.supports_multiplayer is not None
                else base.get("supports_multiplayer")
            ),
            "default_capacity": int(
                override.default_capacity
                if override.default_capacity is not None
                else base.get("default_capacity") or 1
            ),
            "controller_policy": override.controller_policy or base.get("controller_policy"),
            "is_active": bool(override.is_active),
            "source": "vendor_override",
        }

    payload = sorted(merged.values(), key=lambda x: str(x.get("display_name") or x["slug"]).lower())
    with _CATALOG_MERGE_CACHE_LOCK:
        _CATALOG_MERGE_CACHE[cache_key] = {"payload": payload, "expires_at": now_ts + _CATALOG_MERGE_CACHE_TTL_SEC}
    return payload


def resolve_console_capabilities(vendor_id: Optional[int], raw_console: Any) -> Dict[str, Any]:
    slug = normalize_console_slug(raw_console)
    if not slug:
        return {
            "slug": "unknown",
            "display_name": "Unknown",
            "family": "other",
            "icon": "Monitor",
            "input_mode": "controller",
            "supports_multiplayer": False,
            "default_capacity": 1,
            "controller_policy": "none",
            "is_active": True,
            "source": "derived",
        }

    merged = get_merged_console_catalog(vendor_id=vendor_id)
    for item in merged:
        if item.get("slug") == slug:
            return item

    return {
        "slug": slug,
        "display_name": slug.replace("_", " ").title(),
        "family": "other",
        "icon": "Monitor",
        "input_mode": "controller",
        "supports_multiplayer": False,
        "default_capacity": 1,
        "controller_policy": "none",
        "is_active": True,
        "source": "derived",
    }


def legacy_console_group(slug: str, capabilities: Optional[Dict[str, Any]] = None) -> str:
    normalized = normalize_console_slug(slug)
    caps = capabilities or {}

    if normalized == "playstation":
        return "ps"
    if normalized == "xbox":
        return "xbox"
    if normalized in {"vr_headset", "simulator"}:
        return "vr"
    if normalized == "pc":
        return "pc"
    if normalized in {"private_room", "vip_room", "bootcamp_room"}:
        return "zone"

    input_mode = str(caps.get("input_mode") or "").lower()
    controller_policy = str(caps.get("controller_policy") or "").lower()
    supports_multiplayer = bool(caps.get("supports_multiplayer"))

    if input_mode in {"keyboard_mouse", "hybrid"}:
        return "pc"
    if controller_policy in {"per_player", "controller_pricing", "optional"} and supports_multiplayer:
        return "xbox"
    if input_mode in {"motion", "wheel", "specialized"}:
        return "vr"
    if input_mode == "room" or str(caps.get("family") or "").lower() == "zone":
        return "zone"

    return "unknown"


def _override_to_dict(row: VendorConsoleOverride) -> Dict[str, Any]:
    return {
        "id": int(row.id),
        "vendor_id": int(row.vendor_id),
        "console_catalog_id": int(row.console_catalog_id) if row.console_catalog_id is not None else None,
        "slug": normalize_console_slug(row.slug),
        "display_name": row.display_name,
        "family": row.family,
        "icon": row.icon,
        "input_mode": row.input_mode,
        "supports_multiplayer": row.supports_multiplayer,
        "default_capacity": int(row.default_capacity) if row.default_capacity is not None else None,
        "controller_policy": row.controller_policy,
        "is_active": bool(row.is_active),
    }


def get_vendor_console_overrides(vendor_id: int, include_inactive: bool = False) -> List[Dict[str, Any]]:
    query = VendorConsoleOverride.query.filter(VendorConsoleOverride.vendor_id == int(vendor_id))
    if not include_inactive:
        query = query.filter(VendorConsoleOverride.is_active.is_(True))
    return [_override_to_dict(row) for row in query.order_by(VendorConsoleOverride.id.asc()).all()]


def upsert_vendor_console_override(vendor_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    base_slug = normalize_console_slug(payload.get("slug") or payload.get("display_name"))
    if not base_slug:
        raise ValueError("slug or display_name is required")

    display_name = str(payload.get("display_name") or "").strip() or base_slug.replace("_", " ").title()
    family = str(payload.get("family") or "").strip() or None
    icon = str(payload.get("icon") or "").strip() or None
    input_mode = str(payload.get("input_mode") or "").strip() or None
    controller_policy = str(payload.get("controller_policy") or "").strip() or None

    supports_multiplayer = payload.get("supports_multiplayer")
    if supports_multiplayer is not None:
        supports_multiplayer = bool(supports_multiplayer)

    default_capacity = payload.get("default_capacity")
    if default_capacity is not None:
        try:
            default_capacity = max(1, int(default_capacity))
        except Exception as exc:
            raise ValueError("default_capacity must be a valid integer") from exc

    catalog_row = ConsoleCatalog.query.filter(ConsoleCatalog.slug == base_slug).first()
    override = VendorConsoleOverride.query.filter(
        VendorConsoleOverride.vendor_id == int(vendor_id),
        VendorConsoleOverride.slug == base_slug,
    ).first()
    if override is None:
        override = VendorConsoleOverride(vendor_id=int(vendor_id), slug=base_slug)
        db.session.add(override)

    override.console_catalog_id = int(catalog_row.id) if catalog_row else None
    override.slug = base_slug
    override.display_name = display_name
    override.family = family
    override.icon = icon
    override.input_mode = input_mode
    override.supports_multiplayer = supports_multiplayer
    override.default_capacity = default_capacity
    override.controller_policy = controller_policy
    override.is_active = bool(payload.get("is_active", True))
    db.session.flush()
    with _CATALOG_MERGE_CACHE_LOCK:
        _CATALOG_MERGE_CACHE.clear()
    return _override_to_dict(override)


def set_vendor_console_override_active(vendor_id: int, slug: str, is_active: bool) -> Optional[Dict[str, Any]]:
    normalized_slug = normalize_console_slug(slug)
    if not normalized_slug:
        return None
    override = VendorConsoleOverride.query.filter(
        VendorConsoleOverride.vendor_id == int(vendor_id),
        VendorConsoleOverride.slug == normalized_slug,
    ).first()
    if override is None:
        return None
    override.is_active = bool(is_active)
    db.session.flush()
    with _CATALOG_MERGE_CACHE_LOCK:
        _CATALOG_MERGE_CACHE.clear()
    return _override_to_dict(override)
