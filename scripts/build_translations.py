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
    "email_entity": "SMTP customer recipient (optional)",
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
    "invalid_config": "Check the W/kW sensor, unique sensor/switch assignment, selected switch/SMTP recipient, three-letter currency, nonnegative rates, tax (0–100), and whole-minute schedule times. Currency cannot change on an existing account."
}
step = {
    "title": "EV charging and billing",
    "data": labels,
    "description": "Configure one customer and dedicated EV power sensor. Billing uses calendar months in your Home Assistant timezone. SMTP recipients are configured in the SMTP integration. Switch control and automatic email are optional.",
}
translation = {
    "title": "EV ChargePoint",
    "config": {"step": {"user": step}, "error": error},
    "options": {"step": {"init": step}, "error": error},
    "selector": {
        "schedule_mode": {"options": {"all_day": "All day", "window": "Daily time window"}}
    },
}
root = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
(root / "translations").mkdir(exist_ok=True)
for path in (root / "strings.json", root / "translations" / "en.json"):
    path.write_text(json.dumps(translation, indent=2) + "\n", encoding="utf-8")
