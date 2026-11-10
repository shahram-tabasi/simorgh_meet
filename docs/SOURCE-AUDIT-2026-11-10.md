# Initial Source Audit — Simorgh Meet Extraction

**Date:** 2026-11-10  
**Source:** `shahram-tabasi/SIMORGH-KARA`, branch `hadi_vk_meet`  
**Audited commit:** `28d08158ba4010c5e266d1f5d66b6b3c807f7a02`  
**Scope:** Static inspection of communication backend, Jitsi integration, attendance, schema, and frontend.  
**Execution status:** No source build or tests have been run.

## Executive summary

The branch contains useful implementations for direct/group calls, scheduled meetings, guest invitations, Jitsi JWT issuance, live notifications, and attendance sessions. The implementation is not a standalone product module: its services and UI are coupled to KARA's tenant/account model, database schemas, API proxy, and application shell.

**Decision:** Build Simorgh Meet-owned identity, organization, persistence, and authorization boundaries first. Port behavior selectively; do not copy KARA's API application or global schema.

## Verified source inventory

| Capability | Source |
|---|---|
| Calls lifecycle | `services/kara-api/src/comms/calls.service.ts` |
| Meetings, guests, attendance | `services/kara-api/src/comms/meetings.service.ts` |
| Authenticated routes | `services/kara-api/src/comms/comms.controller.ts` |
| Guest redemption | `services/kara-api/src/comms/guest-meetings.controller.ts` |
| Jitsi event receiver | `services/kara-api/src/comms/jitsi-events.controller.ts` |
| Jitsi JWT / room names | `services/kara-api/src/comms/jitsi.ts` |
| PostgreSQL LISTEN/NOTIFY + SSE | `services/kara-api/src/comms/live.service.ts` |
| KARA-wide schema | `services/kara-api/src/infra/schema.sql` |
| Call UI / Jitsi iframe | `src/components/comms/CallProvider.tsx` |
| Call controls | `src/components/comms/CallButtons.tsx` |
| KARA API proxy | `src/lib/comms.ts` |
| KARA calls page and shell | `src/app/app/[slug]/calls/page.tsx`, `src/app/app/[slug]/layout.tsx` |

Backend package uses NestJS 10, TypeScript, and PostgreSQL. The KARA `AppModule` registers communication components alongside ERP, HR, PLM, shop-floor, team, assistant, Kasra, identity, and provisioning services.

## Coupling to remove

- Services import `Actor` and `Tenant` from KARA's tenants module.
- Services use KARA `DbService`, configuration, and schemas.
- User identity/display data comes from `platform.user_accounts`.
- Membership and permissions use tenant-specific KARA tables.
- Communications data is stored in `kara_comms.*`.
- Live delivery uses fixed PostgreSQL channel `kara_live`.
- Frontend routes require KARA tenant sessions and `karaApi` proxies.
- The calls page depends on KARA company directory, navigation, and shell.

## Findings

### F-01 — Guest email validation regex is incorrectly escaped
**Severity: High (guest invitation usability).**

In `meetings.service.ts` (guest invitation creation and redemption, around lines 154–190), the email regex uses a doubled backslash before `s` inside a regex literal. The character class therefore does not mean “non-whitespace”; it excludes literal backslash and the letter `s` instead. Legitimate addresses containing `s` may be rejected, while whitespace handling is not as intended.

**Action:** Correct the expression in the Simorgh Meet implementation and add tests for valid addresses containing `s`, whitespace rejection, malformed domains, and boundary lengths. Leave KARA unchanged.

### F-02 — KARA identity and tenant types are embedded in domain services
**Severity: Critical architectural blocker.**

`CallsService` and `MeetingsService` accept KARA `Actor`/`Tenant` and query KARA account and membership tables.

**Action:** Define product-owned `UserPrincipal`, `OrganizationContext`, `Membership`, and authorization interfaces before implementing product services.

### F-03 — Communication tables are part of a global KARA schema
**Severity: Critical architectural blocker.**

`schema.sql` creates `kara_comms` alongside unrelated KARA schemas. It cannot serve as Simorgh Meet's clean-database migration.

**Action:** Create versioned product migrations for organizations, memberships, meetings, participants, guest invitations, provider events, and attendance.

### F-04 — Guest invitation controls are promising but need adversarial tests
**Severity: High.**

Observed controls include random high-entropy tokens, SHA-256 hashes at rest, expiry, row locking during redemption, single-use marking, and optional email binding.

Still unverified: concurrent redemption, transaction rollback, rate limiting, cancellation races, token leakage through logs/referrers, and guest room-token scope.

### F-05 — Jitsi integration needs a product adapter and deployment verification
**Severity: High.**

The source signs HS256 JWTs server-side with room and moderator claims, expiry, and a separate bearer secret for Prosody callbacks using timing-safe comparison.

Still unverified: issuer/audience/subject alignment with the actual Jitsi deployment, moderator policy, token TTL, room-locking, webhook network restrictions, replay handling, and provider compatibility.

### F-06 — Attendance requires event-order and reconciliation tests
**Severity: High.**

The source stores event IDs and join/leave intervals, maps stable JWT participant identity, deduplicates event IDs, and closes open intervals on room-destroyed events.

Still unverified: out-of-order events, multiple endpoints, reconnect identity changes, delivery gaps, duplicate events with changed timestamps, and late room-destroyed events.

### F-07 — Live delivery is coupled to PostgreSQL NOTIFY
**Severity: Medium.**

A dedicated PostgreSQL LISTEN connection forwards events to in-memory SSE streams. This may suit an initial deployment but requires testing for replica routing, reconnects, slow clients/backpressure, notification payload size, and delivery guarantees.

**Action:** Preserve a transport interface and choose the implementation based on measured scale.

### F-08 — Existing tests are narrow
**Severity: High.**

Visible tests cover meeting input validation and selected Jitsi event mapping/authentication cases. They do not establish database correctness, tenant isolation, guest race safety, full lifecycle correctness, real Jitsi interoperability, or browser behavior.

**Action:** Add unit, integration, cross-tenant security, and e2e tests. Source tests were not run in this audit.

### F-09 — Frontend requires an independent application shell
**Severity: Critical architectural blocker.**

The UI is mounted below KARA's `/app/[slug]`, requires KARA sessions, directory data, and API proxy routes.

**Action:** Build the Simorgh Meet shell and identity integration. Reuse only isolated UI behavior after reviewing dependencies.

### F-10 — Ad-hoc calls and scheduled meetings are distinct workflows
**Severity: Medium.**

Calls use a ringing/answer/decline/missed/leave state machine; meeting attendance is captured from Jitsi events. Their lifecycle semantics should not be collapsed.

**Action:** Keep separate domain aggregates while sharing carefully selected participant and media-provider primitives.

## Recommended extraction order

1. Product-owned configuration, database module, migrations, health checks.
2. Identity adapter, organizations, memberships, and authorization.
3. Meeting domain and repositories.
4. Jitsi provider adapter and secure room-token issuance.
5. Guest invitations and redemption.
6. Jitsi event ingestion and attendance.
7. Live transport and SSE.
8. Calls lifecycle.
9. Independent web application.
10. On-Premise deployment, then SaaS control plane.

## Limits

- Static inspection only; no build or test execution is claimed.
- No KARA files were changed.
- No KARA runtime dependency or source code has been added to Simorgh Meet yet.
