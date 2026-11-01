# Identity security

Persistent sessions supplement the existing RS256 JWT/JWKS contract. Password
login issues a session UUID and an opaque refresh token. Only the SHA-256 refresh
hash is stored. Refresh rotates once; replay revokes its entire session family.
Rotation and security mutations serialize in a database transaction (SQLite
BEGIN IMMEDIATE, PostgreSQL durable mutex row). No in-process locking is required.

Sessions expire after 15 minutes without foreground activity and after eight
hours absolutely. Refresh and ordinary reads do not extend either deadline.
`POST /auth/session/activity {}` uses server time and never extends absolute life.
`GET /auth/sessions` lists only the caller's sessions; logout and revocation take
effect on the next authoritative `/auth/me` check. Offline JWT consumers must
adopt that check to enforce immediate revocation.

Five failed logins in 15 minutes lock the login for 15 minutes. Inactive, unknown,
locked and wrong-password responses remain uniform. A global administrator can
unlock accounts or revoke sessions/tokens. Public registration cannot assign
administrator privileges. Bootstrap uses the host CLI:

```
mod1-auth migrate
mod1-auth set-admin --user-id <UUID> --admin
mod1-auth set-admin --user-id <UUID> --no-admin
```

`init` and `migrate` are explicit, idempotent schema operations; application startup
never changes schema. Existing users and profiles are preserved. New security
tables hold account flags, sessions, hashed tokens and append-only audit events;
old accounts start without administrator or verified-email flags. A legacy JWT
without `sid` is accepted only for active users and only before account revocation.
Revocation timestamps also block legacy tokens; their second resolution can
conservatively reject a synthetic legacy token issued within the revocation second.

Changing or resetting a password now revokes **all** sessions. This deliberately
replaces the old behavior of allowing the old JWT until its expiry. Reauthenticate
with the new password before changing it again. Deactivation also revokes sessions.

Security responses are `Cache-Control: no-store`. Validation never reflects
submitted passwords or tokens. Audit payloads omit credentials and record only
actor, target, action, outcome, source service and UTC time. Proposed retention is
180 days, with no automatic deletion of audit records in this implementation.

## Recovery, email and MFA

Recovery links expire in 30 minutes, verification links in 24 hours; both are
single-use opaque values with only a hash in credential storage. Requests are
limited to three per account/purpose in 15 minutes, with 60 seconds between sends.
Links use the configured `FRONTEND_ORIGIN`, never the incoming Host header, and
carry credentials in fragments (`#recovery=` or `#verify-email=`). Clients must
remove the fragment before logging, navigating or making network requests.

SMTP is disabled unless `SMTP_HOST` is explicitly supplied. Transport uses STARTTLS,
the system certificate trust store, optional SMTP credentials and a five-second
timeout. With no transport configured, requests uniformly return 503 for existing
and absent emails; with configured transport, eligible and absent accounts receive
the same generic 202. SMTP failures return a sanitized 503. No real SMTP delivery
has been verified during this local implementation.

`LOCAL_MAILBOX_ENABLED=true` selects a development-only mailbox instead of SMTP.
Its sensitive message bodies can be read only by a valid global administrator at
`GET /admin/mailbox`. The route returns 404 when disabled. Never enable it in a
public deployment; these development messages contain the actual one-time links.
Admin provisioning (`POST /admin/users {display_name,email}`) uses a setup link;
an administrator never supplies a colleague's password. Existing inactive accounts
are neither reactivated nor reset as an implicit side effect.

MFA uses RFC 6238 SHA-1, six digits, 30-second steps, a ±1-step window and atomic
step consumption. An enabled account receives only a five-minute challenge after
correct password entry; access/refresh tokens require TOTP or an unused recovery
code. Password-only requests cannot reset the MFA failure counter. Five failed
second-factor attempts lock the factor for 15 minutes. Password reset cannot bypass
MFA, and changing/resetting the password invalidates outstanding login challenges.

Set a separate `MFA_ENCRYPTION_KEY` (a Fernet key) through the environment or secret
store. Seeds are authenticated-encrypted; recovery codes are high-entropy values
shown once and persisted only as SHA-256 hashes. Without the configured key, MFA
setup/verification returns sanitized 503. Losing this key makes enrolled seeds
unreadable; retain/rotate it through an operational backup process. Key rotation
is not automated here. Setup requires password and activation proof; regeneration
requires password and a fresh TOTP; disabling requires password and TOTP/recovery.

## Consented professional directory

`PATCH /auth/profile` adds `share_for_recommendations:boolean`, default false for
all users, including old records. Consent persists in a separate security document,
so existing user/profile tables do not need destructive changes. Directory items
are professional snapshots with `user_id`, `display_name`, `summary`, `seniority`,
`weekly_availability_hours`, `skills:[{name,level}]` and the consent flag. They
contain no email or authentication information. Only active, opted-in users appear
in paginated/filterable `/auth/directory`; a snapshot by UUID is visible when shared,
or to its owner/global administrator. Revoking consent removes subsequent access.
Pagination is applied after consent and search filtering (default 20, maximum 100).
