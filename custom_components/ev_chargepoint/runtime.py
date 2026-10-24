"""Live metering, scheduled control, invoice persistence and email delivery."""

import asyncio
from datetime import datetime, timedelta
from decimal import InvalidOperation
import logging
from pathlib import Path
import smtplib
from time import monotonic

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .billing import Ledger, decimal, in_window, invoice_html
from .const import DEFAULTS, DOMAIN
from .tariffs import resolve_rates
from .branding import logo_data_uri
from .mail import send_invoice, send_test_email
from .gmail import async_send_invoice as async_send_gmail_invoice, async_send_test_email as async_send_gmail_test

_LOGGER = logging.getLogger(__name__)


class BillingRuntime(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=entry.title)
        self.entry = entry
        self.config = {**DEFAULTS, **(entry.options or entry.data)}
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", private=True)
        self.ledger = Ledger()
        self.lock = asyncio.Lock()
        self.charge_lock = asyncio.Lock()
        self.unsubscribers = []
        self.stopping = False
        self.sample_rates = None
        self.charge_mode = "Automatic schedule"
        self.override_until = None
        self.charge_mode_entity_id = None
        self.email_test_lock = asyncio.Lock()
        self.email_test = {"status": "not_tested", "attempted_at": None}
        self.last_email_test = None

    async def async_start(self):
        self.ledger = Ledger(await self.store.async_load())
        await self.async_tick()

        @callback
        def changed(event):
            self.hass.async_create_task(self.async_tick())

        self.unsubscribers.append(
            async_track_state_change_event(self.hass, [self.config["power_sensor"], *([self.config["charger_switch"]] if self.config.get("charger_switch") else []), *[value for key, value in self.config.items() if key.startswith("tariff_") and key.endswith("_sensor") and value]], changed)
        )
        self.unsubscribers.append(
            async_track_time_interval(self.hass, self.async_tick, timedelta(seconds=30))
        )

    async def async_stop(self):
        self.stopping = True
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        async with self.lock:
            self._sample(dt_util.utcnow())
            await self.store.async_save(self.ledger.data)

    def _sample(self, now):
        state = self.hass.states.get(self.config["power_sensor"])
        watts = None
        fresh = False
        if state is not None:
            reported = state.last_reported
            fresh = 0 <= (now - reported).total_seconds() <= self.config["max_age"]
            try:
                value = decimal(state.state)
                unit = state.attributes.get("unit_of_measurement")
                if fresh and unit in ("W", "kW") and value >= 0:
                    watts = value * (1000 if unit == "kW" else 1)
            except (ValueError, InvalidOperation):
                pass
        # On an unavailable event, the prior reading was valid until that event.
        # On stale data, conservatively mark the whole last tick as a gap.
        cursor = self.ledger.data["cursor"]
        if (
            cursor
            and (now - datetime.fromisoformat(cursor)).total_seconds() > self.config["max_age"]
        ):
            fresh = False
        rates = resolve_rates(self.hass, self.config)
        effective = {**self.config, "_tariff_rates": self.sample_rates or rates}
        self.ledger.advance(now, watts, effective, dt_util.DEFAULT_TIME_ZONE, valid_previous=fresh)
        self.sample_rates = rates

    async def async_tick(self, _now=None):
        async with self.lock:
            if self.stopping:
                return
            now = dt_util.utcnow()
            self._sample(now)
            # Persist consumption before external actions.
            await self.store.async_save(self.ledger.data)
            await self._control(now)
            await self._invoice_completed(now)
            self.async_set_updated_data(self.ledger.data)

    async def _control(self, now):
        async with self.charge_lock:
            await self._control_locked(now)

    async def _control_locked(self, now):
        if self.override_until is not None and now >= self.override_until:
            self.charge_mode = "Automatic schedule"
            self.override_until = None
        if self.charge_mode == "Automatic schedule":
            if not self.config["control_switch"]:
                return
            desired = "on" if in_window(dt_util.as_local(now), self.config) else "off"
        else:
            desired = "on" if self.charge_mode == "Manual charging on" else "off"
        entity_id = self.config["charger_switch"]
        state = self.hass.states.get(entity_id)
        if state is None or state.state == desired:
            return
        try:
            await self.hass.services.async_call(
                "switch", f"turn_{desired}", {"entity_id": entity_id}, blocking=True
            )
        except HomeAssistantError:
            _LOGGER.warning("Could not apply EV charging schedule for %s", self.entry.entry_id)

    async def _invoice_completed(self, now, approve=False):
        current = dt_util.as_local(now).strftime("%Y-%m")
        for period in sorted(self.ledger.data["months"]):
            if period >= current:
                continue
            try:
                invoice = self.ledger.issue(period, current, self.entry.entry_id, now, approve)
            except ValueError:
                continue
            await self.store.async_save(self.ledger.data)
            await self.hass.async_add_executor_job(self._write_invoice, invoice)
            if self.config["auto_email"] and self.ledger.data["delivery"].get(period) == "pending":
                await self._send(period)

    def _write_invoice(self, invoice):
        folder = Path(self.hass.config.path("ev_chargepoint_invoices", self.entry.entry_id))
        folder.mkdir(parents=True, exist_ok=True)
        # Regenerate the same immutable snapshot atomically after interruptions.
        path = folder / f"{invoice['period']}.html"
        if path.exists():
            return
        temporary = path.with_suffix(".tmp")
        temporary.write_text(invoice_html(invoice, logo_src=logo_data_uri()), encoding="utf-8")
        temporary.replace(path)

    async def _send(self, period):
        if self.config.get("smtp_provider") == "none":
            return
        invoice = self.ledger.data["invoices"][period]
        # Mark before sending: an interrupted/uncertain attempt is never retried
        # automatically, because the mail server may already have accepted it.
        self.ledger.data["delivery"][period] = "sending"
        await self.store.async_save(self.ledger.data)
        try:
            if self.config.get("smtp_provider") == "gmail_oauth":
                await async_send_gmail_invoice(self.hass, self.config, invoice)
            else:
                await self.hass.async_add_executor_job(send_invoice, self.config, invoice)
        except (OSError, smtplib.SMTPException, ValueError, HomeAssistantError):
            self.ledger.data["delivery"][period] = "failed"
            _LOGGER.warning(
                "Invoice email failed for %s; manual retry required", self.entry.entry_id
            )
        else:
            self.ledger.data["delivery"][period] = "submitted"
        await self.store.async_save(self.ledger.data)

    async def async_approve(self):
        async with self.lock:
            await self._invoice_completed(dt_util.utcnow(), approve=True)
            self.async_set_updated_data(self.ledger.data)

    async def async_retry(self):
        async with self.lock:
            for period, status in list(self.ledger.data["delivery"].items()):
                if status in ("pending", "failed", "sending"):
                    await self._send(period)
            self.async_set_updated_data(self.ledger.data)

    async def async_test_email(self):
        """Explicit one-message test, independent of automatic invoice delivery."""
        if self.config.get("smtp_provider") == "none":
            raise HomeAssistantError("Configure an email provider and recipient first")
        if self.email_test_lock.locked():
            raise HomeAssistantError("An email test is already in progress")
        if self.last_email_test is not None and monotonic() - self.last_email_test < 60:
            raise HomeAssistantError("Wait 60 seconds before sending another test email")
        async with self.email_test_lock:
            self.last_email_test = monotonic()
            self.email_test = {"status": "sending", "attempted_at": dt_util.utcnow().isoformat()}
            self.async_set_updated_data(self.ledger.data)
            try:
                if self.config.get("smtp_provider") == "gmail_oauth":
                    await async_send_gmail_test(self.hass, self.config)
                else:
                    await self.hass.async_add_executor_job(send_test_email, self.config)
            except (OSError, smtplib.SMTPException, ValueError, HomeAssistantError) as err:
                self.email_test["status"] = "failed"
                raise HomeAssistantError("Test email failed. Check the provider, login/app password and recipient; no automatic retry was made.") from err
            else:
                self.email_test["status"] = "submitted"
            finally:
                self.async_set_updated_data(self.ledger.data)

    def _next_schedule_boundary(self, now):
        if not self.config["control_switch"] or self.config["schedule_mode"] != "window":
            return None
        initial = in_window(dt_util.as_local(now), self.config)
        boundary = now.replace(second=0, microsecond=0)
        for _ in range(1500):
            boundary += timedelta(minutes=1)
            if in_window(dt_util.as_local(boundary), self.config) != initial:
                return boundary
        return None

    async def async_set_charge_mode(self, mode):
        """Explicit manual override; automatic operation resumes at the next boundary."""
        if mode not in ("Automatic schedule", "Manual charging on", "Manual charging off"):
            raise HomeAssistantError("Invalid charging mode")
        entity_id = self.config.get("charger_switch")
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state not in ("on", "off"):
            raise HomeAssistantError("The configured charger switch is unavailable")
        async with self.charge_lock:
            now = dt_util.utcnow()
            if mode == "Automatic schedule":
                desired = "on" if in_window(dt_util.as_local(now), self.config) else "off"
                apply = self.config["control_switch"]
            else:
                desired = "on" if mode == "Manual charging on" else "off"
                apply = True
            if apply:
                await self.hass.services.async_call("switch", f"turn_{desired}", {"entity_id": entity_id}, blocking=True)
            self.charge_mode = mode
            self.override_until = self._next_schedule_boundary(now) if mode != "Automatic schedule" else None
            self.async_set_updated_data(self.ledger.data)
