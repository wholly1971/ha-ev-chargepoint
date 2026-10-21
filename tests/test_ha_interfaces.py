"""Smoke checks against real Home Assistant, run by the Linux CI job."""

import importlib.util
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("homeassistant"), "Home Assistant is not installed locally"
)
class HomeAssistantInterfaceTests(unittest.TestCase):
    def test_config_schema_accepts_selections(self):
        from custom_components.ev_chargepoint.config_flow import schema
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {
            **DEFAULTS,
            "power_sensor": "sensor.ev_power",
            "charger_switch": "switch.charger",
            "customer_email": "customer@example.com",
            "customer": "Customer",
            "seller": "Seller",
        }
        self.assertEqual(schema(values)(values), values)

    def test_optional_entities_can_be_omitted(self):
        from custom_components.ev_chargepoint.config_flow import schema
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {**DEFAULTS, "power_sensor": "sensor.ev_power"}
        self.assertEqual(schema(values)(values), values)

    def test_platform_modules_import(self):
        from custom_components.ev_chargepoint import button, sensor

        self.assertTrue(callable(button.async_setup_entry))
        self.assertTrue(callable(sensor.async_setup_entry))
