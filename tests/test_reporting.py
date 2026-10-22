"""Pure accounting/reporting regressions for the dashboard upgrade."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


billing, reporting, const = load("billing"), load("reporting"), load("const")


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.config = {**const.DEFAULTS, "customer": "PRIVATE", "seller": "PRIVATE"}
        self.zone = ZoneInfo("Australia/Brisbane")
        self.start = datetime(2026, 10, 21, 23, 30, tzinfo=self.zone)
        self.ledger = billing.Ledger()

    def test_daily_splits_at_local_midnight_and_preserves_money(self):
        self.ledger.advance(self.start, Decimal("2000"), self.config, self.zone)
        self.ledger.advance(self.start + timedelta(hours=1), Decimal("2000"), self.config, self.zone)
        for day in ("2026-10-21", "2026-10-22"):
            self.assertAlmostEqual(Decimal(self.ledger.data["days"][day]["kwh"]), Decimal(1))
            self.assertAlmostEqual(Decimal(self.ledger.data["days"][day]["energy_cost"]), Decimal("0.30"))
        self.assertEqual(self.ledger.totals("2026-10")[2], "0.60")

    def test_gap_is_not_zero_consumption(self):
        self.ledger.advance(self.start, None, self.config, self.zone)
        self.ledger.advance(self.start + timedelta(minutes=10), None, self.config, self.zone)
        day = self.ledger.data["days"]["2026-10-21"]
        self.assertEqual(day["gap_seconds"], 600)
        self.assertEqual(day["kwh"], "0")

    def test_old_ledger_migration_does_not_invent_history(self):
        old = {"cursor": None, "months": {}, "invoices": {}, "delivery": {}}
        migrated = billing.Ledger(deepcopy(old))
        self.assertEqual(migrated.data["days"], {})
        self.assertEqual(migrated.data["months"], {})

    def test_summary_has_totals_without_private_settings(self):
        self.ledger.advance(self.start, Decimal("2000"), self.config, self.zone)
        self.ledger.advance(self.start + timedelta(hours=1), Decimal("2000"), self.config, self.zone)
        self.ledger.issue("2026-10", "2026-11", "test", self.start, approve=True)
        summary = reporting.ledger_summary(self.ledger)
        self.assertEqual(summary["months"]["2026-10"]["total"], "0.60")
        self.assertEqual(summary["invoices"]["2026-10"]["total"], "0.60")
        self.assertNotIn("PRIVATE", str(summary))
        self.assertNotIn("settings", str(summary))

    def test_invoice_snapshot_does_not_change_when_day_reporting_is_added(self):
        self.ledger.advance(self.start, Decimal("2000"), self.config, self.zone)
        original = deepcopy(self.ledger.issue("2026-10", "2026-11", "test", self.start, approve=True))
        self.ledger.advance(datetime(2026, 11, 1, tzinfo=timezone.utc), None, self.config, self.zone)
        self.assertEqual(self.ledger.data["invoices"]["2026-10"], original)
