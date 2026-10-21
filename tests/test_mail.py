"""Test SMTP encryption, recipient snapshots, Gmail presets and secret handling."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
package = ModuleType("mail_test")
package.__path__ = [str(ROOT)]
spec = importlib.util.spec_from_file_location("mail_test.mail", ROOT / "mail.py")
mail = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"mail_test": package}):
    spec.loader.exec_module(mail)
    billing = sys.modules["mail_test.billing"]


class MailTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_security": "starttls",
            "smtp_username": "sender@example.com",
            "smtp_password": "secret-app-password",
            "smtp_sender": "sender@example.com",
            "customer_email": "customer@example.com",
            "currency": "AUD",
            "rate": "0.30",
            "fixed_fee": "0",
            "tax_percent": "0",
            "schedule_mode": "all_day",
            "customer": "Customer",
            "seller": "Seller",
            "payment_instructions": "Bank transfer",
        }
        self.ledger = billing.Ledger()
        now = datetime(2026, 1, 15, tzinfo=timezone.utc)
        self.ledger.advance(now, billing.decimal(1000), self.config, timezone.utc)
        self.ledger.advance(
            now + timedelta(hours=1), billing.decimal(1000), self.config, timezone.utc
        )
        self.invoice = self.ledger.issue("2026-01", "2026-02", "id", now, True)

    def test_starttls_precedes_authentication(self):
        with patch.object(mail.smtplib, "SMTP") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            mail.send_invoice(self.config, self.invoice)
            names = [call[0] for call in smtp.method_calls]
            self.assertLess(names.index("starttls"), names.index("login"))
            smtp.login.assert_called_once_with("sender@example.com", "secret-app-password")
            message = smtp.send_message.call_args.args[0]
            self.assertEqual(message["To"], "customer@example.com")
            self.assertEqual(message["From"], "sender@example.com")
            self.assertIn("text/html", message.as_string())
            self.assertNotIn("secret-app-password", message.as_string())

    def test_implicit_tls_uses_verified_context(self):
        self.config.update(smtp_security="tls", smtp_port=465)
        with patch.object(mail.smtplib, "SMTP_SSL") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            mail.send_invoice(self.config, self.invoice)
            context = factory.call_args.kwargs["context"]
            self.assertTrue(context.check_hostname)
            smtp.starttls.assert_not_called()

    def test_recipient_cannot_be_redirected_by_later_config(self):
        self.config["customer_email"] = "other@example.com"
        with patch.object(mail.smtplib, "SMTP") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            mail.send_invoice(self.config, self.invoice)
            self.assertEqual(smtp.send_message.call_args.args[0]["To"], "customer@example.com")

    def test_credentials_never_enter_ledger(self):
        self.assertNotIn("secret-app-password", str(self.ledger.data))
        self.assertFalse(any(key.startswith("smtp_") for key in self.invoice["settings"]))

    def test_header_injection_is_rejected(self):
        self.invoice["settings"]["customer_email"] = "a@example.com\nBcc: b@example.com"
        with patch.object(mail.smtplib, "SMTP") as factory:
            with self.assertRaises(ValueError):
                mail.send_invoice(self.config, self.invoice)
            factory.assert_not_called()

    def test_unencrypted_transport_is_rejected(self):
        self.config["smtp_security"] = "none"
        with self.assertRaises(ValueError):
            mail.validate_mail(self.config)

    def test_refused_recipient_is_failure(self):
        with patch.object(mail.smtplib, "SMTP") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {"customer@example.com": (550, b"Rejected")}
            with self.assertRaises(mail.smtplib.SMTPRecipientsRefused):
                mail.send_invoice(self.config, self.invoice)

    def test_gmail_preset_and_app_password(self):
        self.config.update(
            smtp_provider="gmail", smtp_sender="", smtp_password="abcd efgh ijkl mnop"
        )
        with patch.object(mail.smtplib, "SMTP") as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            mail.send_invoice(self.config, self.invoice)
            self.assertEqual(factory.call_args.kwargs["host"], "smtp.gmail.com")
            self.assertEqual(factory.call_args.kwargs["port"], 587)
            smtp.starttls.assert_called_once()
            smtp.login.assert_called_once_with("sender@example.com", "abcdefghijklmnop")
            self.assertEqual(smtp.send_message.call_args.args[0]["From"], "sender@example.com")

    def test_gmail_requires_login_and_app_password(self):
        self.config.update(smtp_provider="gmail", smtp_password="")
        with self.assertRaises(ValueError):
            mail.validate_mail(self.config)
