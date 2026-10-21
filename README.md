# EV ChargePoint

Home Assistant custom integration for scheduled EV charging, electricity charges,
and monthly customer invoices. Install as a HACS custom repository.

**Initial version: live Home Assistant and SMTP testing is still required.**

## Configure everything in Home Assistant

Add one integration instance per customer/charger. Select:

- A dedicated EV **power sensor** reporting W or kW.
- Optional charger switch and automatic schedule control (disabled by default).
- All-day billing or one daily time window, including overnight windows.
- Currency, price per kWh, monthly fixed fee, and tax percentage.
- Customer and seller details, including addresses/tax identifiers if needed.
- Payment instructions.
- Optional SMTP recipient entity and automatic monthly email (disabled by default).
- Maximum acceptable age of power readings, default 300 seconds.

All settings can be changed through **Settings → Devices & services → EV ChargePoint
→ Configure**. Default rate AUD 0.30/kWh is an example; replace it with your rate.
Rates and fixed fees are tax-exclusive. Currency uses two decimal places.

Haggle can remain installed for AGL history. EV ChargePoint reads the selected live
EV power entity; it does not read Haggle's external whole-property statistics or
access AGL credentials. The selected sensor must specifically measure the EV load.

## Installation

Requires Home Assistant 2026.10 or later.

1. In HACS, open **Custom repositories**.
2. Add `https://github.com/wholly1971/ha-ev-chargepoint` with category **Integration**.
3. Download **EV ChargePoint** and restart Home Assistant.
4. Add **EV ChargePoint** from Settings → Devices & services → Add integration.
5. For emails, first configure Home Assistant's **SMTP** integration and add the
   customer as a recipient. Select the resulting `notify` entity in EV ChargePoint.

Manual installation: copy `custom_components/ev_chargepoint` into your Home Assistant
configuration's `custom_components` directory, restart, and add the integration.

## How measurement and schedules work

The integration integrates the last observed power over elapsed time (a
left-hand sum), samples at state changes and every 30 seconds, and stores its
ledger after each sample. This is an estimate based on the sensor's reporting
frequency, not a replacement for a dedicated certified energy meter.

Only electricity inside the configured window is billed. Switch control is a
separate option: when enabled, the integration enforces on inside the window and
off outside it, including on startup. All-day mode forces the switch on.
Switch changes take up to 30 seconds. Use the charger's supported control entity.
Equal start/end times mean all day. Schedule precision is one minute, every day;
multiple windows, weekday schedules, and peak/off-peak tariff bands are not yet supported.

The selected sensor's last report must be recent, its units W/kW, and its value
finite and nonnegative. Outages, stale readings, and Home Assistant downtime
become gaps, not invented usage. No historical backfill is attempted. A complete
Home Assistant outage can also prevent scheduled switch control.

## Monthly invoices

Billing periods are calendar months in Home Assistant's local timezone. The
first sample after the month ends creates the invoice. The starting month is
always marked partial. Invoices for incomplete months are withheld until you
press **Approve all incomplete completed months**. This issues every withheld
completed month using only recorded usage, so review the status sensor first.
If automatic email is enabled, approval also sends those invoices.

Three entities show monthly billable kWh, monthly charge including fee/tax,
and billing status. The status attributes show missing-data seconds by month
and invoice email states. Fees apply once per tracked month; no proration.
Periods entirely outside the billable window are not created. Months with
missing data need approval even if measured consumption is zero.

Invoices contain a stable identifier, monthly period, seller/customer details,
kWh grouped by tariff, fee, subtotal, tax, total, and payment instructions.
Tariff changes apply to future measured intervals. The fixed fee, tax,
currency and customer details use the last configuration recorded in that month;
currency changes within a month are not supported. Issued invoices retain their
snapshot and are never recalculated. To change the customer or currency, create
a new instance with a different sensor after retiring the old instance.

Printable HTML invoices are saved under:

```text
<config>/ev_chargepoint_invoices/<entry_id>/YYYY-MM.html
```

Open these files from your Home Assistant configuration storage and use the
browser's Print → Save as PDF if needed. Files are deliberately outside `www`
and are not exposed as unauthenticated web links. Emails contain the complete
invoice in plain text; PDF attachments and online payment collection are not
included in this version.

Email state `submitted` means the SMTP action returned successfully, not proof
of delivery to the recipient. Failed or interrupted (`sending`) attempts are
not automatically retried. **Retry pending or uncertain invoice emails** retries
all pending/failed/uncertain emails even if automatic email is disabled. Check
the mailbox before retrying uncertain sends, since they may have arrived.
The email target is saved with the invoice, so a later customer change cannot
redirect old invoices. If that SMTP entity is deleted, restore it before retrying.

## Storage and removal

The ledger, invoice snapshots and delivery status live in Home Assistant's
`.storage/ev_chargepoint.<entry_id>`. Include that file and `ev_chargepoint_invoices` in
your backups. Configuration contains private customer details: do not upload
Home Assistant configuration or generated invoices to GitHub.
Removing the integration stops tracking/control but retains billing files for
your records. Export those records before manually removing them. Do not delete
an instance just to change a tariff; use Configure instead.

## Development

```sh
python -m unittest discover -s tests -v
python -m compileall -q custom_components
ruff check .
```

GitHub Actions also runs HACS validation and hassfest. Brand validation is
excluded until a brand icon is added; this project is a custom repository, not a
submission to the HACS default catalogue.

Before customer use, test in Home Assistant: configuration/options, W and kW
sensors, restarts, switch schedule and failures, a completed month, incomplete
month approval, SMTP success/failure/uncertain retry, and backup restoration.

References: [HACS packaging](https://www.hacs.dev/docs/publish/integration/),
[SMTP setup](https://www.home-assistant.io/integrations/smtp/).
