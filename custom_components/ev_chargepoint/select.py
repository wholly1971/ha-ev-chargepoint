"""Manual charging overrides coordinated with automatic scheduling."""

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from .billing import decimal
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ChargingMode(entry), BillingPeriod(entry)])


PERIOD_OPTIONS = {"Each charge": "each_charge", "Daily": "daily", "Weekly": "weekly", "Monthly": "monthly"}


class BillingPeriod(CoordinatorEntity, SelectEntity):
    """Native portal control; updates the same options as the configuration form."""
    _attr_has_entity_name = True
    _attr_name = "Billing period"
    _attr_icon = "mdi:calendar-clock"
    _attr_options = list(PERIOD_OPTIONS)

    def __init__(self, entry):
        super().__init__(entry.runtime_data)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_billing_period"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.coordinator.billing_period_entity_id = self.entity_id
        self.coordinator.async_set_updated_data(self.coordinator.ledger.data)

    @property
    def current_option(self):
        return next(label for label, mode in PERIOD_OPTIONS.items()
                    if mode == self.coordinator.config.get("billing_period", "monthly"))

    async def async_select_option(self, option):
        if option not in PERIOD_OPTIONS:
            raise HomeAssistantError("Invalid billing period")
        if option == "Each charge" and decimal(self.coordinator.config.get("fixed_fee", 0)):
            raise HomeAssistantError("Each-charge billing requires a zero monthly fixed fee")
        if option == self.current_option:
            return
        async with self.coordinator.lock:
            self.coordinator._sample(dt_util.utcnow())
            await self.coordinator.store.async_save(self.coordinator.ledger.data)
            self.hass.config_entries.async_update_entry(self.entry, options={
                **(self.entry.options or self.entry.data), "billing_period": PERIOD_OPTIONS[option]})


class ChargingMode(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Charging mode"
    _attr_icon = "mdi:ev-station"
    _attr_options = ["Automatic schedule", "Manual charging on", "Manual charging off"]

    def __init__(self, entry):
        super().__init__(entry.runtime_data)
        self._attr_unique_id = f"{entry.entry_id}_charge_mode"
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.coordinator.charge_mode_entity_id = self.entity_id
        self.coordinator.async_set_updated_data(self.coordinator.ledger.data)

    @property
    def current_option(self):
        return self.coordinator.charge_mode

    @property
    def extra_state_attributes(self):
        until = self.coordinator.override_until
        return {"override_until": until.isoformat() if until else None}

    async def async_select_option(self, option):
        await self.coordinator.async_set_charge_mode(option)
