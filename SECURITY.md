# Security policy

## Supported versions

Security fixes target the latest numbered release. Older releases are not guaranteed to receive backports. Report the exact affected integration and Home Assistant versions. This is a community custom integration; response and fix times are not guaranteed.

## Reporting a vulnerability

Use GitHub's [private vulnerability reporting form](https://github.com/wholly1971/ha-ev-chargepoint/security/advisories/new) if it is available. If private reporting is not enabled, use a private contact method published on the [maintainer's profile](https://github.com/wholly1971). If neither is available, open a minimal public issue asking for a private reporting channel, without exploit details, credentials, customer information or billing records.

Provide a concise description, affected versions, impact, reproduction steps using synthetic data and suggested mitigations. Coordinate disclosure with the maintainer. Do not probe another person's Home Assistant instance or send test email to uninvolved recipients.

## Sensitive data and trust boundaries

Home Assistant config entries can contain SMTP credentials and customer details. Billing ledgers and generated invoices are private records. They must not be committed to this repository or placed under publicly served `www` paths. Use Home Assistant's supported APIs and configuration flows; never edit its internal storage directly.

The integration uses Home Assistant's existing Google Mail authorization when that provider is selected; it must not copy OAuth tokens. SMTP runs with TLS certificate verification. Invoice downloads require authenticated administrator access. Test emails are explicit actions and must not create invoices or alter delivery records.

The charger-control entity is a physical control surface. Configure a supported outlet/charger entity, review schedule behavior and verify changes on a test system before deployment. Manual overrides and automatic scheduling must remain coordinated.

## Automated checks

CI runs accounting/control tests, Home Assistant interface checks, Ruff, HACS validation and hassfest. OpenSSF Scorecard assesses public repository practices on main-branch changes and weekly; its results and badge are published by the OpenSSF service. Dependabot checks GitHub Actions references weekly. These checks supplement review and do not certify the absence of vulnerabilities or completion of the OpenSSF Best Practices assessment.
