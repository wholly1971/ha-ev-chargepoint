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
from unittest.mock import AsyncMock, Mock, patch


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
            slugify=lambda value: value.replace("@", "_").replace(".", "_").lower(),
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
            "customer_email": "customer@example.com",
            "currency": "AUD",
            "rate": "0.30",
            "fixed_fee": "0",
            "tax_percent": "0",
            "schedule_mode": "all_day",
            "control_switch": False,
            "auto_email": True,
            "smtp_provider": "custom",
            "max_age": 300,
            "seller": "Seller",
            "customer": "Customer",
            "payment_instructions": "",
        }
        self.hass = SimpleNamespace(services=SimpleNamespace(async_call=AsyncMock()))
        entry = SimpleNamespace(title="Charger", entry_id="entry", data=self.config, options={})
        self.runtime = runtime_module.BillingRuntime(self.hass, entry)
        self.mail = Mock()
        mail_patch = patch.object(runtime_module, "send_invoice", self.mail)
        mail_patch.start()
        self.addCleanup(mail_patch.stop)
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
        self.mail.assert_called_once()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "submitted")

    async def test_gmail_oauth_uses_connected_account_without_smtp(self):
        self.runtime.config["smtp_provider"] = "gmail_oauth"
        send = AsyncMock()
        with patch.object(runtime_module, "async_send_gmail_invoice", send):
            await self.runtime._invoice_completed(NOW)
            await self.runtime._invoice_completed(NOW)
        send.assert_awaited_once()
        self.mail.assert_not_called()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "submitted")

    async def test_gmail_authorization_failure_waits_for_explicit_retry(self):
        self.runtime.config["smtp_provider"] = "gmail_oauth"
        send = AsyncMock(side_effect=HAError("Reauthorization required"))
        with patch.object(runtime_module, "async_send_gmail_invoice", send):
            await self.runtime._invoice_completed(NOW)
            await self.runtime._invoice_completed(NOW)
        send.assert_awaited_once()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "failed")

    async def test_sending_marker_saved_before_external_send(self):
        def send(*args, **kwargs):
            saved = self.runtime.store.snapshots[-1]
            self.assertEqual(saved["delivery"]["2026-01"], "sending")
            self.assertIn("2026-01", saved["invoices"])

        self.mail.side_effect = send
        await self.runtime._invoice_completed(NOW)

    async def test_failure_needs_explicit_retry(self):
        self.mail.side_effect = OSError("offline")
        await self.runtime._invoice_completed(NOW)
        await self.runtime._invoice_completed(NOW)
        self.mail.assert_called_once()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "failed")
        self.mail.side_effect = None
        await self.runtime.async_retry()
        self.assertEqual(self.mail.call_count, 2)
        self.assertEqual(len(self.runtime.ledger.data["invoices"]), 1)

    async def test_interrupted_send_is_not_automatically_retried(self):
        self.mail.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.runtime._invoice_completed(NOW)
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "sending")
        await self.runtime._invoice_completed(NOW)
        self.mail.assert_called_once()

    async def test_incomplete_month_blocks_email_until_approved(self):
        self.runtime.ledger.data["months"]["2026-01"]["gap_seconds"] = 60
        await self.runtime._invoice_completed(NOW)
        self.mail.assert_not_called()
        await self.runtime.async_approve()
        self.mail.assert_called_once()

    async def test_auto_email_disabled_keeps_invoice_pending(self):
        self.runtime.config["auto_email"] = False
        await self.runtime._invoice_completed(NOW)
        self.mail.assert_not_called()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "pending")

    async def test_email_uses_invoice_recipient_snapshot(self):
        self.runtime.config["auto_email"] = False
        await self.runtime._invoice_completed(NOW)
        self.runtime.config["customer_email"] = "other@example.com"
        await self.runtime.async_retry()
        call = self.mail.call_args
        self.assertEqual(call.args[1]["settings"]["customer_email"], "customer@example.com")

    async def test_schedule_controls_switch(self):
        self.runtime.config.update(control_switch=True, charger_switch="switch.ev")
        self.hass.states = SimpleNamespace(get=lambda entity: SimpleNamespace(state="off"))
        await self.runtime._control(NOW)
        self.hass.services.async_call.assert_awaited_once_with(
            "switch", "turn_on", {"entity_id": "switch.ev"}, blocking=True
        )

    async def test_no_email_blocks_automatic_and_manual_delivery(self):
        self.runtime.config.update(smtp_provider="none", auto_email=True)
        await self.runtime._invoice_completed(NOW)
        await self.runtime.async_retry()
        self.mail.assert_not_called()
        self.assertEqual(self.runtime.ledger.data["delivery"]["2026-01"], "pending")
        self.assertIn("2026-01", self.runtime.ledger.data["invoices"])

    async def test_disabled_control_never_toggles_switch(self):
        await self.runtime._control(NOW)
        self.hass.services.async_call.assert_not_awaited()

    async def test_test_email_does_not_mutate_ledger_or_require_auto_email(self):
        before = deepcopy(self.runtime.ledger.data)
        self.runtime.config["auto_email"] = False
        send = Mock()
        with patch.object(runtime_module, "send_test_email", send):
            await self.runtime.async_test_email()
        send.assert_called_once_with(self.runtime.config)
        self.assertEqual(self.runtime.email_test["status"], "submitted")
        self.assertEqual(self.runtime.ledger.data, before)
        self.assertEqual(self.runtime.store.snapshots, [])
        self.mail.assert_not_called()

    async def test_test_email_failure_is_visible_and_not_retried(self):
        send = Mock(side_effect=OSError("offline"))
        with patch.object(runtime_module, "send_test_email", send):
            with self.assertRaises(HAError):
                await self.runtime.async_test_email()
        self.assertEqual(self.runtime.email_test["status"], "failed")
        send.assert_called_once()

    async def test_test_email_has_repeat_guard(self):
        send = Mock()
        with patch.object(runtime_module, "send_test_email", send):
            await self.runtime.async_test_email()
            with self.assertRaises(HAError):
                await self.runtime.async_test_email()
        send.assert_called_once()

    async def test_test_email_disabled_provider_cannot_send(self):
        self.runtime.config["smtp_provider"] = "none"
        send = Mock()
        with patch.object(runtime_module, "send_test_email", send):
            with self.assertRaises(HAError):
                await self.runtime.async_test_email()
        send.assert_not_called()

    async def test_test_email_uses_connected_account_transport(self):
        self.runtime.config["smtp_provider"] = "gmail_oauth"
        send = AsyncMock()
        with patch.object(runtime_module, "async_send_gmail_test", send):
            await self.runtime.async_test_email()
        send.assert_awaited_once_with(self.hass, self.runtime.config)


if __name__ == "__main__":
    unittest.main()
