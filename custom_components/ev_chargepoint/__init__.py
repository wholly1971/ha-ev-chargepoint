"""EV ChargePoint integration lifecycle."""

from homeassistant.const import Platform

from .runtime import BillingRuntime

PLATFORMS = [Platform.SENSOR, Platform.BUTTON, Platform.SELECT]


async def async_setup_entry(hass, entry):
    from .websocket import async_register

    async_register(hass)
    runtime = BillingRuntime(hass, entry)
    entry.runtime_data = runtime
    await runtime.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    return True


async def async_options_updated(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
        return True
    return False
