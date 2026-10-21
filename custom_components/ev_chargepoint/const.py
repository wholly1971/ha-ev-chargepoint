"""Constants for EV ChargePoint."""

DOMAIN = "ev_chargepoint"
DEFAULTS = {
    "name": "EV charging",
    "currency": "AUD",
    "rate": "0.30",
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
    "smtp_port": 587,
    "smtp_security": "starttls",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_sender": "",
    "customer_email": "",
}
