"""UI configuration and editable billing options."""

from datetime import time
from decimal import InvalidOperation

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .billing import decimal
from .const import DEFAULTS, DOMAIN
from .mail import validate_mail


def schema(values):
    def default(key):
        return values.get(key, DEFAULTS.get(key, ""))

    fields = {}
    for key in ("name", "customer", "seller", "payment_instructions"):
        fields[vol.Required(key, default=default(key))] = selector.TextSelector(
            selector.TextSelectorConfig(multiline=key != "name")
        )
    power_key = (
        vol.Required("power_sensor", default=values["power_sensor"])
        if values.get("power_sensor")
        else vol.Required("power_sensor")
    )
    fields[power_key] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="power")
    )
    switch_key = (
        vol.Optional("charger_switch", default=values["charger_switch"])
        if values.get("charger_switch")
        else vol.Optional("charger_switch")
    )
    fields[switch_key] = selector.EntitySelector(selector.EntitySelectorConfig(domain="switch"))
    fields[vol.Required("smtp_provider", default=default("smtp_provider"))] = (
        selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["none", "custom", "gmail"], translation_key="smtp_provider"
            )
        )
    )
    for key in ("smtp_host", "smtp_username", "smtp_password", "smtp_sender", "customer_email"):
        fields[vol.Optional(key, default=default(key))] = selector.TextSelector(
            selector.TextSelectorConfig(type="password" if key == "smtp_password" else "text")
        )
    fields[vol.Required("smtp_port", default=default("smtp_port"))] = vol.All(
        vol.Coerce(int), vol.Range(min=1, max=65535)
    )
    fields[vol.Required("smtp_security", default=default("smtp_security"))] = (
        selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["starttls", "tls"], translation_key="smtp_security"
            )
        )
    )
    fields[vol.Required("schedule_mode", default=default("schedule_mode"))] = (
        selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=["all_day", "window"], translation_key="schedule_mode"
            )
        )
    )
    for key in ("start_time", "end_time"):
        fields[vol.Required(key, default=default(key))] = selector.TimeSelector()
    for key in ("control_switch", "auto_email"):
        fields[vol.Required(key, default=default(key))] = selector.BooleanSelector()
    for key in ("currency", "rate", "fixed_fee", "tax_percent"):
        fields[vol.Required(key, default=default(key))] = selector.TextSelector()
    fields[vol.Required("max_age", default=default("max_age"))] = vol.All(
        vol.Coerce(int), vol.Range(min=30, max=86400)
    )
    return vol.Schema(fields)


def validate(hass, data, entry_id=None):
    """Validate selections and prevent accidental double billing/control."""
    for key in ("rate", "fixed_fee", "tax_percent"):
        if decimal(data[key]) < 0:
            raise ValueError("Negative billing value")
    if decimal(data["tax_percent"]) > 100:
        raise ValueError("Tax must be between 0 and 100")
    if (
        len(data["currency"]) != 3
        or not data["currency"].isascii()
        or not data["currency"].isalpha()
    ):
        raise ValueError("Use a three-letter currency code")
    data["currency"] = data["currency"].upper()
    for key in ("start_time", "end_time"):
        parsed = time.fromisoformat(data[key])
        if parsed.second or parsed.microsecond:
            raise ValueError("Schedule uses whole minutes")
    state = hass.states.get(data["power_sensor"])
    if state is None or state.attributes.get("unit_of_measurement") not in ("W", "kW"):
        raise ValueError("Select an existing W or kW power sensor")
    if data["control_switch"] and not data.get("charger_switch"):
        raise ValueError("Select a switch before enabling control")
    if data.get("smtp_provider") == "none":
        data["auto_email"] = False
    elif data["auto_email"]:
        validate_mail(data)
    if data.get("charger_switch"):
        if (
            not data["charger_switch"].startswith("switch.")
            or hass.states.get(data["charger_switch"]) is None
        ):
            raise ValueError("Select an existing switch")
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and data["currency"] != (entry.options or entry.data)["currency"]:
            raise ValueError("Currency cannot change on an existing billing account")
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            continue
        other = entry.options or entry.data
        if other["power_sensor"] == data["power_sensor"]:
            raise ValueError("This sensor is already assigned")
        if (
            data["control_switch"]
            and other.get("control_switch")
            and data["charger_switch"] == other.get("charger_switch")
        ):
            raise ValueError("This switch is already controlled")


class EVBillingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                validate(self.hass, user_input)
            except (ValueError, InvalidOperation):
                errors["base"] = "invalid_config"
            else:
                return self.async_create_entry(title=user_input["name"], data=user_input)
        return self.async_show_form(
            step_id="user", data_schema=schema(user_input or {}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EVBillingOptionsFlow()


class EVBillingOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                validate(self.hass, user_input, self.config_entry.entry_id)
            except (ValueError, InvalidOperation):
                errors["base"] = "invalid_config"
            else:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=schema(user_input or self.config_entry.options or self.config_entry.data),
        )
