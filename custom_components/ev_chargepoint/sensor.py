"""Billing totals and review status."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(BillingSensor(entry, kind) for kind in ("energy", "cost", "status"))


class BillingSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, entry, kind):
        super().__init__(entry.runtime_data)
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_name = {
            "energy": "Monthly billable energy",
            "cost": "Monthly charge",
            "status": "Billing status",
        }[kind]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "EV ChargePoint",
        }
        if kind == "energy":
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_device_class = SensorDeviceClass.ENERGY
        elif kind == "cost":
            self._attr_native_unit_of_measurement = self.coordinator.config["currency"]
            self._attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        ledger = self.coordinator.ledger
        period = dt_util.now().strftime("%Y-%m")
        bucket = ledger.data["months"].get(period)
        if self.kind == "energy":
            return round(float(bucket["kwh"]), 6) if bucket else 0
        if self.kind == "cost":
            return ledger.totals(period)[2] if bucket else "0.00"
        if any(p < period and p not in ledger.data["invoices"] for p in ledger.data["months"]):
            return "review_required"
        if any(status in ("failed", "sending") for status in ledger.data["delivery"].values()):
            return "email_attention"
        return "tracking" if ledger.watts is not None else "meter_unavailable"

    @property
    def extra_state_attributes(self):
        if self.kind != "status":
            return None
        data = self.coordinator.ledger.data
        return {
            "invoice_delivery": dict(data["delivery"]),
            "months": {
                period: {"gap_seconds": bucket["gap_seconds"], "partial": bucket["partial"]}
                for period, bucket in data["months"].items()
            },
        }
