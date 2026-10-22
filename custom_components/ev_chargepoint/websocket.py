"""Admin-only invoice downloads and bounded daily ledger reads over HA auth."""

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import callback

from .billing import invoice_html
from .const import DOMAIN


def _runtime(hass, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or getattr(entry, "runtime_data", None) is None:
        connection.send_error(msg["id"], "not_found", "Loaded EV ChargePoint entry not found")
        return None
    return entry.runtime_data


@websocket_api.websocket_command({
    vol.Required("type"): "ev_chargepoint/invoice",
    vol.Required("entry_id"): str,
    vol.Required("period"): vol.Match(r"^\d{4}-(0[1-9]|1[0-2])$"),
})
@websocket_api.require_admin
@callback
def ws_invoice(hass, connection, msg):
    """Render an existing immutable snapshot, never a caller-selected file path."""
    runtime = _runtime(hass, connection, msg)
    if runtime is None:
        return
    invoice = runtime.ledger.data["invoices"].get(msg["period"])
    if invoice is None:
        connection.send_error(msg["id"], "not_found", "Issued invoice not found")
        return
    connection.send_result(msg["id"], {"html": invoice_html(invoice)})


@websocket_api.websocket_command({
    vol.Required("type"): "ev_chargepoint/daily",
    vol.Required("entry_id"): str,
    vol.Required("month"): vol.Match(r"^\d{4}-(0[1-9]|1[0-2])$"),
})
@websocket_api.require_admin
@callback
def ws_daily(hass, connection, msg):
    """One calendar month per request; daily energy costs exclude monthly fee/tax."""
    runtime = _runtime(hass, connection, msg)
    if runtime is None:
        return
    days = {
        day: dict(bucket)
        for day, bucket in runtime.ledger.data.get("days", {}).items()
        if day.startswith(msg["month"] + "-")
    }
    connection.send_result(msg["id"], {"days": days, "historical_backfill": False})


@callback
def async_register(hass):
    """Register once, independently of entry reloads."""
    key = DOMAIN + "_reporting_registered"
    if hass.data.get(key):
        return
    websocket_api.async_register_command(hass, ws_invoice)
    websocket_api.async_register_command(hass, ws_daily)
    hass.data[key] = True
