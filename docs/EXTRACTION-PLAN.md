# Simorgh Meet — Extraction Plan

**Status:** Planning baseline; source audit is still in progress.

## 1. Objective

Extract only the meeting and collaboration capabilities from SIMORGH-KARA into the independent Simorgh Meet repository. Preserve KARA as-is. The new product must not depend at runtime on KARA services, schemas, identity assumptions, frontend shell, or deployment.

## 2. Source branch and initial evidence

- Source repository: shahram-tabasi/SIMORGH-KARA
- Intended source branch: hadi_vk_meet
- Last commit previously inspected: 28d08158ba4010c5e266d1f5d66b6b3c807f7a02
- Destination repository: shahram-tabasi/simorgh_meet
- Destination branch: main

The source tree contains a distinct `kara_comms` PostgreSQL schema with calls, meetings, participants, Jitsi events, attendance sessions, guest invitations, and guest records. Backend code includes calls/meetings services, guest-meeting and Jitsi-event controllers, a Jitsi JWT helper, and a live-event service. Frontend integration is embedded in KARA's tenant layout, call provider, call buttons, and calls page.

These are candidate source areas, not an approval to copy them unchanged.

## 3. Candidate extraction inventory

### Domain and persistence
- Calls and call participants (evaluate whether peer-to-peer calls are in first product release).
- Meetings and meeting participants.
- Guest invitation tokens and guest records.
- Jitsi event idempotency records.
- Attendance sessions and reports.

### Backend
- Calls and meetings application services.
- Meeting/call controllers and guest redemption endpoints.
- Jitsi event receiver and room-destroyed handling.
- Jitsi room naming and JWT generation.
- Live event delivery.

### Frontend
- CallProvider and meeting/call controls.
- Meeting listing and scheduling panels.
- Guest invitation/redeem/join flow.
- Attendance reporting UI.

## 4. KARA-specific coupling to remove

The inspected source shows several explicit KARA assumptions:

- `Actor` and `Tenant` types imported from KARA's tenants service.
- KARA's `DbService` and `config.databaseUrl`.
- Platform account IDs and tenant schema context.
- KARA-specific environment variables and JWT issuer/client defaults.
- `kara_live` PostgreSQL notification channel.
- Frontend `requireTenant`, `withTenant`, `karaApi`, and the KARA tenant shell.
- Room naming conventions containing KARA/tenant semantics.
- API registration currently combined in KARA's large application module.

These must be replaced by product-owned contracts and modules. Do not solve coupling by adding compatibility calls back to KARA.

## 5. Extraction mapping

| Source concept | Simorgh Meet target |
|---|---|
| KARA Actor | Product authenticated principal |
| KARA Tenant | Product organization / tenant context |
| KARA DbService | Product database module and repositories |
| KARA schema | Versioned product migrations |
| KARA API proxy | Product API client and auth session |
| KARA live channel | Product event transport abstraction |
| KARA Jitsi config | Product media-provider configuration |
| KARA frontend shell | Independent Simorgh Meet application shell |

## 6. Required review before copying

For every candidate file:
1. Read the complete file and its imports/callers.
2. Trace database tables, migrations, and transaction boundaries.
3. Identify KARA-only types, services, environment variables, and assumptions.
4. Review authorization and tenant scoping.
5. Review guest-token hashing, expiry, redemption atomicity, and replay behavior.
6. Review Jitsi JWT claims, room restrictions, event authentication, event deduplication, and participant identity mapping.
7. Review attendance interval behavior for reconnects, duplicate events, out-of-order events, and room destruction.
8. Locate and run the source tests where possible; record missing coverage.
9. Review third-party licenses and preserve required notices.
10. Classify each item: reuse, adapt, rewrite, defer, or reject.

## 7. Acceptance gates

Extraction is not complete until:

- The new repository builds without importing KARA packages or source files.
- Product-owned migrations create a clean database from zero.
- Authentication and organization membership work without KARA.
- Meeting create/list/update/cancel flows pass tests.
- Guest invitation is single-use, expiring, and tenant/meeting-scoped.
- Jitsi tokens are room-scoped and generated only after server authorization.
- Jitsi event ingestion authenticates sender and deduplicates retries.
- Attendance reports correctly account for reconnects and duplicate/out-of-order events.
- Cross-tenant access tests prove isolation.
- No KARA URL, schema, secret name, or runtime service is required.
- A clean deployment can be configured from documented environment variables.

## 8. Explicit exclusions from initial extraction

Do not import KARA ERP, HR, PLM, shop-floor, Kasra, Mattermost, Plane, assistant, knowledge, or unrelated organization workflows. These can be considered later only if a clear standalone Meet use case exists.

## 9. Change control

This plan authorizes documentation and planning only. Source repository files must remain unchanged. Feature implementation and any further repository writes should be performed in small reviewed stages with build/test evidence recorded.
