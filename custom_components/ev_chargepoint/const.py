"""Constants for EV ChargePoint."""

DOMAIN = "ev_chargepoint"
DEFAULTS = {
    "name": "EV charging",
    "currency": "AUD",
    "rate": "0.30",
    "rate_includes_gst": False,
    "fixed_fee_includes_gst": False,
    "fixed_fee": "0.00",
    "tax_percent": "0",
    "schedule_mode": "all_day",
    "start_time": "22:00:00",
    "end_time": "06:00:00",
    "control_switch": False,
    "auto_email": False,
    "max_age": 300,
    "seller": "",
    "customer": "",
    "payment_instructions": "",
    "smtp_host": "",
    "smtp_provider": "none",
    "gmail_account": "",
    "smtp_port": 587,
    "smtp_security": "starttls",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_sender": "",
    "customer_email": "",
    "invoice_billing_option": "itemised",
}

INVOICE_BILLING_OPTIONS = ("itemised", "daily", "monthly_tariffs", "monthly_total")

TARIFF_BANDS = {"peak": "Peak", "off_peak": "Off Peak", "shoulder_1": "Shoulder 1",
                "shoulder_2": "Shoulder 2", "ev_night": "EV Night"}
DEFAULTS.update(use_tariff_bands=False, billing_scope="scheduled", sensor_rate_tax_percent="10")
for band in TARIFF_BANDS:
    DEFAULTS.update({f"tariff_{band}_enabled": False, f"tariff_{band}_start": "00:00:00",
                     f"tariff_{band}_end": "00:00:00", f"tariff_{band}_rate": "0",
                     f"tariff_{band}_sensor_includes_tax": True, f"tariff_{band}_rate_includes_gst": False})
