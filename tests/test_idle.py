"""Continuous idle evidence and persistent off latch acceptance cases."""

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('idle', Path(__file__).resolve().parents[1] / 'custom_components/ev_chargepoint/idle.py')
idle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle)


class IdleTests(unittest.TestCase):
    def setUp(self):
        self.guard = idle.IdleShutoff()
        self.now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    def observe(self, minute, watts=0, on=True, duration=30):
        return self.guard.observe(self.now + timedelta(minutes=minute), on, watts, duration, 100, 300)

    def test_exactly_thirty_minutes_of_continuous_idle(self):
        for minute in range(30):
            self.assertFalse(self.observe(minute))
        self.assertTrue(self.observe(30))

    def test_active_power_resets_idle(self):
        for minute in range(20):
            self.observe(minute)
        self.assertFalse(self.observe(20, watts=100))
        for minute in range(21, 51):
            self.assertFalse(self.observe(minute))
        self.assertTrue(self.observe(51))

    def test_unavailable_and_scheduler_outage_restart_full_timer(self):
        for minute in range(20):
            self.observe(minute)
        self.assertFalse(self.observe(20, watts=None))
        self.assertFalse(self.observe(40))
        self.assertFalse(self.observe(60))  # Twenty-minute sampling outage, not proof of idle.
        for minute in range(61, 90):
            self.assertFalse(self.observe(minute))
        self.assertTrue(self.observe(90))

    def test_off_and_disabled_do_not_count_idle(self):
        self.observe(0)
        self.assertFalse(self.observe(30, on=False))
        self.assertFalse(self.observe(31))
        self.assertFalse(self.observe(61, duration=0))

    def test_latch_survives_restart_until_next_start(self):
        release = self.now + timedelta(days=1)
        self.guard.block(self.now, release)
        restored = idle.IdleShutoff(self.guard.saved)
        self.assertTrue(restored.observe(self.now + timedelta(hours=1), False, None, 30, 100, 300))
        self.assertFalse(restored.observe(release, True, 0, 30, 100, 300))
        self.assertFalse(restored.status(30, 100)['battery_full_confirmed'])

    def test_all_day_latch_needs_explicit_reset(self):
        self.guard.block(self.now, None)
        self.assertTrue(self.observe(100000))
        self.guard.reset()
        self.assertFalse(self.observe(100001))

    def test_restart_does_not_credit_unobserved_idle_time(self):
        for minute in range(20):
            self.observe(minute)
        self.guard = idle.IdleShutoff(self.guard.saved)
        self.assertFalse(self.observe(30))

