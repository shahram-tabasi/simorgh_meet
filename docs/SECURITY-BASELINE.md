# Simorgh Meet — Security Baseline

**Status:** Initial requirements; implementation and verification pending.

## Identity and sessions
- Use OIDC Authorization Code flow with PKCE for browser clients.
- Validate issuer, audience, signature, expiry, nonce, and state.
- Keep signing keys, client secrets, and service credentials server-side.
- Support secure session cookies and CSRF protection where cookie authentication is used.
- Do not treat a display name, email address, or client-provided user ID as proof of identity.

## Organizations and authorization
- Resolve the active organization from a verified membership.
- Enforce authorization in the API for every protected operation.
- Never rely on hidden UI controls as an authorization boundary.
- Scope every meeting, participant, invitation, attendance, recording, and file lookup to an authorized organization and resource.
- Add automated negative tests for cross-organization reads and writes.
- Keep platform operator permissions separate from organization administrator permissions.

## Meetings and guests
- Generate high-entropy guest tokens; store only a cryptographic hash.
- Enforce expiry, single-use redemption, meeting scope, and optional email binding.
- Make redemption atomic to prevent concurrent replay.
- Apply rate limits to invitation creation and redemption.
- Use short-lived, room-scoped Jitsi JWTs. Never expose Jitsi signing secrets to the browser.
- Validate and authenticate Jitsi event callbacks; make event processing idempotent.
- Treat provider event payloads as untrusted input and validate their shape and timestamps.

## Recordings and files
- Recording must be explicitly enabled by policy and clearly disclosed to participants.
- Define who may start, stop, view, download, share, and delete recordings.
- Apply retention and deletion policies to both metadata and object storage.
- Use private object storage and short-lived signed download URLs.
- Validate file type and size; scan uploads where operationally available.
- Audit recording and file access.

## Data protection
- Minimize personal data and avoid logging meeting tokens, invitation tokens, credentials, or sensitive content.
- Encrypt network traffic; document encryption-at-rest responsibilities for database and object storage.
- Define data retention, export, deletion, and backup retention policies.
- Keep tenant data isolated in database queries, background jobs, cache keys, object paths, and event channels.

## Operations and supply chain
- Keep secrets out of Git and container images.
- Run containers with least privilege and pin production image versions.
- Apply dependency and container vulnerability scanning in CI.
- Restrict administrative endpoints and protect them with strong authentication.
- Record security-relevant administrative actions in an audit log.
- Test backup restoration and incident recovery procedures.

## Verification
These are requirements, not claims of implemented controls. Each control must be mapped to code, configuration, and automated/manual tests before release.
