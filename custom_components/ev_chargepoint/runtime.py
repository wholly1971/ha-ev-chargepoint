"""Live metering, scheduled control, invoice persistence and email delivery."""

import asyncio
from datetime import datetime, timedelta
from decimal import InvalidOperation
import logging
from pathlib import Path
import smtplib

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .billing import Ledger, decimal, in_window, invoice_html
from .const import DEFAULTS, DOMAIN
from .mail import send_invoice

_LOGGER = logging.getLogger(__name__)


class BillingRuntime(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=entry.title)
        self.entry = entry
        self.config = {**DEFAULTS, **(entry.options or entry.data)}
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", private=True)
        self.ledger = Ledger()
        self.lock = asyncio.Lock()
        self.unsubscribers = []
        self.stopping = False

    async def async_start(self):
        self.ledger = Ledger(await self.store.async_load())
        await self.async_tick()

        @callback
        def changed(event):
            self.hass.async_create_task(self.async_tick())

        self.unsubscribers.append(
            async_track_state_change_event(self.hass, [self.config["power_sensor"]], changed)
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
        self.ledger.advance(
            now, watts, self.config, dt_util.DEFAULT_TIME_ZONE, valid_previous=fresh
        )

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
        if not self.config["control_switch"]:
            return
        desired = "on" if in_window(dt_util.as_local(now), self.config) else "off"
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
        temporary.write_text(invoice_html(invoice), encoding="utf-8")
        temporary.replace(path)

    async def _send(self, period):
        invoice = self.ledger.data["invoices"][period]
        # Mark before sending: an interrupted/uncertain attempt is never retried
        # automatically, because the mail server may already have accepted it.
        self.ledger.data["delivery"][period] = "sending"
        await self.store.async_save(self.ledger.data)
        try:
            await self.hass.async_add_executor_job(send_invoice, self.config, invoice)
        except (OSError, smtplib.SMTPException, ValueError):
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
