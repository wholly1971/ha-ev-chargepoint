"""Smoke checks against real Home Assistant, run by the Linux CI job."""

import importlib.util
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("homeassistant"), "Home Assistant is not installed locally"
)
class HomeAssistantInterfaceTests(unittest.TestCase):
    def test_connected_gmail_requires_authorization_before_automatic_email(self):
        from types import SimpleNamespace
        from custom_components.ev_chargepoint.config_flow import validate, ConfigValidationError
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {**DEFAULTS, "power_sensor": "sensor.ev_power", "smtp_provider": "gmail_oauth",
                  "auto_email": True, "customer_email": "customer@example.com"}
        hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _: SimpleNamespace(attributes={"unit_of_measurement": "W"})),
            config_entries=SimpleNamespace(async_entries=lambda _: []),
        )
        with self.assertRaises(ConfigValidationError) as caught:
            validate(hass, values)
        self.assertEqual(caught.exception.field, "auto_email")

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

    def test_reporting_commands_register_once(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from custom_components.ev_chargepoint.websocket import async_register

        hass = SimpleNamespace(data={})
        with patch("homeassistant.components.websocket_api.async_register_command") as register:
            async_register(hass)
            async_register(hass)
        self.assertEqual(register.call_count, 2)

    def test_no_email_setup_does_not_require_server_or_recipient(self):
        from types import SimpleNamespace
        from custom_components.ev_chargepoint.config_flow import validate
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {
            **DEFAULTS,
            "power_sensor": "sensor.ev_power",
            "smtp_provider": "none",
            "auto_email": True,
        }
        hass = SimpleNamespace(
            states=SimpleNamespace(
                get=lambda _: SimpleNamespace(attributes={"unit_of_measurement": "W"})
            ),
            config_entries=SimpleNamespace(async_entries=lambda _: []),
        )
        validate(hass, values)
        self.assertFalse(values["auto_email"])

    def test_schedule_picker_seconds_are_normalized_on_edit(self):
        from types import SimpleNamespace
        from custom_components.ev_chargepoint.config_flow import schema, validate
        from custom_components.ev_chargepoint.const import DEFAULTS

        existing = {**DEFAULTS, "power_sensor": "sensor.ev_power"}
        entry = SimpleNamespace(entry_id="existing", options=existing, data={})
        hass = SimpleNamespace(
            states=SimpleNamespace(
                get=lambda _: SimpleNamespace(attributes={"unit_of_measurement": "W"})
            ),
            config_entries=SimpleNamespace(
                async_entries=lambda _: [entry], async_get_entry=lambda _: entry
            ),
        )
        for start, end in [("22:30:47", "06:15:12"), ("22:30", "06:15:00")]:
            with self.subTest(start=start, end=end):
                values = schema(existing)({
                    **existing, "schedule_mode": "window", "start_time": start, "end_time": end,
                })
                validate(hass, values, entry.entry_id)
                self.assertEqual(values["start_time"], "22:30:00")
                self.assertEqual(values["end_time"], "06:15:00")
                self.assertEqual(values["schedule_mode"], "window")

    def test_options_flow_reports_the_failing_field(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch
        from custom_components.ev_chargepoint.config_flow import EVBillingOptionsFlow
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {**DEFAULTS, "power_sensor": "sensor.missing"}
        entry = SimpleNamespace(entry_id="existing", options=values, data={})
        flow = EVBillingOptionsFlow()
        flow.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _: None),
            config_entries=SimpleNamespace(async_entries=lambda _: []),
        )
        with patch.object(EVBillingOptionsFlow, "config_entry", new=entry):
            result = asyncio.run(flow.async_step_init({**values, "schedule_mode": "window"}))
        self.assertEqual(result["errors"], {"power_sensor": "invalid_power_sensor"})

