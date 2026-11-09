# Accepted Django replacements

These decisions preserve OpenKos business behavior without copying Laravel or
framework-specific implementation details.

| OpenKos behavior | Django replacement | Reason and preserved behavior |
| --- | --- | --- |
| Application-specific user class | Django's supported `auth.User` plus one-to-one `UserProfile` | Retrofitting `AUTH_USER_MODEL` after production tables and foreign keys existed would add migration risk without adding a user-visible capability. Profile, language, phone, verification, 2FA, active state, invitations, last login, and safe deactivation are implemented. |
| Permanent account deletion | Soft deactivation | Login, roles, and property access are removed while leases, payments, ownership, and immutable audit records remain referentially valid. |
| Laravel route-per-action controllers | Consolidated Django workspaces and POST action views | The same permission checks, validation, transitions, and results are exposed with Django URL names recorded in the parity matrix. |
| Laravel plugin binaries | Django extension manifests and registries | Python extensions can register permissions, navigation, events, gateways, and health state. PHP binaries remain incompatible by design. |
| Provider-specific payment implementation | Payment gateway registry with the manual gateway enabled | Checkout attempts, webhook signatures, reconciliation, idempotency, and exactly-once payment creation remain provider independent. New gateways implement the registry contract. |
| Laravel mail and WhatsApp drivers | Database-configured SMTP and HTTPS webhook adapters | Credentials are encrypted in `AppSetting`; settings pages expose health tests. Console/log drivers remain available only for isolated development and verification. |
| Physical deletion of staff | Explicit administrator deactivation | The `users.delete` capability disables access and clears live role/property assignments while preserving historical actors and records. |

The 291-route matrix in `docs/PARITY_MATRIX.md` links each source route to its
Django implementation, server-side tests, and browser workflow evidence.
