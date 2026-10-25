"""Pure billing rules. No Home Assistant dependency or floating point money."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy
from html import escape

ZERO = Decimal("0")
INVOICE_LAYOUT_LABELS = {"itemised": "Itemised tariff charging", "daily": "Combined daily charges",
                         "monthly_tariffs": "Monthly tariff totals", "monthly_total": "Monthly total"}


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

    def issue(self, period, current_period, entry_id, issued_at, approve=False, *, invoice_billing_option=None):
        if period >= current_period:
            raise ValueError("Only completed calendar months can be invoiced")
        if period in self.data["invoices"]:
            return self.data["invoices"][period]
        if invoice_billing_option is not None and invoice_billing_option not in INVOICE_LAYOUT_LABELS:
            raise ValueError("Invalid invoice billing option")
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
            "days": deepcopy({day: value for day, value in self.data.get("days", {}).items()
                              if day.startswith(period + "-")}),
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "gap_seconds": bucket["gap_seconds"],
            "partial": bucket["partial"],
            "approved_incomplete": bool(approve),
        }
        if invoice_billing_option is not None:
            invoice["settings"]["invoice_billing_option"] = invoice_billing_option
        self.data["invoices"][period] = invoice
        self.data["delivery"][period] = "pending"
        return invoice


def _tariff_items(lines, tariffs):
    """Unrounded presentation rows; keep rate changes and legacy remainders."""
    rows, tagged = [], {}
    for band, item in tariffs.items():
        for rate, kwh in item["lines"].items():
            quantity = decimal(kwh)
            tagged[rate] = tagged.get(rate, ZERO) + quantity
            if quantity:
                rows.append({"band": band, "description": item["name"], "quantity": quantity,
                             "rate": decimal(rate), "amount": quantity * decimal(rate)})
    for rate, kwh in lines.items():
        quantity = decimal(kwh) - tagged.get(rate, ZERO)
        if quantity:
            rows.append({"band": "legacy" if tariffs else "energy",
                         "description": "Legacy recorded charging" if tariffs else "EV charging",
                         "quantity": quantity, "rate": decimal(rate), "amount": quantity * decimal(rate)})
    return rows


def invoice_items(invoice):
    """Select a snapshot's display grouping without repricing or changing totals."""
    mode = invoice["settings"].get("invoice_billing_option", "itemised")
    monthly = _tariff_items(invoice["lines"], invoice.get("tariffs", {}))
    quantity = sum((row["quantity"] for row in monthly), ZERO)
    amount = sum((row["amount"] for row in monthly), ZERO)
    if mode == "monthly_total":
        return [{"description": "Monthly EV charging - " + invoice["period"],
                 "quantity": quantity, "rate": None, "amount": amount}]
    if mode == "monthly_tariffs":
        groups = {}
        for row in monthly:
            group = groups.setdefault(row["band"], {"description": row["description"], "quantity": ZERO,
                                                     "rate": None, "amount": ZERO})
            group["quantity"] += row["quantity"]
            group["amount"] += row["amount"]
        return list(groups.values())
    days = {day: value for day, value in invoice.get("days", {}).items()
            if day.startswith(invoice["period"] + "-")}
    if not days:
        # Old snapshots have monthly evidence only. Never infer dates/sessions.
        return monthly if mode != "daily" else [{"description": "Recorded charging without daily detail",
                                                  "quantity": quantity, "rate": None, "amount": amount}]
    rows = []
    for day, bucket in sorted(days.items()):
        kwh, cost = decimal(bucket["kwh"]), decimal(bucket["energy_cost"])
        if not kwh and not cost:
            continue
        if mode == "daily":
            rows.append({"description": day + " - Combined tariffs", "quantity": kwh, "rate": None, "amount": cost})
        else:
            day_lines = {}
            for band in bucket.get("tariffs", {}).values():
                for rate, energy in band["lines"].items():
                    day_lines[rate] = str(decimal(day_lines.get(rate, "0")) + decimal(energy))
            items = _tariff_items(day_lines, bucket.get("tariffs", {}))
            for row in items:
                row["description"] = day + " - " + row["description"]
            rows.extend(items)
            missing_kwh = kwh - sum((row["quantity"] for row in items), ZERO)
            missing_cost = cost - sum((row["amount"] for row in items), ZERO)
            if abs(missing_kwh) > Decimal("1e-18") or abs(missing_cost) > Decimal("1e-18"):
                rows.append({"description": day + " - Recorded charging without tariff detail",
                             "quantity": missing_kwh, "rate": None, "amount": missing_cost})
    remainder_kwh = quantity - sum((row["quantity"] for row in rows), ZERO)
    remainder_cost = amount - sum((row["amount"] for row in rows), ZERO)
    if abs(remainder_kwh) > Decimal("1e-18") or abs(remainder_cost) > Decimal("1e-18"):
        rows.append({"description": "Recorded charging without daily detail", "quantity": remainder_kwh,
                     "rate": None, "amount": remainder_cost})
    return rows


def invoice_text(invoice):
    config = invoice["settings"]
    lines = [
        "EV CHARGEPOINT INVOICE",
        invoice["number"],
        f"Issued: {invoice['issued_at']}",
        f"Billing month: {invoice['period']}",
        f"Seller: {config['seller']}",
        f"Customer: {config['customer']}",
        f"Invoice layout: {INVOICE_LAYOUT_LABELS.get(config.get('invoice_billing_option', 'itemised'), 'Itemised tariff charging')}",
        "",
    ]
    for row in invoice_items(invoice):
        rate = f" @ {row['rate']:f} {config['currency']}/kWh" if row['rate'] is not None else " (combined rates)"
        lines.append(f"{row['description']}: {row['quantity']:.6f} kWh{rate} = {money(row['amount'])} {config['currency']}")
    for item in invoice.get("tariffs", {}).values():
        if decimal(item.get("outside_schedule_kwh", "0")):
            lines.append(f"{item['name']} - Outside charging schedule: {decimal(item['outside_schedule_kwh']):.6f} kWh (included above)")
        if decimal(item.get("fallback_kwh", "0")):
            lines.append(f"{item['name']} - Manual fallback used: {decimal(item['fallback_kwh']):.6f} kWh (included above)")
    for item in _tariff_items(invoice["lines"], invoice.get("tariffs", {})):
        if item["band"] == "legacy":
            lines.append(f"Legacy recorded energy: {item['quantity']:.6f} kWh (included above; original rate retained)")
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
