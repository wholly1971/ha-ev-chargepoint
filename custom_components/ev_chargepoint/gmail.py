"""Reuse Home Assistant Google Mail authorization, without copying its tokens."""

from email.utils import parseaddr
from email.message import EmailMessage
from base64 import urlsafe_b64encode

from homeassistant.util import slugify
from homeassistant.exceptions import HomeAssistantError

from .billing import invoice_html, invoice_text
from .pdf_invoice import invoice_pdf, invoice_filename


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
    resolve_gmail(hass, config.get("gmail_account", ""))
    # Native notify only sends MIMEText (no attachments). Reuse the loaded
    # account's authorized client without reading/copying OAuth tokens.
    entries = list(hass.config_entries.async_entries("google_mail"))
    selected = config.get("gmail_account", "")
    entry = next((entry for entry in entries if entry.entry_id == selected), None) if selected else entries[0]
    auth = getattr(entry, "runtime_data", None)
    if auth is None or not callable(getattr(auth, "get_resource", None)):
        raise HomeAssistantError("Connected Gmail PDF client is unavailable; reconnect Google Mail")
    try:
        message = EmailMessage()
        message["To"] = recipient
        message["From"] = "me"
        message["Subject"] = f"EV ChargePoint invoice {invoice['number']}"
        message.set_content(invoice_text(invoice))
        message.add_alternative(invoice_html(invoice), subtype="html")
        pdf = await hass.async_add_executor_job(invoice_pdf, invoice)
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=invoice_filename(invoice))
        resource = await auth.get_resource()
        raw = urlsafe_b64encode(message.as_bytes()).decode("ascii")
        request = resource.users().messages().send(userId="me", body={"raw": raw})
        await hass.async_add_executor_job(request.execute)
    except Exception as err:
        raise HomeAssistantError("Google Mail PDF submission failed; review before retrying") from err


async def async_send_test_email(hass, config):
    """Send one explicit test using the configured account and recipient."""
    recipient = config.get("customer_email", "")
    validate_recipient(recipient)
    service = resolve_gmail(hass, config.get("gmail_account", ""))
    await _async_submit(hass, service, recipient, "EV ChargePoint test email",
                        "<p>EV ChargePoint email test successful.</p><p>This is a test message, not an invoice. No charges or billing records were created.</p>")


async def _async_submit(hass, service, recipient, title, message):
    try:
        await hass.services.async_call(
            "notify", service,
            {
                "title": title,
                "message": message,
                "target": [recipient],
                "data": {"send": True},
            },
            blocking=True,
        )
    except Exception as err:
        # Google API/auth exceptions are not all HomeAssistantError subclasses.
        # Normalize only this external-service boundary; cancellation still propagates.
        raise HomeAssistantError("Google Mail submission failed; review before retrying") from err
