"""UI configuration and editable billing options."""

from datetime import time
from decimal import InvalidOperation

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .billing import decimal
from .const import DEFAULTS, DOMAIN, TARIFF_BANDS, INVOICE_BILLING_OPTIONS
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
        if key in ("rate", "fixed_fee"):
            flag = key + "_includes_gst"
            fields[vol.Required(flag, default=default(flag))] = selector.BooleanSelector()
    fields[vol.Required("max_age", default=default("max_age"))] = vol.All(
        vol.Coerce(int), vol.Range(min=30, max=86400)
    )
    for key in ("agl_rate_sensor", "agl_supply_sensor", "agl_feed_in_sensor"):
        marker = vol.Optional(key, default=values[key]) if values.get(key) else vol.Optional(key)
        fields[marker] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    fields[vol.Required("use_tariff_bands", default=default("use_tariff_bands"))] = selector.BooleanSelector()
    fields[vol.Required("billing_scope", default=default("billing_scope"))] = selector.SelectSelector(
        selector.SelectSelectorConfig(options=["scheduled", "all_time"], translation_key="billing_scope"))
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
    return {key: value for key, value in values.items() if key not in (*EMAIL_KEYS, "invoice_billing_option") and not key.startswith("tariff_") and key != "sensor_rate_tax_percent"}


def tariff_schema(values):
    fields = {}
    for band in TARIFF_BANDS:
        prefix = "tariff_" + band + "_"
        for suffix in ("enabled", "start", "end", "rate", "rate_includes_gst", "sensor_includes_tax"):
            key = prefix + suffix
            marker = vol.Required(key, default=values.get(key, DEFAULTS[key]))
            if suffix in ("enabled", "rate_includes_gst", "sensor_includes_tax"):
                fields[marker] = selector.BooleanSelector()
            elif suffix in ("start", "end"):
                fields[marker] = selector.TimeSelector()
            else:
                fields[marker] = selector.TextSelector()
        key = prefix + "sensor"
        marker = vol.Optional(key, default=values[key]) if values.get(key) else vol.Optional(key)
        fields[marker] = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    fields[vol.Required("sensor_rate_tax_percent", default=values.get("sensor_rate_tax_percent", "10"))] = selector.TextSelector()
    return vol.Schema(fields)


def validate_tariffs(hass, data):
    if not data.get("use_tariff_bands"):
        return
    try:
        if not 0 <= decimal(data.get("sensor_rate_tax_percent", "10")) <= 100:
            raise ValueError("Invalid tax")
    except (ValueError, InvalidOperation) as exc:
        raise ConfigValidationError("sensor_rate_tax_percent", "invalid_tax") from exc
    occupied = set()
    for band in TARIFF_BANDS:
        prefix = "tariff_" + band + "_"
        if not data.get(prefix + "enabled"):
            continue
        if data.get(prefix + "rate_includes_gst") and decimal(data.get("tax_percent", "0")) <= 0:
            raise ConfigValidationError(prefix + "rate_includes_gst", "gst_rate_required")
        minutes = []
        for suffix in ("start", "end"):
            key = prefix + suffix
            try:
                parsed = time.fromisoformat(data[key])
                if parsed.tzinfo is not None:
                    raise ValueError("Local time required")
                data[key] = parsed.replace(second=0, microsecond=0).isoformat()
                minutes.append(parsed.hour * 60 + parsed.minute)
            except (ValueError, TypeError, KeyError) as exc:
                raise ConfigValidationError(key, "invalid_time") from exc
        start, end = minutes
        if start == end:
            raise ConfigValidationError(prefix + "end", "empty_tariff_window")
        covered = set(range(start, end)) if start < end else set(range(start, 1440)) | set(range(end))
        if occupied & covered:
            raise ConfigValidationError(prefix + "start", "overlapping_tariffs")
        occupied |= covered
        try:
            if decimal(data[prefix + "rate"]) < 0:
                raise ValueError("Negative rate")
        except (ValueError, InvalidOperation, KeyError) as exc:
            raise ConfigValidationError(prefix + "rate", "invalid_amount") from exc
        entity_id = data.get(prefix + "sensor")
        if entity_id:
            state = hass.states.get(entity_id)
            if state is None or state.attributes.get("unit_of_measurement") != data["currency"] + "/kWh":
                raise ConfigValidationError(prefix + "sensor", "invalid_rate_sensor")


class EmailFlowMixin:
    """Stage provider selection before requesting provider-specific credentials."""

    async def async_step_tariffs(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._values.update(user_input)
            try:
                validate_tariffs(self.hass, self._values)
            except ConfigValidationError as exc:
                errors[exc.field] = exc.code
            else:
                if self._values["smtp_provider"] != "none":
                    return await self.async_step_email()
                self._values["auto_email"] = False
                return await self.async_step_invoice_billing()
        return self.async_show_form(step_id="tariffs", data_schema=tariff_schema(self._values), errors=errors)

    async def async_step_email(self, user_input=None):
        errors = {}
        if user_input is not None:
            self._values.update(user_input)
            try:
                validate(self.hass, self._values, self._entry_id)
            except ConfigValidationError as exc:
                errors["base" if exc.field == "auto_email" else exc.field] = exc.code
            else:
                return await self.async_step_invoice_billing()
        provider = self._values["smtp_provider"]
        return self.async_show_form(
            step_id="email_" + provider,
            data_schema=email_schema(self._values, self.hass),
            errors=errors,
        )

    async def async_step_invoice_billing(self, user_input=None):
        """One presentation setting shared by local invoices and every provider."""
        errors = {}
        if user_input is not None:
            choice = user_input.get("invoice_billing_option")
            if choice not in INVOICE_BILLING_OPTIONS:
                errors["invoice_billing_option"] = "invalid_invoice_option"
            else:
                self._values["invoice_billing_option"] = choice
                return self.async_create_entry(
                    title=self._values["name"] if self._entry_id is None else "", data=self._values)
        return self.async_show_form(step_id="invoice_billing", data_schema=vol.Schema({
            vol.Required("invoice_billing_option", default=self._values.get("invoice_billing_option", "itemised")):
                selector.SelectSelector(selector.SelectSelectorConfig(
                    options=list(INVOICE_BILLING_OPTIONS), translation_key="invoice_billing_option"))
        }), errors=errors)

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
    validate_tariffs(hass, data)
    if data.get("invoice_billing_option", "itemised") not in INVOICE_BILLING_OPTIONS:
        raise ConfigValidationError("invoice_billing_option", "invalid_invoice_option")
    for key in ("rate", "fixed_fee", "tax_percent"):
        try:
            if decimal(data[key]) < 0:
                raise ValueError("Negative billing value")
        except (ValueError, InvalidOperation) as exc:
            raise ConfigValidationError(key, "invalid_amount") from exc
    if decimal(data["tax_percent"]) > 100:
        raise ConfigValidationError("tax_percent", "invalid_tax")
    inclusive = data.get("rate_includes_gst") or data.get("fixed_fee_includes_gst") or any(
        data.get("use_tariff_bands") and data.get(f"tariff_{band}_enabled") and data.get(f"tariff_{band}_rate_includes_gst")
        for band in TARIFF_BANDS)
    if inclusive and decimal(data["tax_percent"]) <= 0:
        raise ConfigValidationError("tax_percent", "gst_rate_required")
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
                if self._values.get("use_tariff_bands"):
                    return await self.async_step_tariffs()
                if self._values["smtp_provider"] != "none":
                    return await self.async_step_email()
                self._values["auto_email"] = False
                return await self.async_step_invoice_billing()
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
                if self._values.get("use_tariff_bands"):
                    return await self.async_step_tariffs()
                if self._values["smtp_provider"] != "none":
                    return await self.async_step_email()
                self._values["auto_email"] = False
                return await self.async_step_invoice_billing()
        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=schema(user_input or self.config_entry.options or self.config_entry.data, self.hass),
        )
