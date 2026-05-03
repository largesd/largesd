# Privacy & Data Retention Policy

## Data Categories

| Category | Retention | Deletion Policy |
|----------|-----------|-----------------|
| Raw posts | 90 days | Auto-purged after debate closes |
| Canonical facts/arguments | Permanent | Aggregate-only, no PII |
| Snapshots | Permanent | Immutable audit record |
| User accounts | Until deletion request | bcrypt-hashed passwords |
| Appeal records | 7 years | Governance accountability |

## GDPR Considerations

- **Right to deletion**: Raw posts may be deleted; snapshots are immutable aggregates
- **Right to export**: Users can request their submission history via `/api/debate/<id>/appeals/mine`
- **Anonymization**: Canonicalization strips contributor identities per MSD §2.A
- **Consent**: Users agree to blindness rules and moderation at registration

## Contact

For privacy inquiries, contact the system administrator.
