"""Billing totals and review status."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .reporting import ledger_summary
from .pricing import pricing_snapshot
from .tariffs import tariff_config, current_charge_rate


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(BillingSensor(entry, kind) for kind in ("energy", "cost", "status", "rate"))


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
            "rate": "Current charge rate",
        }[kind]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "EV ChargePoint",
        }
        if kind == "rate":
            self._attr_native_unit_of_measurement = self.coordinator.config["currency"] + "/kWh"
            self._attr_suggested_display_precision = 4
        elif kind == "energy":
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_device_class = SensorDeviceClass.ENERGY
        elif kind == "cost":
            self._attr_native_unit_of_measurement = self.coordinator.config["currency"]
            self._attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self):
        if self.kind == "rate":
            return float(current_charge_rate(self.hass, self.coordinator.config, dt_util.now())["including_tax"])
        ledger = self.coordinator.ledger
        period = dt_util.now().strftime("%Y-%m")
        bucket = ledger.data["months"].get(period)
        if self.kind == "energy":
            return round(float(bucket["kwh"]), 6) if bucket else 0
        if self.kind == "cost":
            return ledger.totals(period)[2] if bucket else "0.00"
        if any(p < period and p not in ledger.data["invoices"] for p in ledger.data["months"]):
            return "review_required"
        if self.coordinator.config.get("smtp_provider") != "none" and any(
            status in ("failed", "sending") for status in ledger.data["delivery"].values()
        ):
            return "email_attention"
        return "tracking" if ledger.watts is not None else "meter_unavailable"

    @property
    def extra_state_attributes(self):
        if self.kind == "rate":
            return current_charge_rate(self.hass, self.coordinator.config, dt_util.now())
        if self.kind != "status":
            return None
        return {
            **ledger_summary(self.coordinator.ledger),
            "email_test": dict(self.coordinator.email_test),
            "email_provider": self.coordinator.config.get("smtp_provider", "none"),
            "automatic_email": self.coordinator.config.get("auto_email", False),
            "invoice_rate": self.coordinator.config["rate"],
            "current_charge_rate": current_charge_rate(self.hass, self.coordinator.config, dt_util.now()),
            "charge_control": {"mode": self.coordinator.charge_mode,
                               "entity_id": self.coordinator.charge_mode_entity_id,
                               "override_until": self.coordinator.override_until.isoformat() if self.coordinator.override_until else None,
                               "schedule_control_enabled": self.coordinator.config["control_switch"]},
            "billing_scope": self.coordinator.config.get("billing_scope", "scheduled"),
            "tariff_config": tariff_config(self.hass, self.coordinator.config),
            "tax_percent": self.coordinator.config["tax_percent"],
            "agl_pricing": pricing_snapshot(self.hass, self.coordinator.config),
        }
