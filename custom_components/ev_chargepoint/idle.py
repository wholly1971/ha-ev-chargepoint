"""Continuous observed idle time; no inferred battery state or outage backfill."""

from datetime import datetime


class IdleShutoff:
    def __init__(self, saved=None):
        self.saved = dict(saved or {})
        self.since = None
        self.checked = None

    def reset(self):
        self.saved = {}
        self.since = self.checked = None

    def observe(self, now, switch_on, watts, minutes, threshold, max_age):
        if self.saved.get('blocked'):
            release = self.saved.get('release_at')
            if release and now >= datetime.fromisoformat(release):
                self.reset()
            else:
                return True
        if not minutes or not switch_on or watts is None or watts >= threshold:
            self.since = self.checked = None
            return False
        if self.since is None or self.checked is None or not 0 <= (now - self.checked).total_seconds() <= max_age:
            self.since = now
        self.checked = now
        return (now - self.since).total_seconds() >= minutes * 60

    def block(self, now, release):
        self.saved = {'blocked': True, 'stopped_at': now.isoformat(),
                      'release_at': release.isoformat() if release else None,
                      'reason': 'No active charging for the configured idle period; battery full not confirmed'}
        self.since = self.checked = None

    def status(self, minutes, threshold):
        return {**self.saved, 'minutes': minutes, 'threshold_w': threshold,
                'idle_since': self.since.isoformat() if self.since else None,
                'battery_full_confirmed': False}
