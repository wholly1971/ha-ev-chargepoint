"""Billing acceptance cases runnable without Home Assistant."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
spec = importlib.util.spec_from_file_location("billing", ROOT / "billing.py")
billing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(billing)
spec = importlib.util.spec_from_file_location("const", ROOT / "const.py")
const = importlib.util.module_from_spec(spec)
spec.loader.exec_module(const)


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.config = {**const.DEFAULTS, "customer": "Customer", "seller": "Seller"}
        self.zone = timezone.utc
        self.now = datetime(2026, 1, 15, tzinfo=timezone.utc)
        self.ledger = billing.Ledger()

    def advance(self, now, watts=Decimal("7200"), fresh=True):
        self.ledger.advance(now, watts, self.config, self.zone, fresh)

    def test_power_to_energy(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(hours=1))
        self.assertAlmostEqual(float(self.ledger.data["months"]["2026-01"]["kwh"]), 7.2)
        self.assertEqual(self.ledger.totals("2026-01"), ("2.16", "0.00", "2.16"))

    def test_overnight_schedule(self):
        self.config.update(schedule_mode="window", start_time="22:00:00", end_time="06:00:00")
        self.advance(self.now.replace(hour=21))
        self.advance(self.now.replace(hour=7) + timedelta(days=1))
        self.assertAlmostEqual(float(self.ledger.data["months"]["2026-01"]["kwh"]), 57.6)

    def test_end_exclusive(self):
        self.config.update(schedule_mode="window", start_time="22:00:00", end_time="06:00:00")
        self.assertTrue(billing.in_window(self.now.replace(hour=22), self.config))
        self.assertFalse(billing.in_window(self.now.replace(hour=6), self.config))

    def test_month_boundary_split(self):
        self.advance(datetime(2026, 1, 31, 23, 30, tzinfo=timezone.utc))
        self.advance(datetime(2026, 2, 1, 0, 30, tzinfo=timezone.utc))
        for period in ("2026-01", "2026-02"):
            self.assertAlmostEqual(float(self.ledger.data["months"][period]["kwh"]), 3.6)

    def test_tariff_changes_prospectively(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(hours=1))
        self.config["rate"] = "0.50"
        self.advance(self.now + timedelta(hours=2))
        self.assertEqual(self.ledger.totals("2026-01")[2], "5.76")

    def test_fixed_fee_tax_rounding(self):
        self.config.update(fixed_fee="1.00", tax_percent="10")
        self.advance(self.now)
        self.advance(self.now + timedelta(hours=1))
        self.assertEqual(self.ledger.totals("2026-01"), ("3.16", "0.32", "3.48"))

    def test_restart_marks_gap(self):
        self.advance(self.now)
        self.ledger = billing.Ledger(deepcopy(self.ledger.data))
        self.advance(self.now + timedelta(hours=1))
        bucket = self.ledger.data["months"]["2026-01"]
        self.assertEqual(bucket["kwh"], "0")
        self.assertEqual(bucket["gap_seconds"], 3600)

    def test_stale_data_not_billed(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(minutes=1), fresh=False)
        self.assertEqual(self.ledger.data["months"]["2026-01"]["gap_seconds"], 60)
        self.assertEqual(self.ledger.data["months"]["2026-01"]["kwh"], "0")

    def test_unavailable_recovery_does_not_bridge_gap(self):
        self.advance(self.now, watts=None)
        self.advance(self.now + timedelta(minutes=1))
        self.assertEqual(self.ledger.data["months"]["2026-01"]["gap_seconds"], 60)

    def test_partial_month_requires_approval(self):
        self.advance(self.now)
        with self.assertRaises(ValueError):
            self.ledger.issue("2026-01", "2026-02", "id", self.now)

    def test_current_month_cannot_be_issued(self):
        self.advance(self.now)
        with self.assertRaises(ValueError):
            self.ledger.issue("2026-01", "2026-01", "id", self.now, True)

    def test_invoice_is_idempotent_and_snapshot_immutable(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(hours=1))
        invoice = self.ledger.issue("2026-01", "2026-02", "id", self.now, True)
        snapshot = deepcopy(invoice)
        self.config["rate"] = "99"
        again = self.ledger.issue("2026-01", "2026-02", "id", self.now, True)
        self.assertEqual(again, snapshot)
        self.assertEqual(self.ledger.data["delivery"]["2026-01"], "pending")

    def test_invoice_keeps_previous_month_settings(self):
        self.advance(datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc))
        self.advance(datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.config["fixed_fee"] = "500"
        self.advance(datetime(2026, 2, 1, 0, 1, tzinfo=timezone.utc))
        invoice = self.ledger.issue("2026-01", "2026-02", "id", self.now, True)
        self.assertEqual(invoice["settings"]["fixed_fee"], "0.00")

    def test_dst_fallback_counts_real_elapsed_time(self):
        self.zone = ZoneInfo("Australia/Sydney")
        self.config.update(schedule_mode="window", start_time="01:00:00", end_time="04:00:00")
        self.advance(datetime(2026, 4, 4, 14, tzinfo=timezone.utc))
        self.advance(datetime(2026, 4, 4, 18, tzinfo=timezone.utc))
        self.assertAlmostEqual(float(self.ledger.data["months"]["2026-04"]["kwh"]), 28.8)

    def test_html_escapes_customer_details(self):
        self.config["customer"] = "<script>bad()</script>"
        self.advance(self.now)
        invoice = self.ledger.issue("2026-01", "2026-02", "id", self.now, True)
        self.assertNotIn("<script>", billing.invoice_html(invoice))
        self.assertIn("&lt;script&gt;", billing.invoice_html(invoice))

    def test_nonfinite_money_rejected(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(ValueError):
                billing.decimal(value)

    def test_duplicate_tick_does_not_double_count(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(hours=1))
        snapshot = deepcopy(self.ledger.data)
        self.advance(self.now + timedelta(hours=1))
        self.assertEqual(self.ledger.data, snapshot)

    def test_bands_split_costs_and_bill_outside_schedule(self):
        self.config.update(use_tariff_bands=True, billing_scope="all_time", rate="0.40",
                           schedule_mode="window", start_time="00:01:00", end_time="05:59:00",
                           tariff_ev_night_enabled=True, tariff_ev_night_start="00:00:00",
                           tariff_ev_night_end="06:00:00", tariff_ev_night_rate="0.08",
                           tariff_peak_enabled=True, tariff_peak_start="06:00:00",
                           tariff_peak_end="09:00:00", tariff_peak_rate="0.30")
        self.advance(self.now.replace(hour=5), Decimal("1000"))
        self.advance(self.now.replace(hour=7), Decimal("1000"))
        bucket = self.ledger.data["months"]["2026-01"]
        self.assertAlmostEqual(float(bucket["kwh"]), 2)
        self.assertAlmostEqual(float(bucket["tariffs"]["ev_night"]["kwh"]), 1)
        self.assertAlmostEqual(float(bucket["tariffs"]["peak"]["kwh"]), 1)
        self.assertAlmostEqual(float(bucket["tariffs"]["peak"]["outside_schedule_kwh"]), 1)
        self.assertEqual(self.ledger.totals("2026-01")[2], "0.38")
        invoice = self.ledger.issue("2026-01", "2026-02", "id", self.now, True)
        self.assertIn("EV Night", billing.invoice_text(invoice))
        self.assertIn("Peak", billing.invoice_text(invoice))
        self.assertIn("Outside charging schedule", billing.invoice_text(invoice))

    def test_uncovered_band_uses_default_and_tracks_fallback(self):
        self.config.update(use_tariff_bands=True, billing_scope="all_time", rate="0.40",
                           tariff_peak_enabled=True, tariff_peak_start="16:00:00",
                           tariff_peak_end="20:00:00", tariff_peak_rate="0.30")
        self.config["_tariff_rates"] = {"peak": {"rate": "0.30", "source": "fallback"}}
        self.advance(self.now.replace(hour=15), Decimal("1000"))
        self.advance(self.now.replace(hour=17), Decimal("1000"))
        bucket = self.ledger.data["months"]["2026-01"]
        self.assertEqual(self.ledger.totals("2026-01")[2], "0.70")
        self.assertAlmostEqual(float(bucket["tariffs"]["peak"]["fallback_kwh"]), 1)
        self.assertAlmostEqual(float(bucket["tariffs"]["default"]["kwh"]), 1)
        self.assertNotIn("_tariff_rates", bucket["settings"])

    def test_overnight_tariff_end_is_exclusive(self):
        config = {**self.config, "use_tariff_bands": True, "tariff_ev_night_enabled": True,
                  "tariff_ev_night_start": "22:00:00", "tariff_ev_night_end": "06:00:00",
                  "tariff_ev_night_rate": "0.08"}
        for hour, expected in [(21, "default"), (22, "ev_night"), (5, "ev_night"), (6, "default")]:
            self.assertEqual(billing.tariff_at(self.now.replace(hour=hour), config)[0], expected)

    def test_legacy_consumption_is_kept_when_band_reporting_starts(self):
        self.advance(self.now, Decimal("1000"))
        self.advance(self.now + timedelta(hours=1), Decimal("1000"))
        bucket = self.ledger.data["months"]["2026-01"]
        bucket.pop("tariffs")
        self.advance(self.now + timedelta(hours=2), Decimal("1000"))
        invoice = self.ledger.issue("2026-01", "2026-02", "id", self.now, True)
        self.assertEqual(invoice["total"], "0.60")
        self.assertIn("Legacy recorded energy", billing.invoice_text(invoice))
        snapshot = deepcopy(invoice)
        bucket["tariffs"]["default"]["kwh"] = "999"
        self.assertEqual(invoice, snapshot)

    def test_legacy_schedule_scope_still_excludes_outside_usage(self):
        self.config.update(schedule_mode="window", start_time="01:00:00", end_time="02:00:00",
                           billing_scope="scheduled")
        self.advance(self.now.replace(hour=3))
        self.advance(self.now.replace(hour=4))
        self.assertEqual(self.ledger.data["months"]["2026-01"]["kwh"], "0")

    def test_issued_daily_details_and_layout_are_immutable(self):
        self.config['invoice_billing_option'] = 'daily'
        self.advance(self.now, Decimal('1000'))
        self.advance(self.now + timedelta(hours=1), Decimal('1000'))
        invoice = self.ledger.issue('2026-01', '2026-02', 'id', self.now, True)
        before = deepcopy(invoice)
        self.ledger.data['days'][self.now.strftime('%Y-%m-%d')]['kwh'] = '999'
        self.ledger.data['months']['2026-01']['settings']['invoice_billing_option'] = 'monthly_total'
        self.assertEqual(invoice, before)
        self.assertEqual(invoice['settings']['invoice_billing_option'], 'daily')

    def test_layout_at_issue_applies_to_unissued_period_only(self):
        self.advance(self.now, Decimal('1000'))
        self.advance(self.now + timedelta(hours=1), Decimal('1000'))
        invoice = self.ledger.issue('2026-01', '2026-02', 'id', self.now, True,
                                    invoice_billing_option='monthly_total')
        self.assertEqual(invoice['settings']['invoice_billing_option'], 'monthly_total')
        self.assertEqual(invoice['total'], '0.30')
        repeated = self.ledger.issue('2026-01', '2026-02', 'id', self.now, True,
                                     invoice_billing_option='daily')
        self.assertEqual(repeated, invoice)
        self.assertEqual(repeated['settings']['invoice_billing_option'], 'monthly_total')
