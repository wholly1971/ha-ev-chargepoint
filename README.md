# EV ChargePoint

<p align="center">
  <img src="assets/ev-chargepoint-logo.png" alt="EV ChargePoint logo" width="420">
</p>

Home Assistant custom integration for scheduled EV charging, electricity charges,
and monthly customer invoices. Install as a HACS custom repository.

**Current release: 0.3.0.** See [release notes](CHANGELOG.md). Live Gmail/SMTP
delivery testing is still required before customer use.

Install a numbered release in HACS, rather than `main` or a commit hash, for
readable installed/latest versions. When switching an existing branch install,
open EV ChargePoint in HACS, choose **Redownload → 0.3.0**, then restart Home
Assistant after the download completes. Do not repeatedly reinstall while the
restart-required banner is shown.

## Configure everything in Home Assistant

Add one integration instance per customer/charger. Select:

- A dedicated EV **power sensor** reporting W or kW.
- Optional charger switch and automatic schedule control (disabled by default).
- All-day billing or one daily time window, including overnight windows.
- Currency, price per kWh, monthly fixed fee, and tax percentage.
- Customer and seller details, including addresses/tax identifiers if needed.
- Payment instructions.
- No email (local invoices only), Gmail, or a custom SMTP server; automatic email is disabled by default.
- Maximum acceptable age of power readings, default 300 seconds.

Create entries through **Settings → Devices & services → Integrations → Add
integration → EV ChargePoint**. EV ChargePoint is a service integration and is
not created through the Helpers tab. Add one entry per customer/charger.
Change an existing entry through **Settings → Devices & services → Integrations
→ EV ChargePoint → Configure**. Default rate AUD 0.30/kWh is an example; replace it with your rate.
Rates and fixed fees are tax-exclusive. Currency uses two decimal places.

Haggle can remain installed for AGL history. EV ChargePoint reads the selected live
EV power entity; it does not read Haggle's external whole-property statistics or
access AGL credentials. The selected sensor must specifically measure the EV load.

## Installation

Requires Home Assistant 2026.10 or later.

1. In HACS, open **Custom repositories**.
2. Add `https://github.com/wholly1971/ha-ev-chargepoint` with category **Integration**.
3. Download **EV ChargePoint** and restart Home Assistant.
4. Add **EV ChargePoint** from Settings → Devices & services → Integrations → Add integration.
5. For emails, enter the SMTP hostname, port, security, login, sender address,
   and customer email directly in EV ChargePoint. No separate SMTP integration
   or notification entity is needed. Use STARTTLS (usually 587) or TLS (usually
   465). Passwords use a masked field and remain in Home Assistant configuration;
   SMTP credentials are excluded from billing ledgers and invoice files.

Manual installation: copy `custom_components/ev_chargepoint` into your Home Assistant
configuration's `custom_components` directory, restart, and add the integration.

### No email / no SMTP server

Choose **No email / no SMTP server** to track usage and generate printable
invoices locally without setting up a server, login, sender or customer email.
This is the default for new entries. Selecting it disables automatic delivery
and manual email retries, even if old SMTP credentials are still saved. Existing
Gmail/custom SMTP entries retain their selected provider when updating.

### Send invoices from Gmail

For automatic sending without SMTP settings, first connect your Gmail account
in **Settings → Devices & services → Add integration → Google Mail**. Google
Mail requires Google OAuth application credentials and browser authorization;
an email address in your Home Assistant profile is not a sending authorization.
See [Google Mail setup](https://www.home-assistant.io/integrations/google_mail/).

In EV ChargePoint Configure, select **Gmail — connected account (no SMTP)**,
choose the account (or use the default when exactly one is connected), enter
the customer invoice recipient and enable **Automatically email monthly invoices**.
Leave SMTP fields blank: this mode uses Home Assistant's Google Mail action and
the connected account's default sender. Multiple accounts require an explicit
selection. An absent or disconnected account blocks automatic-email setup.
EV ChargePoint never reads or copies Google's OAuth tokens.

Invoices use the original recipient saved in their immutable snapshot. Missing
recipient information on an old invoice is not retroactively filled in. Failed
or interrupted sends still require explicit retry to avoid duplicate emails.
Messages contain the printable HTML invoice; this mode does not attach a PDF.

The existing app-password method remains available:

Choose **Gmail (Google app password)** as the email provider. Enter your full
Gmail address as the SMTP username and a Google app password in the masked
password field. Leave the sender blank to use that address. The preset uses
`smtp.gmail.com`, port `587`, with STARTTLS and certificate verification.
Custom hostname/port/security fields are ignored when Gmail is selected.

Google requires 2-Step Verification for app passwords; some managed accounts
do not offer them. See [Google's app-password instructions](https://support.google.com/mail/answer/185833)
and [SMTP settings](https://support.google.com/mail/answer/7104828).
No Gmail OAuth connection is included. Automatic email stays off until enabled.

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
invoice in plain text and HTML; PDF attachments and online payment collection are not
included in this version.

Email state `submitted` means the SMTP server accepted the message, not proof
of delivery to the recipient. Failed or interrupted (`sending`) attempts are
not automatically retried. **Retry pending or uncertain invoice emails** retries
all pending/failed/uncertain emails even if automatic email is disabled. Check
the mailbox before retrying uncertain sends, since they may have arrived.
The customer email address is saved with the invoice, so a later customer
change cannot redirect old invoices. SMTP transport settings use the current
configuration, allowing password/server changes before retrying. Connected Gmail
uses the currently selected authorized Google Mail account; legacy version 0.1
notification-entity settings are not reused. Previously issued invoices without a customer email
remain manual records and cannot be automatically redirected or emailed.

## Storage and removal

The ledger, invoice snapshots and delivery status live in Home Assistant's
`.storage/ev_chargepoint.<entry_id>`. Include that file and `ev_chargepoint_invoices` in
your backups. Configuration contains private customer details: do not upload
Home Assistant configuration or generated invoices to GitHub.
Removing the integration stops tracking/control but retains billing files for
your records. Export those records before manually removing them. Do not delete
an instance just to change a tariff; use Configure instead.

## Development

### Operations dashboard reporting

The status sensor now exposes monthly kWh, subtotal, tax, total, currency and
invoice numbers, plus issued-invoice summaries. Customer details, payment
instructions and SMTP configuration are excluded from these state attributes.
Monthly values come from the persisted ledger; they are not inferred from
Recorder samples or the current tariff.

New samples also persist calendar-day billable kWh, energy cost (excluding
monthly fees and tax), and gap seconds in the existing private ledger. Existing
ledgers migrate without backfilling or changing previously issued invoices.

Authenticated **administrator-only** WebSocket commands provide:

- `ev_chargepoint/daily` with `entry_id` and `month` (`YYYY-MM`): one month of
  daily ledger buckets, with `historical_backfill: false`.
- `ev_chargepoint/invoice` with `entry_id` and `period` (`YYYY-MM`): printable
  HTML for an already issued immutable invoice snapshot. This reads no
  caller-selected file paths and creates no public invoice URLs.

`dashboard/chargeport-card.js` is a self-contained Lovelace module. Register it
as a dashboard resource and use `custom:chargeport-operations-card`. Its daily
sensor tables use authenticated Recorder history, keep valid zero samples, and
omit unknown/unavailable values. It displays explicit empty and unsupported
states rather than inventing historical billing totals or invoices. Configure
the entity IDs and entry ID for the relevant charger. Invoice HTML downloads
require the reporting upgrade and an administrator session.

The module supports overview, daily activity, monthly billing, invoices,
requirements, and CSV export. Daily min/max/last readings are **not** daily
energy consumption or charging-session counts. Recorder retention still applies
to raw sensor history; durable daily billing buckets are separate evidence.

An integration update requires a Home Assistant restart to load the Python
changes. Include the existing billing ledger and invoice folder in backups.

```sh
python -m unittest discover -s tests -v
python -m compileall -q custom_components
ruff check .
```

GitHub Actions also runs HACS validation (including brand assets) and hassfest.
The integration ships standard and high-resolution icons and logos for light
and dark themes in `custom_components/ev_chargepoint/brand/`. Home Assistant
uses these in Devices & services and setup screens. Older HACS versions may
still display a placeholder because their update entities use the public brands
CDN instead of the bundled assets. The logo is included in every installation ZIP.
For an affected update card, an optional Home Assistant customization is:

```yaml
homeassistant:
  customize:
    update.ev_chargepoint_update:
      entity_picture: https://raw.githubusercontent.com/wholly1971/ha-ev-chargepoint/main/custom_components/ev_chargepoint/brand/icon.png
```

Merge this into the existing `homeassistant`/`customize` configuration; do not
create duplicate YAML keys. Preserve any existing customization includes. This
changes only the image and does not replace the HACS update entity. Standard
integration screens use the bundled `brand/` assets automatically. Printable invoices
embed the logo, and HTML emails attach it inline without remote tracking images.
This project is a custom repository, not a submission to the HACS default catalogue.

Before customer use, test in Home Assistant: configuration/options, W and kW
sensors, restarts, switch schedule and failures, a completed month, incomplete
month approval, SMTP success/failure/uncertain retry, and backup restoration.

References: [HACS packaging](https://www.hacs.dev/docs/publish/integration/),
[Python SMTP transport](https://docs.python.org/3/library/smtplib.html).

### Release process

Update `manifest.json` and add the matching version section to `CHANGELOG.md`.
After the main-branch Validate workflow passes, Publish release creates that
numbered GitHub release and attaches `ev-chargepoint-<version>.zip`. Existing
releases are not overwritten. The manifest is the package version source; no
second hard-coded version needs editing. Release ZIPs contain only
`custom_components/ev_chargepoint/` and its brand images, never local billing
records, credentials, repository tooling or tests.
