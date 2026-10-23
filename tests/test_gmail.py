"""Connected-account selection and immutable invoice-recipient regressions."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
package = ModuleType("gmail_test")
package.__path__ = [str(ROOT)]
spec = importlib.util.spec_from_file_location("gmail_test.gmail", ROOT / "gmail.py")
gmail = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "gmail_test": package,
    "homeassistant": ModuleType("homeassistant"),
    "homeassistant.util": SimpleNamespace(slugify=lambda value: "sender_gmail_com"),
}):
    spec.loader.exec_module(gmail)


class GmailTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.entries = [SimpleNamespace(entry_id="one", title="sender@gmail.com")]
        self.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_entries=lambda domain: self.entries),
            services=SimpleNamespace(has_service=lambda *args: True, async_call=AsyncMock()),
        )

    def test_single_account_is_default(self):
        self.assertEqual(gmail.resolve_gmail(self.hass), "sender_gmail_com")

    def test_ambiguous_default_is_rejected(self):
        self.entries.append(SimpleNamespace(entry_id="two", title="other@gmail.com"))
        with self.assertRaises(ValueError):
            gmail.resolve_gmail(self.hass)

    def test_removed_selection_never_falls_back_to_another_account(self):
        with self.assertRaises(ValueError):
            gmail.resolve_gmail(self.hass, "removed")

    def test_disconnected_account_is_rejected(self):
        self.hass.services.has_service = lambda *args: False
        with self.assertRaises(ValueError):
            gmail.resolve_gmail(self.hass)

    async def test_uses_invoice_recipient_and_default_account_sender(self):
        invoice = {
            "number": "EV-test-2026-09", "issued_at": "2026-10-01", "period": "2026-09",
            "lines": {"0.08": "10"}, "subtotal": "0.80", "tax": "0.00", "total": "0.80",
            "partial": False, "gap_seconds": 0,
            "settings": {"customer_email": "original@example.com", "customer": "Customer",
                         "seller": "Seller", "fixed_fee": "0", "tax_percent": "0",
                         "currency": "AUD", "payment_instructions": "Reference EV-test"},
        }
        await gmail.async_send_invoice(self.hass, {"customer_email": "changed@example.com"}, invoice)
        args, kwargs = self.hass.services.async_call.call_args
        self.assertEqual(args[:2], ("notify", "sender_gmail_com"))
        self.assertEqual(args[2]["target"], ["original@example.com"])
        self.assertEqual(args[2]["data"], {"send": True})
        self.assertNotIn("from", args[2]["data"])
        self.assertIn("EV-test-2026-09", args[2]["message"])
        self.assertTrue(kwargs["blocking"])

    async def test_missing_recipient_does_not_send(self):
        with self.assertRaises(ValueError):
            await gmail.async_send_invoice(self.hass, {}, {"settings": {}})
        self.hass.services.async_call.assert_not_awaited()
