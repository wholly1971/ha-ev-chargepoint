# Changelog

## 0.3.2 — 2026-10-23

- Add an explicit Send test email button for SMTP, Gmail app passwords and connected Google Mail, with submission/failure status and a 60-second repeat guard. Tests never create invoices or alter delivery records.
- Add an optional AGL/Haggle reference-pricing module with unit rate, daily supply charge and solar feed-in rate sensor selections. Invoice tariffs remain unchanged.
- Add a pricing tab and email-test controls to the operations dashboard, keeping the live charger graph.

## 0.3.1 — 2026-10-23

- Separate email setup by provider so Gmail app-password setup never asks for a connected Google Mail account.
- Show only relevant email fields in a second setup step and explain provider-specific validation errors.
- Keep existing billing, schedule and email settings when editing. No email is sent during configuration.

## 0.3.0 â€” 2026-10-23

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
