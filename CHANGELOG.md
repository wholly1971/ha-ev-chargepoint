# Changelog

## 0.4.2 - 2026-10-25

- Add branded, paginated A4 PDF invoices with seller/customer details, tariff rows, tax totals, billing notes and payment instructions.
- Attach PDFs to invoice email through SMTP/Gmail app passwords and the existing authorized Google Mail client, without copying OAuth credentials.
- Save PDFs beside private HTML invoices using immutable accounting snapshots; preserve historical amounts, recipients and submitted-send status.
- Withhold email if invoice files cannot be generated; retain explicit retry safeguards. Test email remains a connectivity test without an invoice.
- Add ReportLab dependency and regressions for PDF generation, legacy rate rows, attachment MIME data and private idempotent storage.

## 0.4.1 — 2026-10-25

- Add Manual charge On/Off and Resume schedule controls through a native Charging mode selector. Overrides return to automatic at the next charging-schedule transition and reset on restart/reload.
- Add a current charge-rate sensor and dashboard display using the active tariff, sensor/fallback source and configured invoice tax.
- Keep manual control responsive while email submission is running, with a separate control lock.

## Dashboard revision 2026.10.24.1 — 2026-10-24

- Add the Revisions dashboard page with installed/latest integration versions, bundled release history, official release links and CSV export.
- Dashboard-only update; integration package version remains 0.4.0.

## 0.4.0 — 2026-10-24

- Add configurable Peak, Off Peak, Shoulder 1, Shoulder 2 and EV Night windows, each with a manual rate, optional rate sensor and sensor tax-inclusion setting. Enabled windows must not overlap; overnight windows work.
- Add explicit all-measured-charging billing scope, independent of charger schedule control, with an option to retain legacy schedule-only billing.
- Record daily/monthly band kWh, energy costs, outside-schedule charging and sensor-fallback usage. Immutable invoices include the recorded band/rate breakdown; old energy is not reclassified.
- Add Charge rates dashboard tables and CSV export. Unavailable sensors use the configured manual fallback; unmatched windows use the default rate.

## 0.3.3 — 2026-10-23

- Fix the README logo inside HACS with an absolute HTTPS asset URL.
- Document the separate HACS 2.0.5 repository-list icon limitation; bundled Home Assistant brand assets remain included.

## 0.3.2 — 2026-10-23

- Add an explicit Send test email button for SMTP, Gmail app passwords and connected Google Mail, with submission/failure status and a 60-second repeat guard. Tests never create invoices or alter delivery records.
- Add an optional AGL/Haggle reference-pricing module with unit rate, daily supply charge and solar feed-in rate sensor selections. Invoice tariffs remain unchanged.
- Add a pricing tab and email-test controls to the operations dashboard, keeping the live charger graph.

## 0.3.1 — 2026-10-23

- Separate email setup by provider so Gmail app-password setup never asks for a connected Google Mail account.
- Show only relevant email fields in a second setup step and explain provider-specific validation errors.
- Keep existing billing, schedule and email settings when editing. No email is sent during configuration.

## 0.3.0 — 2026-10-23

- Publish numbered GitHub releases so HACS displays `0.3.0` instead of commit hashes.
- Derive the downloadable package name from the integration manifest version.
- Include only the integration and its bundled branding in the installation ZIP.
- Add automatic monthly invoice delivery through a connected Home Assistant Google Mail account, without SMTP server settings. Google OAuth authorization and an invoice recipient are required; email remains off until configured.
- Add historical monthly billing totals, invoice summaries, administrator-only invoice downloads, and durable daily billing records without inventing historical readings.
- Document the operations dashboard, missing-data handling, schedule controls and branding compatibility.

### Updating from a commit-based installation

In HACS, open EV ChargePoint, use **Redownload**, and select release **0.3.0** rather than `main` or a commit hash. Restart Home Assistant once the download finishes. A restart-required message is expected until the new Python code is loaded.

Existing settings, ledger records and issued invoices are retained. Review the selected schedule after upgrading. Window mode keeps the outlet off outside its configured period; all-day mode deliberately permits charging all day.

### Known limitations

- Older HACS update cards may use the public brands CDN rather than the bundled local logo. See the README branding workaround; a missing image does not mean the packaged logo is absent.
- Incomplete billing months require explicit review before invoices are issued. Missing readings are never backfilled.
- No SMTP or Gmail delivery was exercised against a real recipient for this release.
