"""Build identical English config and options labels."""

import json
from pathlib import Path

labels = {
    "name": "Installation name",
    "use_tariff_bands": "Configure time-based tariff bands",
    "billing_scope": "When to record billable charging",
    "sensor_rate_tax_percent": "Tax included in selected sensor prices (%) — Haggle GST is usually 10",

    "agl_rate_sensor": "AGL / Haggle unit rate sensor (reference only, optional)",
    "agl_supply_sensor": "AGL / Haggle daily supply charge sensor (optional)",
    "agl_feed_in_sensor": "AGL / Haggle solar feed-in rate sensor (optional)",
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
for band, name in {"peak": "Peak", "off_peak": "Off Peak", "shoulder_1": "Shoulder 1", "shoulder_2": "Shoulder 2", "ev_night": "EV Night"}.items():
    for suffix, label in {"enabled": "Enable", "start": "From (inclusive)", "end": "To (exclusive)",
                          "rate": "Manual / fallback rate per kWh, excluding tax",
                          "sensor": "Rate sensor (optional)",
                          "sensor_includes_tax": "Sensor price includes tax"}.items():
        labels["tariff_" + band + "_" + suffix] = name + " — " + label
error = {
    "empty_tariff_window": "Choose different from/to times. Overnight windows are supported.",
    "overlapping_tariffs": "Enabled tariff windows overlap. Use adjacent end/start times; each minute must match at most one band.",
    "invalid_rate_sensor": "Choose a rate sensor with units matching the billing currency, such as AUD/kWh. Unavailable readings use the manual fallback rate.",
    "invalid_time": "Choose a valid local time. Times are saved to the minute.",
    "invalid_amount": "Enter a nonnegative number (for example 0.08).",
    "invalid_tax": "Enter a tax percentage between 0 and 100.",
    "invalid_currency": "Enter a three-letter currency code, such as AUD.",
    "invalid_power_sensor": "Select an existing power sensor measured in W or kW.",
    "switch_required": "Select a charger switch before enabling automatic control.",
    "invalid_switch": "Select an existing switch or clear the optional switch field.",
    "invalid_email_gmail": "Enter your Gmail address as the login username, a Google-generated app password and the invoice recipient. Leave sender blank to use the login address. A connected Gmail account is not required.",
    "invalid_email_gmail_oauth": "Connect Google Mail in Home Assistant, select the sending account and enter the invoice recipient.",
    "invalid_email_custom": "Complete the SMTP server, login, sender and invoice recipient settings.",
    "invalid_email": "For connected Gmail, authorize Google Mail, select the account and enter the invoice recipient. For SMTP, complete login and sender settings. Otherwise turn off automatic email.",
    "currency_locked": "Currency cannot change on an existing billing account.",
    "sensor_assigned": "This power sensor is already assigned to another EV ChargePoint account.",
    "switch_assigned": "This switch is already controlled by another EV ChargePoint account.",
    "invalid_config": "Check the W/kW sensor, unique sensor/switch assignment, SMTP server/sender/customer email when automatic email is enabled, three-letter currency, nonnegative rates, tax (0Ã¢â‚¬â€œ100), and valid schedule times. Currency cannot change on an existing account."
}
step = {
    "title": "EV charging and billing",
    "data": labels,
    "description": "Configure one customer and dedicated EV power sensor. Choose No email / no SMTP server for local invoices only; leave all server and recipient fields blank. This also disables automatic email and manual retries. For Gmail without SMTP, first connect Google Mail in Home Assistant, select Gmail - connected account, choose your sending account and enter the invoice recipient. The default uses the only connected Gmail account; select explicitly if there are several. SMTP fields are ignored in connected-account mode. Other providers use the settings below. Gmail selects smtp.gmail.com:587 with STARTTLS automatically: enter your Gmail address as username and use a Google app password, not your normal password. Leave sender blank to use the Gmail username. Custom server fields are ignored for Gmail. Switch control and automatic email are optional. Schedule times are saved to the minute; seconds are ignored.",
}
email_steps = {
    "tariffs": {"title": "Time-based charge rates", "data": labels,
        "description": "Define Peak, Off Peak, Shoulder 1, Shoulder 2 and EV Night. Enable only bands you use. From is inclusive; To is exclusive; overnight windows are supported. Overlaps are rejected. Uncovered times use the default rate. A selected sensor overrides the manual rate when valid; unavailable/invalid sensors use the manual fallback and are reported. Manual rates exclude tax. Mark tax-inclusive sensor prices (such as Haggle) to remove the included tax before invoice tax is applied. Charging switch control remains separate."},
    "email_gmail": {"title": "Gmail with Google app password", "data": labels,
        "description": "Enter your Gmail address as the login username and paste the 16-character app password generated by Google. Leave sender blank to use the login address. No connected Google Mail account or server settings are needed."},
    "email_gmail_oauth": {"title": "Connected Google Mail account", "data": labels,
        "description": "First authorize Google Mail in Home Assistant. Select that account and enter the invoice recipient. No app password is used here."},
    "email_custom": {"title": "Custom SMTP email", "data": labels,
        "description": "Enter the server, login, sender and invoice recipient supplied by your email provider."},
}
step["description"] = "Configure billing and charging, then choose one email method. The next step shows only settings for that method. No email saves local invoices only. Gmail (Google app password) needs no connected Google Mail account. Schedule times are saved to the minute."
translation = {
    "title": "EV ChargePoint",
    "config": {"step": {"user": step, **email_steps}, "error": error},
    "options": {"step": {"init": step, **email_steps}, "error": error},
    "selector": {
        "billing_scope": {"options": {"scheduled": "Only inside the charging schedule (legacy)", "all_time": "All measured charging, including outside the schedule"}},
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
