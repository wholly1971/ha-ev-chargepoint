"""Smoke checks against real Home Assistant, run by the Linux CI job."""

import importlib.util
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("homeassistant"), "Home Assistant is not installed locally"
)
class HomeAssistantInterfaceTests(unittest.TestCase):
    def test_inclusive_prices_require_positive_gst_and_fields_exist(self):
        from types import SimpleNamespace
        from custom_components.ev_chargepoint.config_flow import validate, schema, tariff_schema, ConfigValidationError
        from custom_components.ev_chargepoint.const import DEFAULTS
        values = {**DEFAULTS, 'power_sensor': 'sensor.ev', 'rate_includes_gst': True}
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: SimpleNamespace(attributes={'unit_of_measurement': 'W'})),
                               config_entries=SimpleNamespace(async_entries=lambda _: []))
        with self.assertRaises(ConfigValidationError) as caught:
            validate(hass, values)
        self.assertEqual(caught.exception.code, 'gst_rate_required')
        values['tax_percent'] = '10'
        validate(hass, values)
        self.assertIn('rate_includes_gst', {key.schema for key in schema(values).schema})
        self.assertIn('fixed_fee_includes_gst', {key.schema for key in schema(values).schema})
        self.assertIn('tariff_peak_rate_includes_gst', {key.schema for key in tariff_schema(values).schema})

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
        from custom_components.ev_chargepoint.config_flow import schema, main_values
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {
            **DEFAULTS,
            "power_sensor": "sensor.ev_power",
            "charger_switch": "switch.charger",
            "customer_email": "customer@example.com",
            "customer": "Customer",
            "seller": "Seller",
        }
        self.assertEqual(schema(values)(main_values(values)), main_values(values))

    def test_optional_entities_can_be_omitted(self):
        from custom_components.ev_chargepoint.config_flow import schema, main_values
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {**DEFAULTS, "power_sensor": "sensor.ev_power"}
        self.assertEqual(schema(values)(main_values(values)), main_values(values))

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
        from custom_components.ev_chargepoint.config_flow import schema, validate, main_values
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
                    **main_values(existing), "schedule_mode": "window", "start_time": start, "end_time": end,
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


    def test_email_forms_are_specific_to_provider(self):
        from types import SimpleNamespace
        from custom_components.ev_chargepoint.config_flow import email_schema
        from custom_components.ev_chargepoint.const import DEFAULTS

        hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _: []))
        for provider, expected in (
            ("gmail", {"smtp_username", "smtp_password", "smtp_sender", "customer_email"}),
            ("gmail_oauth", {"gmail_account", "customer_email"}),
            ("custom", {"smtp_host", "smtp_port", "smtp_security", "smtp_username",
                        "smtp_password", "smtp_sender", "customer_email"}),
        ):
            fields = email_schema({**DEFAULTS, "smtp_provider": provider}, hass).schema
            self.assertEqual({key.schema for key in fields}, expected)

    def test_gmail_app_password_flow_ignores_connected_account(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch
        from custom_components.ev_chargepoint.config_flow import EVBillingOptionsFlow, main_values
        from custom_components.ev_chargepoint.const import DEFAULTS

        values = {**DEFAULTS, "power_sensor": "sensor.ev_power", "smtp_provider": "gmail",
                  "auto_email": True, "gmail_account": "disconnected-account"}
        entry = SimpleNamespace(entry_id="existing", options=values, data={})
        flow = EVBillingOptionsFlow()
        flow.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _: SimpleNamespace(attributes={"unit_of_measurement": "W"})),
            config_entries=SimpleNamespace(async_entries=lambda _: [], async_get_entry=lambda _: entry),
        )
        with patch.object(EVBillingOptionsFlow, "config_entry", new=entry):
            result = asyncio.run(flow.async_step_init(main_values(values)))
            self.assertEqual(result["step_id"], "email_gmail")
            result = asyncio.run(flow.async_step_email_gmail({
                "smtp_username": "sender@gmail.com", "smtp_password": "abcd efgh ijkl mnop",
                "smtp_sender": "", "customer_email": "recipient@example.com",
            }))
            self.assertEqual(result["step_id"], "invoice_billing")
            result = asyncio.run(flow.async_step_invoice_billing({"invoice_billing_option": "daily"}))
        self.assertEqual(result["type"], "create_entry")
        self.assertTrue(result["data"]["auto_email"])
        self.assertEqual(result["data"]["smtp_provider"], "gmail")

    def test_gmail_missing_password_has_provider_specific_error(self):
        import asyncio
        from types import SimpleNamespace
        from custom_components.ev_chargepoint.config_flow import EVBillingOptionsFlow
        from custom_components.ev_chargepoint.const import DEFAULTS

        flow = EVBillingOptionsFlow()
        flow._entry_id = None
        flow._values = {**DEFAULTS, "power_sensor": "sensor.ev_power", "smtp_provider": "gmail",
                        "auto_email": True}
        flow.hass = SimpleNamespace(
            states=SimpleNamespace(get=lambda _: SimpleNamespace(attributes={"unit_of_measurement": "W"})),
            config_entries=SimpleNamespace(async_entries=lambda _: []),
        )
        result = asyncio.run(flow.async_step_email_gmail({"smtp_username": "sender@gmail.com",
                                                        "customer_email": "recipient@example.com"}))
        self.assertEqual(result["step_id"], "email_gmail")
        self.assertEqual(result["errors"], {"base": "invalid_email_gmail"})

    def test_test_email_button_routes_only_to_explicit_test(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from custom_components.ev_chargepoint.button import BillingButton

        runtime = SimpleNamespace(async_test_email=AsyncMock(), async_approve=AsyncMock(),
                                  async_retry=AsyncMock())
        entry = SimpleNamespace(entry_id="entry", runtime_data=runtime)
        button = BillingButton(entry, "test_email")
        asyncio.run(button.async_press())
        runtime.async_test_email.assert_awaited_once()
        runtime.async_approve.assert_not_awaited()
        runtime.async_retry.assert_not_awaited()

    def test_tariff_overlaps_rejected_and_adjacent_overnight_allowed(self):
        from types import SimpleNamespace
        from custom_components.ev_chargepoint.config_flow import validate_tariffs, ConfigValidationError
        from custom_components.ev_chargepoint.const import DEFAULTS
        values = {**DEFAULTS, "use_tariff_bands": True, "tariff_peak_enabled": True,
                  "tariff_peak_start": "20:00:00", "tariff_peak_end": "23:00:00",
                  "tariff_ev_night_enabled": True, "tariff_ev_night_start": "22:00:00",
                  "tariff_ev_night_end": "06:00:00"}
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: None))
        with self.assertRaises(ConfigValidationError) as error:
            validate_tariffs(hass, values)
        self.assertEqual(error.exception.code, "overlapping_tariffs")
        values["tariff_ev_night_start"] = "23:00:00"
        validate_tariffs(hass, values)
        values["tariff_peak_end"] = "20:00:00"
        with self.assertRaises(ConfigValidationError) as error:
            validate_tariffs(hass, values)
        self.assertEqual(error.exception.code, "empty_tariff_window")

    def test_options_tariff_step_preserves_schedule_and_email(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch
        from custom_components.ev_chargepoint.config_flow import EVBillingOptionsFlow, main_values, tariff_schema
        from custom_components.ev_chargepoint.const import DEFAULTS
        values = {**DEFAULTS, "power_sensor": "sensor.ev", "use_tariff_bands": True,
                  "billing_scope": "all_time", "schedule_mode": "window",
                  "start_time": "00:01:00", "end_time": "05:59:00", "smtp_provider": "gmail",
                  "smtp_username": "sender@gmail.com", "smtp_password": "test-only",
                  "customer_email": "customer@example.com", "auto_email": True}
        entry = SimpleNamespace(entry_id="existing", options=values, data={})
        flow = EVBillingOptionsFlow()
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: SimpleNamespace(attributes={"unit_of_measurement": "W"})),
            config_entries=SimpleNamespace(async_entries=lambda _: [], async_get_entry=lambda _: entry))
        with patch.object(EVBillingOptionsFlow, "config_entry", new=entry):
            result = asyncio.run(flow.async_step_init(main_values(values)))
            self.assertEqual(result["step_id"], "tariffs")
            inputs = {key.schema: values[key.schema] for key in tariff_schema(values).schema if key.schema in values}
            result = asyncio.run(flow.async_step_tariffs(inputs))
            self.assertEqual(result["step_id"], "email_gmail")
            result = asyncio.run(flow.async_step_email_gmail({}))
            self.assertEqual(result["step_id"], "invoice_billing")
            result = asyncio.run(flow.async_step_invoice_billing({"invoice_billing_option": "monthly_tariffs"}))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["start_time"], "00:01:00")
        self.assertEqual(result["data"]["smtp_password"], "test-only")
        self.assertEqual(result["data"]["billing_scope"], "all_time")

    def test_charging_mode_select_routes_to_runtime(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from custom_components.ev_chargepoint.select import ChargingMode
        runtime = SimpleNamespace(charge_mode="Automatic schedule", override_until=None,
                                  async_set_charge_mode=AsyncMock())
        selector = ChargingMode(SimpleNamespace(entry_id="test", runtime_data=runtime))
        asyncio.run(selector.async_select_option("Manual charging on"))
        runtime.async_set_charge_mode.assert_awaited_once_with("Manual charging on")
        self.assertEqual(selector.current_option, "Automatic schedule")

    def test_current_charge_rate_uses_active_sensor_and_invoice_tax(self):
        from types import SimpleNamespace
        from datetime import datetime, timezone
        from decimal import Decimal
        from custom_components.ev_chargepoint.tariffs import current_charge_rate
        from custom_components.ev_chargepoint.const import DEFAULTS
        config = {**DEFAULTS, "use_tariff_bands": True, "tax_percent": "10",
                  "tariff_peak_enabled": True, "tariff_peak_start": "06:00:00",
                  "tariff_peak_end": "20:00:00", "tariff_peak_rate": "0.40",
                  "tariff_peak_sensor": "sensor.rate", "tariff_peak_sensor_includes_tax": True}
        hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: SimpleNamespace(state="0.33", attributes={"unit_of_measurement":"AUD/kWh"})))
        rate = current_charge_rate(hass, config, datetime(2026,10,25,12,tzinfo=timezone.utc))
        self.assertEqual(rate["name"], "Peak")
        self.assertEqual(Decimal(rate["excluding_tax"]), Decimal("0.3"))
        self.assertEqual(Decimal(rate["including_tax"]), Decimal("0.33"))
        self.assertEqual(rate["source"], "sensor")

    def test_invoice_billing_options_reject_invalid_choice(self):
        import asyncio
        from custom_components.ev_chargepoint.config_flow import EVBillingOptionsFlow
        from custom_components.ev_chargepoint.const import DEFAULTS
        flow = EVBillingOptionsFlow()
        flow._entry_id = "existing"
        flow._values = dict(DEFAULTS)
        result = asyncio.run(flow.async_step_invoice_billing({"invoice_billing_option": "invalid"}))
        self.assertEqual(result["errors"], {"invoice_billing_option": "invalid_invoice_option"})

    def test_no_email_flow_still_configures_invoice_presentation(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch
        from custom_components.ev_chargepoint.config_flow import EVBillingOptionsFlow, main_values
        from custom_components.ev_chargepoint.const import DEFAULTS
        values = {**DEFAULTS, "power_sensor": "sensor.ev", "smtp_provider": "none"}
        entry = SimpleNamespace(entry_id="existing", options=values, data={})
        flow = EVBillingOptionsFlow()
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: SimpleNamespace(attributes={"unit_of_measurement": "W"})),
            config_entries=SimpleNamespace(async_entries=lambda _: [], async_get_entry=lambda _: entry))
        with patch.object(EVBillingOptionsFlow, "config_entry", new=entry):
            result = asyncio.run(flow.async_step_init(main_values(values)))
            self.assertEqual(result["step_id"], "invoice_billing")
            result = asyncio.run(flow.async_step_invoice_billing({"invoice_billing_option": "monthly_total"}))
        self.assertEqual(result["type"], "create_entry")
        self.assertFalse(result["data"]["auto_email"])
        self.assertEqual(result["data"]["invoice_billing_option"], "monthly_total")
