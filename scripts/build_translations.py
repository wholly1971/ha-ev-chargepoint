"""Build identical English config and options labels."""

import json
from pathlib import Path

labels = {
    "name": "Installation name",
    "customer": "Customer name and billing details",
    "seller": "Seller name, address and tax details",
    "payment_instructions": "Payment instructions and due terms",
    "power_sensor": "Dedicated EV power sensor (W or kW)",
    "charger_switch": "Charger control switch (optional)",
    "smtp_host": "SMTP server hostname",
    "smtp_provider": "Email provider",
    "smtp_port": "SMTP server port",
    "smtp_security": "SMTP connection security",
    "smtp_username": "SMTP login username (optional)",
    "smtp_password": "SMTP password (for Gmail, use a Google app password)",
    "smtp_sender": "Sender email address",
    "customer_email": "Customer invoice email address",
    "gmail_account": "Connected Gmail sending account",
    "schedule_mode": "Billable schedule",
    "start_time": "Daily start time (inclusive)",
    "end_time": "Daily stop time (exclusive)",
    "control_switch": "Automatically control the charger switch",
    "auto_email": "Automatically email monthly invoices",
    "currency": "Currency code (e.g. AUD)",
    "rate": "Price per kWh, excluding tax",
    "fixed_fee": "Monthly fixed fee, excluding tax",
    "tax_percent": "Tax percentage",
    "max_age": "Maximum power reading age in seconds",
}
error = {
    "invalid_time": "Choose a valid local time. Times are saved to the minute.",
    "invalid_amount": "Enter a nonnegative number (for example 0.08).",
    "invalid_tax": "Enter a tax percentage between 0 and 100.",
    "invalid_currency": "Enter a three-letter currency code, such as AUD.",
    "invalid_power_sensor": "Select an existing power sensor measured in W or kW.",
    "switch_required": "Select a charger switch before enabling automatic control.",
    "invalid_switch": "Select an existing switch or clear the optional switch field.",
    "invalid_email": "For connected Gmail, authorize Google Mail, select the account and enter the invoice recipient. For SMTP, complete login and sender settings. Otherwise turn off automatic email.",
    "currency_locked": "Currency cannot change on an existing billing account.",
    "sensor_assigned": "This power sensor is already assigned to another EV ChargePoint account.",
    "switch_assigned": "This switch is already controlled by another EV ChargePoint account.",
    "invalid_config": "Check the W/kW sensor, unique sensor/switch assignment, SMTP server/sender/customer email when automatic email is enabled, three-letter currency, nonnegative rates, tax (0–100), and valid schedule times. Currency cannot change on an existing account."
}
step = {
    "title": "EV charging and billing",
    "data": labels,
    "description": "Configure one customer and dedicated EV power sensor. Choose No email / no SMTP server for local invoices only; leave all server and recipient fields blank. This also disables automatic email and manual retries. For Gmail without SMTP, first connect Google Mail in Home Assistant, select Gmail - connected account, choose your sending account and enter the invoice recipient. The default uses the only connected Gmail account; select explicitly if there are several. SMTP fields are ignored in connected-account mode. Other providers use the settings below. Gmail selects smtp.gmail.com:587 with STARTTLS automatically: enter your Gmail address as username and use a Google app password, not your normal password. Leave sender blank to use the Gmail username. Custom server fields are ignored for Gmail. Switch control and automatic email are optional. Schedule times are saved to the minute; seconds are ignored.",
}
translation = {
    "title": "EV ChargePoint",
    "config": {"step": {"user": step}, "error": error},
    "options": {"step": {"init": step}, "error": error},
    "selector": {
        "smtp_provider": {
            "options": {
                "none": "No email / no SMTP server",
                "custom": "Custom SMTP server",
                "gmail": "Gmail (Google app password)",
                "gmail_oauth": "Gmail - connected account (no SMTP)",
            }
        },
        "schedule_mode": {"options": {"all_day": "All day", "window": "Daily time window"}},
        "smtp_security": {
            "options": {"starttls": "STARTTLS (usually port 587)", "tls": "TLS (usually port 465)"}
        },
    },
}
root = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
(root / "translations").mkdir(exist_ok=True)
for path in (root / "strings.json", root / "translations" / "en.json"):
    path.write_text(json.dumps(translation, indent=2) + "\n", encoding="utf-8")
