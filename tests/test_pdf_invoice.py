"""PDF accounting presentation and snapshot/attachment regressions."""

from copy import deepcopy
from decimal import Decimal
import importlib.util
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "ev_chargepoint"
package = ModuleType("pdf_test")
package.__path__ = [str(ROOT)]
spec = importlib.util.spec_from_file_location("pdf_test.pdf_invoice", ROOT / "pdf_invoice.py")
pdf = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"pdf_test": package}):
    spec.loader.exec_module(pdf)


def sample_invoice():
    return {
        "number": "SAMPLE-EV-2026-09", "issued_at": "2026-10-01T08:00:00+10:00", "period": "2026-09",
        "lines": {"0.08": "120", "0.30": "40"},
        "tariffs": {
            "ev_night": {"name": "EV Night", "lines": {"0.08": "120"}, "energy_cost": "9.60", "fallback_kwh": "0", "outside_schedule_kwh": "0"},
            "peak": {"name": "Peak", "lines": {"0.30": "40"}, "energy_cost": "12.00", "fallback_kwh": "0", "outside_schedule_kwh": "40"},
        },
        "subtotal": "21.60", "tax": "2.16", "total": "23.76", "partial": False, "gap_seconds": 0,
        "settings": {"seller": "PalmView\nEV charging services\nSample seller details", "customer": "Sample Customer\nSample billing address", "customer_email": "customer@example.com", "currency": "AUD", "fixed_fee": "0", "tax_percent": "10", "payment_instructions": "Sample payment instructions only.\nUse the invoice number as your payment reference.\nNot a payment request."},
    }


class InvoicePdfTests(unittest.TestCase):
    def test_rate_rows_preserve_legacy_remainder(self):
        invoice = sample_invoice()
        invoice['lines']['0.30'] = '42'
        self.assertEqual(pdf.invoice_rows(invoice), [('EV Night', Decimal('120'), Decimal('0.08')), ('Peak', Decimal('40'), Decimal('0.30')), ('Legacy recorded charging', Decimal('2'), Decimal('0.30'))])

    def test_render_does_not_mutate_issued_snapshot(self):
        invoice = sample_invoice()
        before = deepcopy(invoice)
        result = pdf.invoice_pdf(invoice)
        self.assertTrue(result.startswith(b'%PDF-'))
        self.assertTrue(result.rstrip().endswith(b'%%EOF'))
        self.assertEqual(invoice, before)

    def test_multiple_pages_and_escaped_user_text(self):
        invoice = sample_invoice()
        invoice['settings']['seller'] = 'Café & Co <Seller>'
        invoice['settings']['customer'] = '<script>alert(1)</script> & Customer'
        invoice['lines'] = {str(Decimal(i) / 10000): '1' for i in range(100)}
        invoice['tariffs'] = {}
        self.assertTrue(pdf.invoice_pdf(invoice).startswith(b'%PDF-'))

    def test_safe_filename(self):
        self.assertEqual(pdf.invoice_filename({'number': '../../evil\r\nname'}), '.._.._evil__name.pdf')

    def test_zero_and_incomplete_invoice_renders(self):
        invoice = sample_invoice()
        invoice.update(lines={}, tariffs={}, subtotal='0.00', tax='0.00', total='0.00', partial=True, gap_seconds=900)
        self.assertTrue(pdf.invoice_pdf(invoice).startswith(b'%PDF-'))
