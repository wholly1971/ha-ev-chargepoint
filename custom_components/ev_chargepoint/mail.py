"""Direct SMTP transport; no Home Assistant notification entity required."""

from email.message import EmailMessage
from email.utils import parseaddr
import smtplib
import ssl

from .billing import invoice_html, invoice_text
from .branding import logo_bytes


def smtp_settings(config):
    """Resolve Gmail's server preset without changing stored configuration."""
    resolved = dict(config)
    if resolved.get("smtp_provider") == "gmail":
        resolved.update(smtp_host="smtp.gmail.com", smtp_port=587, smtp_security="starttls")
        resolved["smtp_password"] = resolved.get("smtp_password", "").replace(" ", "")
        if not resolved.get("smtp_sender"):
            resolved["smtp_sender"] = resolved.get("smtp_username", "")
    return resolved


def validate_mail(config, recipient=None):
    """Validate transport settings without connecting or sending mail."""
    config = smtp_settings(config)
    if config.get("smtp_provider") == "none":
        raise ValueError("Email delivery is disabled")
    if config.get("smtp_provider") == "gmail" and (
        not config.get("smtp_username") or not config.get("smtp_password")
    ):
        raise ValueError("Gmail requires a username and Google app password")
    if not config.get("smtp_host", "").strip():
        raise ValueError("SMTP host is required")
    if not 1 <= int(config.get("smtp_port", 587)) <= 65535:
        raise ValueError("Invalid SMTP port")
    if config.get("smtp_security", "starttls") not in ("starttls", "tls"):
        raise ValueError("Choose STARTTLS or TLS")
    for address in (config.get("smtp_sender", ""), recipient or config.get("customer_email", "")):
        if "\r" in address or "\n" in address:
            raise ValueError("Invalid email address")
        _, parsed = parseaddr(address)
        if parsed != address or "@" not in parsed or not all(parsed.rsplit("@", 1)):
            raise ValueError("Enter a plain email address")


def send_invoice(config, invoice):
    """Blocking SMTP operation: caller must run in an executor."""
    config = smtp_settings(config)
    recipient = invoice["settings"].get("customer_email")
    if not recipient:
        raise ValueError("Invoice has no customer email address")
    validate_mail(config, recipient)
    message = EmailMessage()
    message["Subject"] = f"EV ChargePoint invoice {invoice['number']}"
    message["From"] = config["smtp_sender"]
    message["To"] = recipient
    message.set_content(invoice_text(invoice))
    message.add_alternative(
        invoice_html(invoice, logo_src="cid:ev-chargepoint-logo"), subtype="html"
    )
    message.get_payload()[-1].add_related(
        logo_bytes(),
        maintype="image",
        subtype="png",
        cid="<ev-chargepoint-logo>",
        disposition="inline",
        filename="ev-chargepoint-logo.png",
    )
    context = ssl.create_default_context()
    security = config.get("smtp_security", "starttls")
    kwargs = {"host": config["smtp_host"], "port": int(config.get("smtp_port", 587)), "timeout": 30}
    if security == "tls":
        connection = smtplib.SMTP_SSL(**kwargs, context=context)
    else:
        connection = smtplib.SMTP(**kwargs)
    with connection as smtp:
        smtp.ehlo()
        if security == "starttls":
            smtp.starttls(context=context)
            smtp.ehlo()
        if config.get("smtp_username"):
            smtp.login(config["smtp_username"], config.get("smtp_password", ""))
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
