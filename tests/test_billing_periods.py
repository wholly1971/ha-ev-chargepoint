"""Non-overlapping billing periods, session detection and migration acceptance."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import unittest

from test_billing import billing, const


class BillingPeriodsTests(unittest.TestCase):
    def setUp(self):
        self.ledger = billing.Ledger()
        self.config = {**const.DEFAULTS, 'billing_scope': 'all_time', 'billing_period': 'daily'}
        self.zone = ZoneInfo('Australia/Brisbane')
        self.now = datetime(2026, 1, 31, 23, 0, tzinfo=self.zone)

    def advance(self, now, watts='1000', valid=True):
        self.ledger.advance(now, Decimal(watts) if watts is not None else None,
                            self.config, self.zone, valid)

    def closed(self):
        return {key: bucket for key, bucket in self.ledger.data['cycles'].items() if bucket['closed']}

    def test_daily_local_midnight_splits_month_and_tariffs(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(hours=2))
        self.assertEqual(len(self.closed()), 1)
        key, bucket = next(iter(self.closed().items()))
        self.assertAlmostEqual(float(bucket['kwh']), 1)
        invoice = self.ledger.issue_cycle(key, 'id', self.now + timedelta(hours=2))
        self.assertEqual(invoice['total'], '0.30')
        self.assertEqual(set(invoice['days']), {'2026-01-31'})
        self.assertIn('2026-01-31', billing.invoice_text(invoice))
        self.assertIn('2026-02-01T00:00:00+10:00', invoice['period_end'])

    def test_week_starts_monday_and_crosses_month(self):
        self.config['billing_period'] = 'weekly'
        start = datetime(2026, 1, 26, tzinfo=self.zone)
        self.advance(start)
        self.advance(start + timedelta(days=7))
        key, bucket = next(iter(self.closed().items()))
        self.assertAlmostEqual(float(bucket['kwh']), 168)
        invoice = self.ledger.issue_cycle(key, 'id', start + timedelta(days=7))
        self.assertEqual(len(invoice['days']), 7)
        self.assertEqual(invoice['total'], '50.40')

    def test_daily_fee_proration_reconciles_month(self):
        self.config.update(fixed_fee='31', tax_percent='10')
        start = datetime(2026, 1, 1, tzinfo=self.zone)
        self.advance(start, '0')
        self.advance(start + timedelta(days=31), '0')
        invoices = [self.ledger.issue_cycle(key, 'id', start + timedelta(days=31)) for key in self.closed()]
        self.assertEqual(sum(Decimal(inv['subtotal']) for inv in invoices), Decimal('31'))
        self.assertEqual(sum(Decimal(inv['tax']) for inv in invoices), Decimal('3.10'))

    def test_last_sunday_second_belongs_only_to_ending_week(self):
        self.config.update(billing_period='weekly', rate='0.33', rate_includes_gst=True, tax_percent='10')
        sunday = datetime(2026, 2, 1, 23, 59, 59, tzinfo=self.zone)
        self.advance(sunday, '3600000')  # One kWh per second, to expose boundary errors.
        self.advance(sunday + timedelta(seconds=1), '3600000')
        key, bucket = next(iter(self.closed().items()))
        self.assertEqual(Decimal(bucket['kwh']), Decimal(1))
        invoice = self.ledger.issue_cycle(key, 'id', sunday + timedelta(seconds=1))
        self.assertEqual((invoice['subtotal'], invoice['tax'], invoice['total']), ('0.30', '0.03', '0.33'))
        self.assertEqual(set(invoice['days']), {'2026-02-01'})
        self.advance(sunday + timedelta(seconds=2), '0')
        next_bucket = self.ledger.data['cycles'][self.ledger.data['active_cycle']]
        self.assertEqual(Decimal(next_bucket['kwh']), Decimal(1))
        self.assertEqual(set(next_bucket['days']), {'2026-02-02'})
        self.assertEqual(len(self.closed()), 1)

    def test_full_week_tariff_gst_totals_and_monday_to_sunday_label(self):
        self.config.update(billing_period='weekly', use_tariff_bands=True, tax_percent='10',
            tariff_ev_night_enabled=True, tariff_ev_night_start='00:00:00', tariff_ev_night_end='06:00:00',
            tariff_ev_night_rate='0.08', tariff_ev_night_rate_includes_gst=True,
            tariff_peak_enabled=True, tariff_peak_start='06:00:00', tariff_peak_end='00:00:00',
            tariff_peak_rate='0.30', tariff_peak_rate_includes_gst=True)
        start = datetime(2026, 1, 26, tzinfo=self.zone)
        self.advance(start)
        self.advance(start + timedelta(days=7))
        key = next(iter(self.closed()))
        invoice = self.ledger.issue_cycle(key, 'id', start + timedelta(days=7))
        self.assertAlmostEqual(float(invoice['tariffs']['ev_night']['kwh']), 42)
        self.assertAlmostEqual(float(invoice['tariffs']['peak']['kwh']), 126)
        self.assertEqual((invoice['subtotal'], invoice['tax'], invoice['total']), ('37.42', '3.74', '41.16'))
        self.assertEqual(len(invoice['days']), 7)
        label = billing.period_label(invoice)
        self.assertIn('Monday 26 Jan 2026 00:00', label)
        self.assertIn('Sunday 01 Feb 2026 23:59:59', label)
        self.assertNotIn('Monday 02 Feb', label)

    def test_two_consecutive_weeks_reconcile_without_overlap(self):
        self.config['billing_period'] = 'weekly'
        start = datetime(2026, 1, 26, tzinfo=self.zone)
        self.advance(start)
        self.advance(start + timedelta(days=14))
        buckets = list(self.closed().values())
        self.assertEqual(len(buckets), 2)
        self.assertEqual(buckets[0]['end'], buckets[1]['start'])
        self.assertAlmostEqual(sum(float(b['kwh']) for b in buckets), 336)
        self.assertTrue(set(buckets[0]['days']).isdisjoint(buckets[1]['days']))

    def test_cross_month_week_prorates_each_month_fee(self):
        self.config.update(billing_period='weekly', fixed_fee='31', tax_percent='10')
        start = datetime(2026, 1, 26, tzinfo=self.zone)
        self.advance(start, '0')
        self.advance(datetime(2026, 2, 1, tzinfo=self.zone), '0')
        self.config['fixed_fee'] = '28'
        end = datetime(2026, 2, 2, tzinfo=self.zone)
        self.advance(end, '0')
        key = next(iter(self.closed()))
        invoice = self.ledger.issue_cycle(key, 'id', end)
        self.assertEqual((invoice['subtotal'], invoice['tax'], invoice['total']), ('7.00', '0.70', '7.70'))

    def test_dst_weeks_keep_all_seven_local_days_and_real_energy(self):
        self.config['billing_period'] = 'weekly'
        self.zone = ZoneInfo('Australia/Sydney')
        for date, hours in [((2026, 3, 30), 169), ((2026, 9, 28), 167)]:
            with self.subTest(date=date):
                self.ledger = billing.Ledger()
                start = datetime(*date, tzinfo=self.zone)
                self.advance(start)
                self.advance(start + timedelta(days=7))
                bucket = next(iter(self.closed().values()))
                self.assertAlmostEqual(float(bucket['kwh']), hours)
                self.assertEqual(len(bucket['days']), 7)

    def test_session_idle_delay_short_pause_and_separate_charges(self):
        self.config['billing_period'] = 'each_charge'
        self.advance(self.now)
        self.advance(self.now + timedelta(minutes=30), '0')
        self.advance(self.now + timedelta(minutes=32))
        self.assertFalse(self.closed())
        self.advance(self.now + timedelta(minutes=60), '0')
        self.advance(self.now + timedelta(minutes=65), '0')
        self.assertEqual(len(self.closed()), 1)
        key = next(iter(self.closed()))
        invoice = self.ledger.issue_cycle(key, 'id', self.now + timedelta(minutes=65))
        self.assertAlmostEqual(float(invoice['kwh']), 58 / 60)
        self.advance(self.now + timedelta(minutes=70))
        self.advance(self.now + timedelta(minutes=80), '0')
        self.advance(self.now + timedelta(minutes=85), '0')
        self.assertEqual(len(self.closed()), 2)

    def test_session_unknown_does_not_end_charge_and_requires_approval(self):
        self.config['billing_period'] = 'each_charge'
        self.advance(self.now)
        self.advance(self.now + timedelta(minutes=5))
        self.advance(self.now + timedelta(minutes=10), None, False)
        self.advance(self.now + timedelta(minutes=20), '0')
        self.assertFalse(self.closed())
        self.advance(self.now + timedelta(minutes=25), '0')
        key = next(iter(self.closed()))
        with self.assertRaises(ValueError):
            self.ledger.issue_cycle(key, 'id', self.now)
        self.assertGreater(self.ledger.issue_cycle(key, 'id', self.now, True)['gap_seconds'], 0)

    def test_restart_preserves_cycle_and_blocks_incomplete_bill(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(minutes=20))
        self.ledger = billing.Ledger(deepcopy(self.ledger.data))
        self.advance(self.now + timedelta(minutes=40))
        self.advance(self.now + timedelta(hours=1))
        key = next(iter(self.closed()))
        with self.assertRaises(ValueError):
            self.ledger.issue_cycle(key, 'id', self.now + timedelta(hours=1))
        invoice = self.ledger.issue_cycle(key, 'id', self.now + timedelta(hours=1), True)
        self.assertEqual(invoice['gap_seconds'], 1200)
        snapshot = deepcopy(invoice)
        self.assertEqual(self.ledger.issue_cycle(key, 'id', self.now, True), snapshot)

    def test_switch_cadence_preserves_unbilled_month_without_overlap(self):
        self.config['billing_period'] = 'monthly'
        self.advance(self.now)
        self.advance(self.now + timedelta(minutes=30))
        self.config['billing_period'] = 'daily'
        self.advance(self.now + timedelta(hours=1))
        old = self.ledger.data['cycles']['transition-2026-01']
        daily = next(bucket for key, bucket in self.closed().items() if key != 'transition-2026-01')
        self.assertEqual(datetime.fromisoformat(old['end']), datetime.fromisoformat(daily['start']))
        self.assertAlmostEqual(float(old['kwh']) + float(daily['kwh']), 1)
        self.assertEqual(self.ledger.data['cycle_cutover_month'], '2026-01')

    def test_mode_change_shortens_old_open_period(self):
        self.advance(self.now)
        self.advance(self.now + timedelta(minutes=10))
        self.config['billing_period'] = 'weekly'
        self.advance(self.now + timedelta(minutes=20))
        old = next(iter(self.closed().values()))
        new = self.ledger.data['cycles'][self.ledger.data['active_cycle']]
        self.assertEqual(datetime.fromisoformat(old['end']), datetime.fromisoformat(new['start']))
        self.assertEqual(old['kwh'], new['kwh'])

    def test_dst_day_uses_actual_elapsed_hours(self):
        self.zone = ZoneInfo('Australia/Sydney')
        start = datetime(2026, 4, 5, tzinfo=self.zone)
        self.advance(start)
        self.advance(datetime(2026, 4, 6, tzinfo=self.zone))
        self.assertAlmostEqual(float(next(iter(self.closed().values()))['kwh']), 25)

    def test_monthly_default_does_not_migrate_or_rebill(self):
        self.config['billing_period'] = 'monthly'
        self.advance(self.now)
        self.advance(self.now + timedelta(hours=1))
        self.assertNotIn('cycles', self.ledger.data)


if __name__ == '__main__':
    unittest.main()
