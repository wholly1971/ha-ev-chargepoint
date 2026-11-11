"""Pure billing rules. No Home Assistant dependency or floating point money."""

from datetime import datetime, timedelta, timezone
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
from copy import deepcopy
from html import escape

ZERO = Decimal("0")
INVOICE_LAYOUT_LABELS = {"itemised": "Itemised tariff charging", "daily": "Combined daily charges",
                         "monthly_tariffs": "Tariff totals for billing period", "monthly_total": "Billing period total"}


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


def net_amount(config, key):
    """Extract included GST once; all stored price lines remain tax-exclusive."""
    value = decimal(config.get(key, "0"))
    if config.get(key + "_includes_gst", False):
        value /= 1 + decimal(config["tax_percent"]) / 100
    return value


def tax_bases(bucket):
    """Old unissued energy retains its recorded period's previous tax treatment."""
    if "tax_bases" in bucket:
        return dict(bucket["tax_bases"])
    cost = sum((decimal(rate) * decimal(kwh) for rate, kwh in bucket["lines"].items()), ZERO)
    return {f"{decimal(bucket['settings']['tax_percent']).normalize():f}": str(cost)} if cost else {}


def tax_summary(bucket):
    config = bucket["settings"]
    bases = {rate: decimal(value) for rate, value in tax_bases(bucket).items()}
    rate = f"{decimal(config['tax_percent']).normalize():f}"
    if "fee_tax_bases" in bucket:
        for fee_rate, value in bucket["fee_tax_bases"].items():
            bases[fee_rate] = bases.get(fee_rate, ZERO) + decimal(value)
    else:
        bases[rate] = bases.get(rate, ZERO) + net_amount(config, "fixed_fee")
    return {rate: money(value * decimal(rate) / 100) for rate, value in bases.items() if value}


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
                return band, name, str(resolved["rate"] if "rate" in resolved else net_amount(config, prefix + "rate")), resolved.get("source", "manual")
    return "default", "Default rate", str(net_amount(config, "rate")), "manual"


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
        self._prepare_cycles(now, config, zone)
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
                if "cycles" in self.data:
                    self._cycle_interval(cursor, stop, config, zone, valid_previous)
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
                        bucket.setdefault("tax_bases", tax_bases(bucket))
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
                            tax_rate = f"{decimal(config['tax_percent']).normalize():f}"
                            bucket["tax_bases"][tax_rate] = str(decimal(bucket["tax_bases"].get(tax_rate, "0")) + energy * decimal(rate))
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

    def _prepare_cycles(self, now, config, zone):
        """Opt in prospectively; preserve the unbilled monthly remainder once."""
        mode = config.get("billing_period", "monthly")
        if "cycles" not in self.data and mode == "monthly":
            return
        if "cycles" not in self.data:
            start = datetime.fromisoformat(self.data["cursor"]) if self.data["cursor"] else now
            month = start.astimezone(zone).strftime("%Y-%m")
            self.data.update(cycles={}, active_cycle=None, cycle_mode=mode, cycle_cutover_month=month)
            old = self.data["months"].get(month)
            if old and month not in self.data["invoices"]:
                key = "transition-" + month
                bucket = deepcopy(old)
                bucket.update(start=start.astimezone(zone).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(),
                              end=start.astimezone(zone).isoformat(), closed=True, mode="monthly", days=deepcopy({
                                  day: value for day, value in self.data["days"].items() if day.startswith(month + "-")}))
                # Monthly fee accrued to the cutover only, not a second full fee.
                elapsed = decimal((start - datetime.fromisoformat(bucket["start"])).total_seconds())
                bucket["settings"]["fixed_fee"] = str(net_amount(old["settings"], "fixed_fee") * elapsed / self._month_seconds(start, zone))
                bucket["settings"]["fixed_fee_includes_gst"] = False
                self.data["cycles"][key] = bucket
        if mode != self.data["cycle_mode"]:
            key = self.data["active_cycle"]
            if key:
                self.data["cycles"][key]["closed"] = True
                self.data["cycles"][key]["end"] = (datetime.fromisoformat(self.data["cursor"]) if self.data["cursor"] else now).astimezone(zone).isoformat()
            self.data.update(active_cycle=None, cycle_mode=mode)

    @staticmethod
    def _month_seconds(now, zone):
        local = now.astimezone(zone)
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return decimal((end.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds())

    @staticmethod
    def _calendar_cycle(now, mode, zone):
        local = now.astimezone(zone)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if mode == "weekly":
            start -= timedelta(days=start.weekday())
            end = start + timedelta(days=7)
        elif mode == "monthly":
            start = start.replace(day=1)
            end = start + timedelta(days=monthrange(start.year, start.month)[1])
        else:
            end = start + timedelta(days=1)
        return start, end

    def _new_cycle(self, start, end, config, mode, partial=False):
        key = mode + "-" + start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.data["cycles"][key] = {
            "start": start.isoformat(), "end": end.isoformat(), "closed": False, "mode": mode,
            "kwh": "0", "lines": {}, "tax_bases": {}, "fee_tax_bases": {}, "fee_net": "0",
            "gap_seconds": 0, "partial": partial, "settings": billing_settings(config), "days": {},
        }
        self.data["active_cycle"] = key
        return key

    def _cycle_interval(self, start, stop, config, zone, valid):
        mode = self.data["cycle_mode"]
        key = self.data["active_cycle"]
        bucket = self.data["cycles"].get(key)
        if mode != "each_charge":
            _, end = self._calendar_cycle(start, mode, zone)
            if bucket and start >= datetime.fromisoformat(bucket["end"]):
                bucket["closed"] = True
                bucket = None
            if bucket is None:
                key = self._new_cycle(start.astimezone(zone), end, config, mode, False)
                bucket = self.data["cycles"][key]
        else:
            active = valid and self.watts is not None and self.watts >= decimal(config.get("session_power_threshold", 100))
            if bucket is None:
                if not active:
                    return
                key = self._new_cycle(start.astimezone(zone), stop.astimezone(zone), config, mode, False)
                bucket = self.data["cycles"][key]
            if active:
                bucket.pop("idle_since", None)
            elif valid and self.watts is not None:
                bucket.setdefault("idle_since", start.isoformat())
            else:
                # Unknown power is not proof of a completed charge.
                bucket.pop("idle_since", None)
            bucket["end"] = stop.astimezone(zone).isoformat()
        seconds = decimal((stop - start).total_seconds())
        local = start.astimezone(zone)
        daily = bucket["days"].setdefault(local.strftime("%Y-%m-%d"), {"kwh": "0", "energy_cost": "0", "gap_seconds": 0})
        allowed = config.get("billing_scope") == "all_time" or in_window(local, config)
        if allowed:
            if self.watts is None or not valid:
                bucket["gap_seconds"] += float(seconds)
                daily["gap_seconds"] += float(seconds)
            else:
                energy = self.watts * seconds / Decimal("3600000")
                band, name, rate, source = tariff_at(local, config)
                cost = energy * decimal(rate)
                bucket["kwh"] = str(decimal(bucket["kwh"]) + energy)
                bucket["lines"][rate] = str(decimal(bucket["lines"].get(rate, 0)) + energy)
                daily["kwh"] = str(decimal(daily["kwh"]) + energy)
                daily["energy_cost"] = str(decimal(daily["energy_cost"]) + cost)
                tax = f"{decimal(config['tax_percent']).normalize():f}"
                bucket["tax_bases"][tax] = str(decimal(bucket["tax_bases"].get(tax, 0)) + cost)
                for target in (bucket, daily):
                    add_tariff(target, band, name, rate, energy, source, not in_window(local, config))
        if mode != "each_charge":
            fee = net_amount(config, "fixed_fee") * seconds / self._month_seconds(start, zone)
            bucket["fee_net"] = str(decimal(bucket["fee_net"]) + fee)
            tax = f"{decimal(config['tax_percent']).normalize():f}"
            bucket["fee_tax_bases"][tax] = str(decimal(bucket["fee_tax_bases"].get(tax, 0)) + fee)
        bucket["settings"] = billing_settings(config)
        bucket["settings"].update(fixed_fee=bucket["fee_net"], fixed_fee_includes_gst=False)
        if mode == "each_charge":
            idle = bucket.get("idle_since")
            finished = idle and (stop - datetime.fromisoformat(idle)).total_seconds() >= config.get("session_idle_minutes", 5) * 60
        else:
            finished = stop >= datetime.fromisoformat(bucket["end"])
        if finished:
            bucket["closed"] = True
            self.data["active_cycle"] = None

    def issue_cycle(self, key, entry_id, now, approve=False, *, invoice_billing_option="itemised"):
        """Reuse immutable invoice/delivery rules for a closed non-overlapping cycle."""
        if key in self.data["invoices"]:
            return self.data["invoices"][key]
        bucket = self.data["cycles"][key]
        if not bucket["closed"]:
            raise ValueError("Billing period is still open")
        if not decimal(bucket["kwh"]) and not net_amount(bucket["settings"], "fixed_fee"):
            return None
        # Existing accounting and coverage checks apply to every cadence.
        temporary = Ledger({"cursor": None, "months": {"0000-00": bucket}, "invoices": {},
                            "delivery": {}, "days": {}})
        invoice = temporary.issue("0000-00", "9999-99", entry_id, now, approve,
                                  invoice_billing_option=invoice_billing_option)
        invoice.update(number=f"EV-{entry_id}-{key}", period=key, billing_period=bucket["mode"],
                       period_start=bucket["start"], period_end=bucket["end"], days=deepcopy(bucket["days"]))
        self.data["invoices"][key] = invoice
        self.data["delivery"][key] = "pending"
        return invoice

    def totals(self, period):
        bucket = self.data["months"][period]
        config = bucket["settings"]
        energy_cost = sum(
            (decimal(rate) * decimal(kwh) for rate, kwh in bucket["lines"].items()), ZERO
        )
        subtotal = decimal(money(energy_cost + net_amount(config, "fixed_fee")))
        if "tax_bases" not in bucket:
            tax = decimal(money(subtotal * decimal(config["tax_percent"]) / 100))
        else:
            tax = sum((decimal(value) for value in tax_summary(bucket).values()), ZERO)
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
            "tax_breakdown": tax_summary(bucket),
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
        return [{"description": "EV charging - " + period_label(invoice),
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
            if invoice.get("period_start") or day.startswith(invoice["period"] + "-")}
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


def period_label(invoice):
    if invoice.get("period_start"):
        start = datetime.fromisoformat(invoice['period_start'])
        end = datetime.fromisoformat(invoice['period_end'])
        return f"{start:%d %b %Y %H:%M %z} to {end:%d %b %Y %H:%M %z} (end exclusive)"
    return invoice["period"]


def invoice_text(invoice):
    config = invoice["settings"]
    lines = [
        "EV CHARGEPOINT INVOICE",
        invoice["number"],
        f"Issued: {invoice['issued_at']}",
        f"Billing period: {period_label(invoice)}",
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
            f"Fixed fee (excluding GST): {money(net_amount(config, 'fixed_fee'))}",
            f"Subtotal: {invoice['subtotal']}",
            f"GST included in total: {invoice['tax']}",
            f"TOTAL: {invoice['total']} {config['currency']}",
            "",
            config["payment_instructions"],
        ]
    )
    if invoice["partial"] or invoice["gap_seconds"]:
        lines.append(f"Approved incomplete period. Missing data: {invoice['gap_seconds']} seconds.")
    if invoice.get("tax_breakdown"):
        lines.append("GST breakdown: " + "; ".join(f"{rate}%: {amount} {config['currency']}" for rate, amount in invoice["tax_breakdown"].items()))
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
