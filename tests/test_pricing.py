"""Reference pricing never substitutes unknown readings with zero."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
package = ModuleType("pricing_test")
package.__path__ = [str(ROOT)]
spec = importlib.util.spec_from_file_location("pricing_test.pricing", ROOT / "pricing.py")
pricing = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"pricing_test": package}):
    spec.loader.exec_module(pricing)


class PricingTests(unittest.TestCase):
    def test_units_and_unknown_states(self):
        for value, unit, expected in [("0.2783", "AUD/kWh", "0.2783"),
                                      ("0", "AUD/kWh", "0"),
                                      ("unknown", "AUD/kWh", None),
                                      ("NaN", "AUD/kWh", None),
                                      ("27.83", "c/kWh", None)]:
            state = SimpleNamespace(state=value, attributes={"unit_of_measurement": unit},
                                    last_updated=datetime(2026, 10, 23, tzinfo=timezone.utc))
            hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: state))
            config = {"agl_rate_sensor": "sensor.rate", "rate": "0.08"}
            result = pricing.pricing_snapshot(hass, config)
            self.assertEqual(result["unit_rate"]["value"], expected)
            self.assertEqual(config["rate"], "0.08")
            self.assertFalse(result["supply_charge"]["available"])

    def test_missing_sensor(self):
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: None))
        result = pricing.pricing_snapshot(hass, {"agl_rate_sensor": "sensor.missing"})
        self.assertIsNone(result["unit_rate"]["value"])
        self.assertIsNone(result["unit_rate"]["updated_at"])
