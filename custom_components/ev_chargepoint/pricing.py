"""Optional AGL/Haggle reference prices; never mutate invoice tariffs."""

from decimal import InvalidOperation

from .billing import decimal

PRICE_SOURCES = {
    "unit_rate": ("agl_rate_sensor", "AUD/kWh"),
    "supply_charge": ("agl_supply_sensor", "AUD/day"),
    "feed_in_rate": ("agl_feed_in_sensor", "AUD/kWh"),
}


def pricing_snapshot(hass, config):
    """Expose unavailable data explicitly, retaining source units and timestamp."""
    result = {}
    for kind, (key, unit) in PRICE_SOURCES.items():
        entity_id = config.get(key)
        state = hass.states.get(entity_id) if entity_id else None
        value = None
        if state is not None and state.attributes.get("unit_of_measurement") == unit:
            try:
                value = str(decimal(state.state))
            except (ValueError, TypeError, InvalidOperation):
                pass
        result[kind] = {"entity_id": entity_id, "value": value, "unit": unit,
                        "available": value is not None,
                        "updated_at": state.last_updated.isoformat() if state else None}
    return result
