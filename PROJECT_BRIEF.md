# EV ChargePoint for Home Assistant

Status: initial integration implemented as EV ChargePoint. Repository:
https://github.com/wholly1971/ha-ev-chargepoint. See README.md for implemented
behavior and limits. Live Home Assistant and SMTP validation remains required.

## Purpose

A HACS-installable Home Assistant integration for EV charging that measures electricity use,
applies billing rates during configured on/off periods, creates a monthly
customer invoice, and emails it to the customer.

Confirmed context: https://github.com/NaanyaBiz/haggle is the user's Haggle
integration. Billing uses only a user-selected, dedicated EV power sensor,
not whole-property consumption. Configure its entity ID in Home Assistant;
do not hard-code it or assume Haggle exposes live charger power.
Integrate W/kW readings over time into kWh. Missing readings and Home Assistant
downtime must be flagged as gaps rather than charged as assumed consumption.

## Proposed first release

- Set up each customer and their meter through the Home Assistant UI.
- Select an energy sensor (kWh/Wh), or a power sensor (W/kW) whose readings
  are integrated over time. Prefer a cumulative energy meter where available.
- Configure billable time windows, including windows that cross midnight.
- Optionally control an existing Home Assistant switch on a schedule if requested.
- Configure currency, energy tariff, fixed fees, tax, and billing date.
- Show current-period energy use and estimated charges as Home Assistant entities.
- Keep a persistent usage ledger and immutable, uniquely numbered monthly invoices.
- Generate a downloadable invoice and send it through a configured email service.
- Record email delivery attempts separately from invoice creation so retries
  do not create duplicate invoices.

## Accounting and reliability requirements

- Use decimal arithmetic for money and explicit rounding rules.
- Preserve customer, tariff, and billing details on each issued invoice.
- Apply tariff changes prospectively; do not rewrite issued invoices.
- Handle restarts, unavailable readings, meter resets, and month boundaries.
- Flag missing or ambiguous meter data for review instead of silently inventing usage.
- Use Home Assistant's configured local timezone for schedules and billing periods.
- Keep customer details, credentials, readings, and invoices out of GitHub.
- Test billing boundaries, overnight schedules, restarts, and invoice retry behavior.

## Decisions needed

All selections are configurable through Home Assistant. Initial scope uses one
daily window, one price per kWh, and calendar-month invoices issued on the first
sample after month end. Email uses a selected SMTP recipient entity. Invoices
are printable HTML plus plain-text email. Payment collection is out of scope.

1. Dedicated EV power sensor confirmed; entity ID will be configured in the UI.
2. Whether on/off times control equipment, define billable windows, or both.
3. Customer count and whether each customer has a dedicated meter.
4. Currency, tariff structure, fixed fees, tax, and billing date.
5. Existing sensor units and email service.
6. Seller details, customer details, invoice format, and payment instructions.
7. Whether collecting payment is required in addition to issuing an invoice.
8. GitHub repository name and destination account.

## References

- HACS integration packaging: https://www.hacs.dev/docs/publish/integration/
- Home Assistant sensor entities: https://developers.home-assistant.io/docs/core/entity/sensor/
- Home Assistant SMTP integration: https://www.home-assistant.io/integrations/smtp/
