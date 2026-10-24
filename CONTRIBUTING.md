# Contributing to EV ChargePoint

Thank you for helping improve scheduled EV charging and customer billing in Home Assistant. Please follow the [code of conduct](CODE_OF_CONDUCT.md).

## Before opening an issue

Search existing issues. Include the integration version, Home Assistant version, expected/actual behavior and a minimal reproduction. Redact customer names, addresses, email recipients, account identifiers, tokens, passwords and invoice data. Do not upload your Home Assistant configuration, billing ledger, diagnostics or invoices without reviewing them for private data. Report vulnerabilities using [SECURITY.md](SECURITY.md), rather than a public issue with exploit details.

## Development and validation

Use a supported Python release matching the CI workflow and a virtual environment. The accounting tests run without Home Assistant; interface tests require the Home Assistant version in `.github/workflows/validate.yml` and run in Linux CI.

```sh
python -m venv .venv
python -m pip install ruff
python -m unittest discover -s tests -v
python -m compileall -q custom_components
ruff check .
node --check dashboard/chargeport-card.js
```

When changing configuration labels, edit `scripts/build_translations.py` and regenerate both translation files with `python scripts/build_translations.py`. CI also runs HACS validation and hassfest. Run changes on a test Home Assistant instance before controlling a real outlet or sending email.

## Accounting and control changes

Use Decimal arithmetic for money. Preserve issued invoice snapshots and historical rates. Never backfill missing energy with invented readings. Test boundaries, overnight windows, missing/stale sensors, tax conversion, rate changes and restart behavior when relevant. Manual charging must remain coordinated with the automatic schedule; unavailable or failed control commands must not report success. Never send a real email as part of automated tests.

## Pull requests

Keep changes focused and describe the problem, resulting behavior, validation and material limitations. Add regression coverage for meaningful behavior changes. Do not include credentials, generated billing files, private configuration, dependency environments or build outputs. Contributions are made under the repository's existing GPLv3 license. Do not change licensing or claim third-party certifications as part of an unrelated contribution.

## Releases

Runtime changes require a manifest version change and matching changelog entry. The release workflow packages only tracked integration files and branding after main-branch validation passes. Documentation/community changes do not require a runtime version bump. Dashboard revisions are labelled separately from the installed integration version.
