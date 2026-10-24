"""Manual charging overrides coordinated with automatic scheduling."""

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ChargingMode(entry)])


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
