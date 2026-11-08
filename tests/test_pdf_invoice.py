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
    def test_chart_distinguishes_zero_missing_and_incomplete(self):
        invoice = sample_invoice()
        invoice['days'] = {'2026-09-01': {'kwh': '0'},
                           '2026-09-03': {'kwh': '2.5', 'gap_seconds': 60},
                           '2026-08-31': {'kwh': '999'}}
        before = deepcopy(invoice)
        rows = pdf.daily_usage(invoice)
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0]['kwh'], Decimal('0'))
        self.assertIsNone(rows[1]['kwh'])
        self.assertEqual(rows[2]['kwh'], Decimal('2.5'))
        self.assertTrue(rows[2]['partial'])
        self.assertEqual(invoice, before)

    def test_chart_calendar_handles_leap_february_and_31_days(self):
        for period, expected in [('2028-02', 29), ('2027-02', 28), ('2026-10', 31)]:
            invoice = sample_invoice()
            invoice['period'] = period
            self.assertEqual(len(pdf.daily_usage(invoice)), expected)

    def test_chart_legacy_snapshot_has_no_fabricated_daily_usage(self):
        rows = pdf.daily_usage(sample_invoice())
        self.assertTrue(all(row['kwh'] is None for row in rows))

    def test_chart_invalid_values_are_not_zero(self):
        invoice = sample_invoice()
        invoice['days'] = {f'2026-09-0{i}': {'kwh': value}
                           for i, value in enumerate(['NaN', '-1', 'unknown', None], 1)}
        self.assertTrue(all(row['kwh'] is None for row in pdf.daily_usage(invoice)))

    def test_chart_first_record_is_partial_for_partial_invoice(self):
        invoice = self.detailed_invoice()
        invoice['partial'] = True
        rows = pdf.daily_usage(invoice)
        self.assertTrue(rows[0]['partial'])
        self.assertFalse(rows[1]['partial'])

    def detailed_invoice(self):
        invoice = sample_invoice()
        invoice['days'] = {}
        for day in ('2026-09-01', '2026-09-02'):
            invoice['days'][day] = {'kwh': '80', 'energy_cost': '10.80', 'tariffs': {
                'ev_night': {'name': 'EV Night', 'lines': {'0.08': '60'}},
                'peak': {'name': 'Peak', 'lines': {'0.30': '20'}},
            }}
        return invoice

    def test_four_modes_keep_energy_amounts_and_snapshots(self):
        for mode, expected_count in [('itemised', 4), ('daily', 2), ('monthly_tariffs', 2), ('monthly_total', 1)]:
            with self.subTest(mode=mode):
                invoice = self.detailed_invoice()
                invoice['settings']['invoice_billing_option'] = mode
                before = deepcopy(invoice)
                rows = pdf.invoice_items(invoice)
                self.assertEqual(len(rows), expected_count)
                self.assertEqual(sum(row['quantity'] for row in rows), Decimal('160'))
                self.assertEqual(sum(row['amount'] for row in rows), Decimal('21.60'))
                self.assertEqual(invoice, before)
                self.assertTrue(pdf.invoice_pdf(invoice).startswith(b'%PDF-'))

    def test_combined_rates_are_not_presented_as_a_single_tariff(self):
        invoice = self.detailed_invoice()
        invoice['settings']['invoice_billing_option'] = 'monthly_tariffs'
        invoice['lines'] = {'0.08': '120', '0.30': '20', '0.40': '20'}
        invoice['tariffs']['peak']['lines'] = {'0.30': '20', '0.40': '20'}
        peak = next(row for row in pdf.invoice_items(invoice) if row['description'] == 'Peak')
        self.assertEqual(peak['quantity'], Decimal('40'))
        self.assertEqual(peak['amount'], Decimal('14.00'))
        self.assertIsNone(peak['rate'])

    def test_missing_daily_history_stays_a_labelled_remainder(self):
        invoice = self.detailed_invoice()
        del invoice['days']['2026-09-02']
        invoice['settings']['invoice_billing_option'] = 'daily'
        rows = pdf.invoice_items(invoice)
        self.assertEqual(rows[0]['description'], '2026-09-01 - Combined tariffs')
        self.assertEqual(rows[1]['description'], 'Recorded charging without daily detail')
        self.assertEqual(rows[1]['amount'], Decimal('10.80'))
        self.assertNotIn('2026-09-02', str(rows))

    def test_daily_layout_ignores_other_months(self):
        invoice = self.detailed_invoice()
        invoice['days']['2026-08-31'] = {'kwh': '999', 'energy_cost': '999'}
        invoice['settings']['invoice_billing_option'] = 'daily'
        self.assertEqual(len(pdf.invoice_items(invoice)), 2)

    def test_new_default_is_itemised_and_old_snapshot_is_supported(self):
        self.assertEqual(len(pdf.invoice_items(self.detailed_invoice())), 4)
        self.assertEqual(len(pdf.invoice_items(sample_invoice())), 2)

    def test_rate_rows_preserve_legacy_remainder(self):
        invoice = sample_invoice()
        invoice['lines']['0.30'] = '42'
        self.assertEqual(pdf.invoice_rows(invoice), [('EV Night', Decimal('120'), Decimal('0.08'), Decimal('9.60')), ('Peak', Decimal('40'), Decimal('0.30'), Decimal('12.00')), ('Legacy recorded charging', Decimal('2'), Decimal('0.30'), Decimal('0.60'))])

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
