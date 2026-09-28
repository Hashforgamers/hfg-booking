"""Bounded customer lookup across a cafe's complete booking history."""
from sqlalchemy import text


def search_booked_customers(session, vendor_id, query, field, limit):
    columns = {
        "name": "lower(u.name)",
        "phone": "lower(c.phone)",
        "email": "lower(c.email)",
    }
    selected = [columns[field]] if field in columns else list(columns.values())
    # Treat wildcard characters as customer text rather than SQL patterns.
    prefix = query.strip().lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    predicate = " OR ".join(f"{column} LIKE :prefix ESCAPE '!'" for column in selected)
    where_search = f"AND ({predicate})" if prefix else ""
    rows = session.execute(text(f"""
        SELECT u.id, u.name, c.email, c.phone
        FROM users u
        LEFT JOIN contact_info c ON c.parent_id = u.id AND c.parent_type = 'user'
        WHERE EXISTS (
            SELECT 1 FROM transactions t
            WHERE t.vendor_id = :vendor_id AND t.user_id = u.id
        )
        {where_search}
        ORDER BY u.id DESC
        LIMIT :limit
    """), {"vendor_id": int(vendor_id), "prefix": prefix + "%", "limit": max(1, min(int(limit), 25))}).mappings().all()
    return [dict(row) for row in rows]
