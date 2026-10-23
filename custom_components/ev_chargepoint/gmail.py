"""Reuse Home Assistant Google Mail authorization, without copying its tokens."""

from email.utils import parseaddr

from homeassistant.util import slugify
from homeassistant.exceptions import HomeAssistantError

from .billing import invoice_html


def resolve_gmail(hass, entry_id=""):
    """Default means the sole connected account, never an arbitrary first match."""
    entries = list(hass.config_entries.async_entries("google_mail"))
    if entry_id:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
    if len(entries) != 1:
        raise ValueError("Connect one Google Mail account or select the sending account")
    entry = entries[0]
    service = slugify(entry.title)
    # The native Google Mail integration names its notify action after entry.title.
    # Require it to be registered: an unloaded or unauthorized account cannot send.
    if not hass.services.has_service("notify", service):
        raise ValueError("The selected Google Mail account is not ready; reconnect it")
    return service


def validate_recipient(address):
    """Keep recipient validation independent of SMTP credentials."""
    if not address or "\r" in address or "\n" in address:
        raise ValueError("Enter the customer invoice email address")
    _, parsed = parseaddr(address)
    if parsed != address or "@" not in parsed or not all(parsed.rsplit("@", 1)):
        raise ValueError("Enter a plain customer email address")


async def async_send_invoice(hass, config, invoice):
    """Use the connected account's default From address and immutable recipient."""
    recipient = invoice["settings"].get("customer_email", "")
    validate_recipient(recipient)
    service = resolve_gmail(hass, config.get("gmail_account", ""))
    try:
        await hass.services.async_call(
            "notify", service,
            {
                "title": f"EV ChargePoint invoice {invoice['number']}",
                "message": invoice_html(invoice),
                "target": [recipient],
                "data": {"send": True},
            },
            blocking=True,
        )
    except Exception as err:
        # Google API/auth exceptions are not all HomeAssistantError subclasses.
        # Normalize only this external-service boundary; cancellation still propagates.
        raise HomeAssistantError("Google Mail submission failed; review before retrying") from err
