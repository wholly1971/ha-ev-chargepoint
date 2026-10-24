"""Pure billing rules. No Home Assistant dependency or floating point money."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy
from html import escape

ZERO = Decimal("0")


def billing_settings(config):
    """Never copy SMTP transport settings or credentials into the ledger."""
    return {
        key: value
        for key, value in config.items()
        if not key.startswith(("smtp_", "_")) and key != "email_entity"
    }


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Value must be finite")
    return result


def money(value):
    return str(decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def in_window(now, config):
    if config["schedule_mode"] == "all_day":
        return True
    start = config["start_time"][:5]
    end = config["end_time"][:5]
    current = now.strftime("%H:%M")
    if start == end:
        return True
    return start <= current < end if start < end else current >= start or current < end


BAND_NAMES = {"peak": "Peak", "off_peak": "Off Peak", "shoulder_1": "Shoulder 1",
              "shoulder_2": "Shoulder 2", "ev_night": "EV Night"}


def tariff_at(now, config):
    """Select a validated non-overlapping window; unmatched minutes use the default rate."""
    if config.get("use_tariff_bands"):
        for band, name in BAND_NAMES.items():
            prefix = "tariff_" + band + "_"
            if config.get(prefix + "enabled") and in_window(now, {
                "schedule_mode": "window", "start_time": config[prefix + "start"],
                "end_time": config[prefix + "end"],
            }):
                resolved = config.get("_tariff_rates", {}).get(band, {})
                return band, name, str(resolved.get("rate", config[prefix + "rate"])), resolved.get("source", "manual")
    return "default", "Default rate", str(config["rate"]), "manual"


def add_tariff(target, band, name, rate, energy, source, outside):
    """Keep unrounded band evidence separate from the existing total-by-rate ledger."""
    item = target.setdefault("tariffs", {}).setdefault(band, {
        "name": name, "kwh": "0", "energy_cost": "0", "lines": {},
        "fallback_kwh": "0", "outside_schedule_kwh": "0",
    })
    item["kwh"] = str(decimal(item["kwh"]) + energy)
    item["energy_cost"] = str(decimal(item["energy_cost"]) + energy * decimal(rate))
    item["lines"][rate] = str(decimal(item["lines"].get(rate, "0")) + energy)
    if source == "fallback":
        item["fallback_kwh"] = str(decimal(item["fallback_kwh"]) + energy)
    if outside:
        item["outside_schedule_kwh"] = str(decimal(item["outside_schedule_kwh"]) + energy)


class Ledger:
    """Persisted monthly totals, tariff lines, and immutable invoice snapshots."""

    def __init__(self, data=None):
        self.data = data or {"cursor": None, "months": {}, "invoices": {}, "delivery": {}}
        # Older ledgers have no daily evidence. Do not invent historical buckets.
        self.data.setdefault("days", {})
        self.watts = None  # Never extrapolate consumption across a restart.

    def advance(self, now, watts, config, zone, valid_previous=True):
        previous = self.data["cursor"]
        now = now.astimezone(timezone.utc)
        if previous:
            cursor = datetime.fromisoformat(previous).astimezone(timezone.utc)
            if now <= cursor:
                return
            # Split at every local minute, including schedule and month boundaries.
            # UTC iteration also handles repeated and missing DST hours.
            while cursor < now:
                boundary = cursor.replace(second=0, microsecond=0) + timedelta(minutes=1)
                stop = min(now, boundary)
                local = cursor.astimezone(zone)
                if config.get("billing_scope") == "all_time" or in_window(local, config):
                    period = local.strftime("%Y-%m")
                    bucket = self.data["months"].setdefault(
                        period,
                        {
                            "kwh": "0",
                            "lines": {},
                            "gap_seconds": 0,
                            "partial": False,
                            "settings": billing_settings(config),
                        },
                    )
                    if period not in self.data["invoices"]:
                        seconds = decimal((stop - cursor).total_seconds())
                        day = local.strftime("%Y-%m-%d")
                        daily = self.data["days"].setdefault(
                            day, {"kwh": "0", "energy_cost": "0", "gap_seconds": 0}
                        )
                        if self.watts is None or not valid_previous:
                            bucket["gap_seconds"] += float(seconds)
                            daily["gap_seconds"] += float(seconds)
                        else:
                            energy = self.watts * seconds / Decimal("3600000")
                            band, name, rate, source = tariff_at(local, config)
                            lines = bucket["lines"]
                            lines[rate] = str(decimal(lines.get(rate, "0")) + energy)
                            bucket["kwh"] = str(decimal(bucket["kwh"]) + energy)
                            daily["kwh"] = str(decimal(daily["kwh"]) + energy)
                            daily["energy_cost"] = str(
                                decimal(daily["energy_cost"]) + energy * decimal(rate)
                            )
                            outside = not in_window(local, config)
                            add_tariff(bucket, band, name, rate, energy, source, outside)
                            add_tariff(daily, band, name, rate, energy, source, outside)
                        # Snapshot final settings for this period, not a future month.
                        bucket["settings"] = billing_settings(config)
                cursor = stop
        else:
            period = now.astimezone(zone).strftime("%Y-%m")
            self.data["months"][period] = {
                "kwh": "0",
                "lines": {},
                "gap_seconds": 0,
                "partial": True,
                "settings": billing_settings(config),
            }
        self.data["cursor"] = now.isoformat()
        self.watts = watts

    def totals(self, period):
        bucket = self.data["months"][period]
        config = bucket["settings"]
        energy_cost = sum(
            (decimal(rate) * decimal(kwh) for rate, kwh in bucket["lines"].items()), ZERO
        )
        subtotal = decimal(money(energy_cost + decimal(config["fixed_fee"])))
        tax = decimal(money(subtotal * decimal(config["tax_percent"]) / 100))
        return money(subtotal), money(tax), money(subtotal + tax)

    def issue(self, period, current_period, entry_id, issued_at, approve=False):
        if period >= current_period:
            raise ValueError("Only completed calendar months can be invoiced")
        if period in self.data["invoices"]:
            return self.data["invoices"][period]
        bucket = self.data["months"][period]
        if (bucket["gap_seconds"] or bucket["partial"]) and not approve:
            raise ValueError("Incomplete readings need approval")
        subtotal, tax, total = self.totals(period)
        invoice = {
            "number": f"EV-{entry_id}-{period}",
            "period": period,
            "issued_at": issued_at.isoformat(),
            "kwh": bucket["kwh"],
            "lines": dict(bucket["lines"]),
            "settings": deepcopy(bucket["settings"]),
            "tariffs": deepcopy(bucket.get("tariffs", {})),
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "gap_seconds": bucket["gap_seconds"],
            "partial": bucket["partial"],
            "approved_incomplete": bool(approve),
        }
        self.data["invoices"][period] = invoice
        self.data["delivery"][period] = "pending"
        return invoice


def invoice_text(invoice):
    config = invoice["settings"]
    lines = [
        "EV CHARGEPOINT INVOICE",
        invoice["number"],
        f"Issued: {invoice['issued_at']}",
        f"Billing month: {invoice['period']}",
        f"Seller: {config['seller']}",
        f"Customer: {config['customer']}",
        "",
    ]
    if invoice.get("tariffs"):
        for item in invoice["tariffs"].values():
            lines.append(item["name"])
            for rate, kwh in item["lines"].items():
                lines.append(f"  {decimal(kwh):.6f} kWh @ {rate} {config['currency']}/kWh")
            lines.append(f"  Energy cost: {money(item['energy_cost'])} {config['currency']}")
            if decimal(item.get("fallback_kwh", "0")):
                lines.append(f"  Manual fallback used: {item['fallback_kwh']} kWh")
            if decimal(item.get("outside_schedule_kwh", "0")):
                lines.append(f"  Outside charging schedule: {item['outside_schedule_kwh']} kWh")
        # Pre-upgrade consumption has no band evidence; retain its existing price lines.
        for rate, kwh in invoice["lines"].items():
            tagged = sum((decimal(t["lines"].get(rate, "0")) for t in invoice["tariffs"].values()), ZERO)
            remaining = decimal(kwh) - tagged
            if remaining:
                lines.append(f"Legacy recorded energy: {remaining:.6f} kWh @ {rate} {config['currency']}/kWh")
    else:
        for rate, kwh in invoice["lines"].items():
            lines.append(f"{decimal(kwh):.6f} kWh @ {rate} {config['currency']}/kWh")
    lines.extend(
        [
            f"Monthly fee: {money(config['fixed_fee'])}",
            f"Subtotal: {invoice['subtotal']}",
            f"Tax ({config['tax_percent']}%): {invoice['tax']}",
            f"TOTAL: {invoice['total']} {config['currency']}",
            "",
            config["payment_instructions"],
        ]
    )
    if invoice["partial"] or invoice["gap_seconds"]:
        lines.append(f"Approved incomplete period. Missing data: {invoice['gap_seconds']} seconds.")
    return "\n".join(lines)


def invoice_html(invoice, logo_src=None):
    logo = (
        '<img alt="EV ChargePoint" style="width:240px;max-width:100%;height:auto" src="'
        + escape(logo_src, quote=True)
        + '">'
        if logo_src
        else ""
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>EV charging invoice</title><style>body{font:16px system-ui;"
        "max-width:800px;margin:48px auto;padding:24px}pre{white-space:pre-wrap;"
        "font:inherit;line-height:1.7}</style><body>"
        + logo
        + "<pre>"
        + escape(invoice_text(invoice))
        + "</pre></body></html>"
    )
