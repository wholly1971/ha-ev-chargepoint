"""Resolve selected rate sensors without copying credentials or inferring tariff windows."""

from decimal import InvalidOperation
from .billing import BAND_NAMES, decimal


def resolve_rates(hass, config):
    result = {}
    for band in BAND_NAMES:
        prefix = "tariff_" + band + "_"
        rate = config.get(prefix + "rate", "0")
        entity_id = config.get(prefix + "sensor")
        source = "fallback" if entity_id else "manual"
        state = hass.states.get(entity_id) if entity_id else None
        if state is not None:
            try:
                value = decimal(state.state)
                if state.attributes.get("unit_of_measurement") != config["currency"] + "/kWh" or value < 0:
                    raise ValueError("Invalid rate sensor")
                if config.get(prefix + "sensor_includes_tax", True):
                    value /= 1 + decimal(config.get("sensor_rate_tax_percent", "10")) / 100
                rate, source = str(value), "sensor"
            except (ValueError, TypeError, InvalidOperation):
                pass
        result[band] = {"rate": str(rate), "source": source}
    return result


def tariff_config(hass, config):
    resolved = resolve_rates(hass, config)
    return [{"id": band, "name": name,
             "enabled": bool(config.get("use_tariff_bands") and config.get("tariff_" + band + "_enabled")),
             **{key: config.get("tariff_" + band + "_" + key) for key in ("start", "end", "rate", "sensor", "sensor_includes_tax")},
             "effective_rate": resolved[band]["rate"], "source": resolved[band]["source"]}
            for band, name in BAND_NAMES.items()]
