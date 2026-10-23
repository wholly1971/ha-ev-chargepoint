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
from .gmail import resolve_gmail, validate_recipient


def schema(values, hass=None):
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
                options=["none", "gmail_oauth", "custom", "gmail"], translation_key="smtp_provider"
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
    for key in ("agl_rate_sensor", "agl_supply_sensor", "agl_feed_in_sensor"):
        marker = vol.Optional(key, default=values[key]) if values.get(key) else vol.Optional(key)
        fields[marker] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    return vol.Schema(fields)


EMAIL_KEYS = ("gmail_account", "smtp_host", "smtp_username", "smtp_password", "smtp_sender",
              "customer_email", "smtp_port", "smtp_security")


def email_schema(values, hass):
    """Show only fields used by the selected delivery method."""
    def default(key):
        return values.get(key, DEFAULTS.get(key, ""))

    fields = {}
    accounts = [{"value": "", "label": "Default connected Gmail account (one account only)"}]
    if hass is not None:
        accounts.extend(
            {"value": entry.entry_id, "label": entry.title}
            for entry in hass.config_entries.async_entries("google_mail")
        )
    # Retain a disconnected selection so editing unrelated settings is possible.
    saved = default("gmail_account")
    if saved and not any(option["value"] == saved for option in accounts):
        accounts.append({"value": saved, "label": "Previously selected Gmail (reconnect account)"})
    fields[vol.Optional("gmail_account", default=saved)] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=accounts)
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
    provider = values.get("smtp_provider")
    keys = {"customer_email"}
    if provider == "gmail_oauth":
        keys.add("gmail_account")
    else:
        keys.update(("smtp_username", "smtp_password", "smtp_sender"))
        if provider == "custom":
            keys.update(("smtp_host", "smtp_port", "smtp_security"))
    return vol.Schema({key: value for key, value in fields.items() if key.schema in keys})


def main_values(values):
    return {key: value for key, value in values.items() if key not in EMAIL_KEYS}


class EmailFlowMixin:
    """Stage provider selection before requesting provider-specific credentials."""

    async def async_step_email(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._values.update(user_input)
            try:
                validate(self.hass, self._values, self._entry_id)
            except ConfigValidationError as exc:
                errors["base" if exc.field == "auto_email" else exc.field] = exc.code
            else:
                return self.async_create_entry(
                    title=self._values["name"] if self._entry_id is None else "",
                    data=self._values,
                )
        provider = self._values["smtp_provider"]
        return self.async_show_form(
            step_id="email_" + provider,
            data_schema=email_schema(self._values, self.hass),
            errors=errors,
        )

    async def async_step_email_gmail(self, user_input=None):
        return await self.async_step_email(user_input)

    async def async_step_email_gmail_oauth(self, user_input=None):
        return await self.async_step_email(user_input)

    async def async_step_email_custom(self, user_input=None):
        return await self.async_step_email(user_input)


class ConfigValidationError(ValueError):
    """An actionable form error attached to the field that needs attention."""

    def __init__(self, field, code):
        self.field = field
        self.code = code
        super().__init__(code)


def validate(hass, data, entry_id=None):
    """Validate selections and prevent accidental double billing/control."""
    for key in ("rate", "fixed_fee", "tax_percent"):
        try:
            if decimal(data[key]) < 0:
                raise ValueError("Negative billing value")
        except (ValueError, InvalidOperation) as exc:
            raise ConfigValidationError(key, "invalid_amount") from exc
    if decimal(data["tax_percent"]) > 100:
        raise ConfigValidationError("tax_percent", "invalid_tax")
    data["currency"] = data["currency"].strip().upper()
    if (
        len(data["currency"]) != 3
        or not data["currency"].isascii()
        or not data["currency"].isalpha()
    ):
        raise ConfigValidationError("currency", "invalid_currency")
    data["currency"] = data["currency"].upper()
    for key in ("start_time", "end_time"):
        try:
            parsed = time.fromisoformat(data[key])
            if parsed.tzinfo is not None:
                raise ValueError("Use a local time")
        except (TypeError, ValueError) as exc:
            raise ConfigValidationError(key, "invalid_time") from exc
        # Billing and switch control both operate at minute precision. The HA
        # time selector accepts seconds, so normalize instead of rejecting it.
        data[key] = parsed.replace(second=0, microsecond=0).isoformat()
    state = hass.states.get(data["power_sensor"])
    if state is None or state.attributes.get("unit_of_measurement") not in ("W", "kW"):
        raise ConfigValidationError("power_sensor", "invalid_power_sensor")
    if data["control_switch"] and not data.get("charger_switch"):
        raise ConfigValidationError("charger_switch", "switch_required")
    if data.get("smtp_provider") == "none":
        data["auto_email"] = False
    elif data["auto_email"]:
        try:
            if data.get("smtp_provider") == "gmail_oauth":
                resolve_gmail(hass, data.get("gmail_account", ""))
                validate_recipient(data.get("customer_email", ""))
            else:
                validate_mail(data)
        except ValueError as exc:
            raise ConfigValidationError("auto_email", "invalid_email_" + data.get("smtp_provider", "custom")) from exc
    if data.get("charger_switch"):
        if (
            not data["charger_switch"].startswith("switch.")
            or hass.states.get(data["charger_switch"]) is None
        ):
            raise ConfigValidationError("charger_switch", "invalid_switch")
    if entry_id:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and data["currency"] != (entry.options or entry.data)["currency"]:
            raise ConfigValidationError("currency", "currency_locked")
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == entry_id:
            continue
        other = entry.options or entry.data
        if other["power_sensor"] == data["power_sensor"]:
            raise ConfigValidationError("power_sensor", "sensor_assigned")
        if (
            data["control_switch"]
            and other.get("control_switch")
            and data["charger_switch"] == other.get("charger_switch")
        ):
            raise ConfigValidationError("charger_switch", "switch_assigned")


class EVBillingConfigFlow(EmailFlowMixin, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                staged = {**DEFAULTS, **user_input, "auto_email": False}
                validate(self.hass, staged)
            except ConfigValidationError as exc:
                errors[exc.field] = exc.code
            except (ValueError, InvalidOperation):
                errors["base"] = "invalid_config"
            else:
                self._entry_id = None
                self._values = {**staged, "auto_email": user_input["auto_email"]}
                if self._values["smtp_provider"] != "none":
                    return await self.async_step_email()
                self._values["auto_email"] = False
                return self.async_create_entry(title=user_input["name"], data=self._values)
        return self.async_show_form(
            step_id="user", data_schema=schema(user_input or {}, self.hass), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EVBillingOptionsFlow()


class EVBillingOptionsFlow(EmailFlowMixin, config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                staged = {**DEFAULTS, **(self.config_entry.options or self.config_entry.data), **user_input, "auto_email": False}
                validate(self.hass, staged, self.config_entry.entry_id)
            except ConfigValidationError as exc:
                errors[exc.field] = exc.code
            except (ValueError, InvalidOperation):
                errors["base"] = "invalid_config"
            else:
                self._entry_id = self.config_entry.entry_id
                self._values = {**staged, "auto_email": user_input["auto_email"]}
                if self._values["smtp_provider"] != "none":
                    return await self.async_step_email()
                self._values["auto_email"] = False
                return self.async_create_entry(title="", data=self._values)
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=schema(user_input or self.config_entry.options or self.config_entry.data, self.hass),
        )
