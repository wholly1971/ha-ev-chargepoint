"""Exercise invoice delivery and persistence with Home Assistant boundary doubles.

These tests do not claim to validate a real Home Assistant installation.
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
NOW = datetime(2026, 2, 1, tzinfo=timezone.utc)


class FakeCoordinator:
    def __init__(self, hass, *args, **kwargs):
        self.hass = hass

    def async_set_updated_data(self, data):
        self.data = data


class FakeStore:
    def __init__(self, *args, **kwargs):
        self.snapshots = []

    async def async_save(self, data):
        self.snapshots.append(deepcopy(data))


class HAError(Exception):
    pass


def load_runtime():
    package = ModuleType("ev_test")
    package.__path__ = [str(ROOT)]
    registry = SimpleNamespace(async_get=lambda target: SimpleNamespace(platform="smtp"))
    fake_modules = {
        "ev_test": package,
        "homeassistant": ModuleType("homeassistant"),
        "homeassistant.core": SimpleNamespace(callback=lambda fn: fn),
        "homeassistant.exceptions": SimpleNamespace(HomeAssistantError=HAError),
        "homeassistant.helpers": SimpleNamespace(
            entity_registry=SimpleNamespace(async_get=lambda hass: registry)
        ),
        "homeassistant.helpers.event": SimpleNamespace(
            async_track_state_change_event=lambda *args: lambda: None,
            async_track_time_interval=lambda *args: lambda: None,
        ),
        "homeassistant.helpers.storage": SimpleNamespace(Store=FakeStore),
        "homeassistant.helpers.update_coordinator": SimpleNamespace(
            DataUpdateCoordinator=FakeCoordinator
        ),
        "homeassistant.util": SimpleNamespace(
            dt=SimpleNamespace(
                utcnow=lambda: NOW, as_local=lambda value: value, DEFAULT_TIME_ZONE=timezone.utc
            )
        ),
    }
    spec = importlib.util.spec_from_file_location("ev_test.runtime", ROOT / "runtime.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, fake_modules):
        spec.loader.exec_module(module)
    return module, registry


runtime_module, registry = load_runtime()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = {
            "name": "Charger",
            "power_sensor": "sensor.ev",
            "email_entity": "notify.customer",
            "currency": "AUD",
            "rate": "0.30",
            "fixed_fee": "0",
            "tax_percent": "0",
            "schedule_mode": "all_day",
            "control_switch": False,
            "auto_email": True,
            "max_age": 300,
            "seller": "Seller",
            "customer": "Customer",
            "payment_instructions": "",
        }
        self.hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
        entry = SimpleNamespace(title="Charger", entry_id="entry", data=self.config, options={})
        self.runtime = runtime_module.BillingRuntime(self.hass, entry)
        ledger = self.runtime.ledger
        ledger.data["months"]["2026-01"] = {
            "kwh": "10",
            "lines": {"0.30": "10"},
            "settings": dict(self.config),
            "gap_seconds": 0,
            "partial": False,
        }
        self.runtime._write_invoice = lambda invoice: None

        async def executor(function, *args):
            return function(*args)

        self.hass.async_add_executor_job = executor

    async def test_automatic_invoice_sent_once(self):
        await self.runtime._invoice_completed(NOW)
        await self.runtime._invoice_completed(NOW)
        self.hass.services.async_call.assert_awaited_once()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "submitted")

    async def test_sending_marker_saved_before_external_send(self):
        async def send(*args, **kwargs):
            saved = self.runtime.store.snapshots[-1]
            self.assertEqual(saved["delivery"]["2026-01"], "sending")
            self.assertIn("2026-01", saved["invoices"])

        self.hass.services.async_call.side_effect = send
        await self.runtime._invoice_completed(NOW)

    async def test_failure_needs_explicit_retry(self):
        self.hass.services.async_call.side_effect = HAError("offline")
        await self.runtime._invoice_completed(NOW)
        await self.runtime._invoice_completed(NOW)
        self.hass.services.async_call.assert_awaited_once()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "failed")
        self.hass.services.async_call.side_effect = None
        await self.runtime.async_retry()
        self.assertEqual(self.hass.services.async_call.await_count, 2)
        self.assertEqual(len(self.runtime.ledger.data["invoices"]), 1)

    async def test_interrupted_send_is_not_automatically_retried(self):
        self.hass.services.async_call.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.runtime._invoice_completed(NOW)
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "sending")
        await self.runtime._invoice_completed(NOW)
        self.hass.services.async_call.assert_awaited_once()

    async def test_incomplete_month_blocks_email_until_approved(self):
        self.runtime.ledger.data["months"]["2026-01"]["gap_seconds"] = 60
        await self.runtime._invoice_completed(NOW)
        self.hass.services.async_call.assert_not_awaited()
        await self.runtime.async_approve()
        self.hass.services.async_call.assert_awaited_once()

    async def test_auto_email_disabled_keeps_invoice_pending(self):
        self.runtime.config["auto_email"] = False
        await self.runtime._invoice_completed(NOW)
        self.hass.services.async_call.assert_not_awaited()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "pending")

    async def test_email_uses_invoice_recipient_snapshot(self):
        self.runtime.config["auto_email"] = False
        await self.runtime._invoice_completed(NOW)
        self.runtime.config["email_entity"] = "notify.other_customer"
        await self.runtime.async_retry()
        call = self.hass.services.async_call.call_args
        self.assertEqual(call.args[2]["entity_id"], "notify.customer")

    async def test_schedule_controls_switch(self):
        self.runtime.config.update(control_switch=True, charger_switch="switch.ev")
        self.hass.states = SimpleNamespace(get=lambda entity: SimpleNamespace(state="off"))
        await self.runtime._control(NOW)
        self.hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_on", {"entity_id": "switch.ev"}, blocking=True
        )

    async def test_disabled_control_never_toggles_switch(self):
        await self.runtime._control(NOW)
        self.hass.services.async_call.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
