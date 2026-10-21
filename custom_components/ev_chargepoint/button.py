"""Explicit invoice approval and email retry actions."""

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(BillingButton(entry, kind) for kind in ("approve", "retry"))


class BillingButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, kind):
        self.runtime = entry.runtime_data
        self.kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_name = (
            "Approve all incomplete completed months"
            if kind == "approve"
            else "Retry pending or uncertain invoice emails"
        )
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}

    async def async_press(self):
        if self.kind == "approve":
            await self.runtime.async_approve()
        else:
            await self.runtime.async_retry()
