"""Dashboard-safe ledger summaries; never publish customer or SMTP settings."""


def ledger_summary(ledger):
    """Keep only accounting totals and coverage in entity state attributes."""
    data = ledger.data
    return {
        "invoice_delivery": dict(data["delivery"]),
        "months": {
            period: {
                "gap_seconds": bucket["gap_seconds"],
                "partial": bucket["partial"],
                "kwh": bucket["kwh"],
                "subtotal": ledger.totals(period)[0],
                "tax": ledger.totals(period)[1],
                "total": ledger.totals(period)[2],
                "currency": bucket["settings"]["currency"],
                "invoice_number": data["invoices"].get(period, {}).get("number"),
            }
            for period, bucket in data["months"].items()
        },
        "invoices": {
            period: {
                key: invoice[key]
                for key in ("number", "period", "issued_at", "kwh", "total", "partial")
            } | {"currency": invoice["settings"]["currency"]}
            for period, invoice in data["invoices"].items()
        },
    }
