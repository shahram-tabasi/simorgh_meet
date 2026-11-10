# Simorgh Meet — Product Architecture

**Status:** Initial architecture proposal  
**Version:** 0.1  
**Date:** 2026-11-10

## 1. Product direction

Simorgh Meet is an independent collaboration and meeting product derived selectively from meeting capabilities in SIMORGH-KARA. It is not a KARA module and must not require a running KARA installation, database, identity realm, API, or tenant context.

The product will be delivered from **one shared codebase** in two editions:

- **On-Premise:** deployed in the customer's infrastructure, with customer-controlled data and a product license.
- **SaaS:** operated as a hosted service, with organization/tenant provisioning, subscription plans, quotas, and centralized operations.

Edition-specific behavior should be implemented through configuration, deployment profiles, and explicit entitlements—not long-lived code forks.

## 2. Product boundaries

### Owned by Simorgh Meet

- Organizations / workspaces and tenant isolation
- Users, memberships, invitations, authentication integration, roles, and permissions
- Meetings, schedules, room policies, participants, and guest access
- Host/moderator controls and meeting lifecycle
- Attendance events, sessions, and reports
- Recording metadata, archive, and retention policy
- Meeting files and attachments
- Calendar integration
- Minutes, decisions, and action items
- AI-assisted transcription/minutes as an optional, policy-controlled capability
- Administration, audit events, licensing, and edition entitlements

### External infrastructure / adapters

- **Jitsi** is the initial media engine, behind a provider adapter.
- **Keycloak** is the proposed default identity provider, not a hard-coded product dependency. The identity boundary should permit OIDC-compatible providers.
- PostgreSQL is the system-of-record database.
- Redis is available for ephemeral coordination, queues, and real-time workloads where needed.
- S3-compatible object storage is the proposed abstraction for recordings and files.

No KARA-specific service, schema, URL, secret, account identifier, or runtime API may be required by the standalone product.

## 3. Proposed repository layout

This is a target structure, not a claim that these directories have already been implemented.

    apps/
      web/                     # Product UI and administration
      api/                     # Product API and application services
    packages/
      core/                    # Meeting and collaboration domain
      auth/                    # Identity integration and authorization contracts
      database/                # Schema, migrations, repositories
      media/                   # Media-provider contract
      integrations/
        jitsi/                 # Initial Jitsi adapter
      licensing/               # On-Premise license validation and entitlements
      shared/                  # Shared contracts, validation, utilities
    deploy/
      on-premise/              # Customer installation, upgrades, backup
      saas/                    # Hosted deployment and tenant operations
    docs/
      PRODUCT-ARCHITECTURE.md
      EXTRACTION-PLAN.md
      SECURITY-BASELINE.md
      ADR/

The final monorepo tooling and framework versions will be selected after auditing the source branch and checking dependency compatibility. Avoid upgrading frameworks as part of extraction unless required and separately justified.

## 4. Logical architecture

1. **Web application** — meeting experience, organization settings, user administration, and platform administration.
2. **API** — authenticated application boundary; validates tenant membership, permissions, meeting policies, and entitlements.
3. **Domain services** — meetings, invitations, participants, attendance, recordings, minutes, and audit.
4. **Adapters** — identity provider, media provider (initially Jitsi), email, calendar, object storage, and AI providers.
5. **Persistence** — PostgreSQL migrations and repositories; Redis only for ephemeral/queued workloads.
6. **Operations** — health checks, structured logs, metrics, backup/restore, upgrade and rollback procedures.

The browser must not receive media-provider secrets. Short-lived, room-scoped media credentials are issued by the API after authorization.

## 5. Multi-tenancy and editions

### SaaS

- Every request is bound to a verified tenant context.
- Tenant identity must come from authenticated membership and server-side resolution, never an untrusted client-supplied tenant ID alone.
- Data access must be tenant-scoped by design, with automated cross-tenant isolation tests.
- Platform operators and tenant administrators have distinct roles and audit trails.
- Plans, quotas, feature entitlements, and billing state are enforced server-side.

### On-Premise

- Support a customer-controlled installation with documented prerequisites and configuration.
- The initial deployment target is Docker Compose; Kubernetes can be evaluated later.
- Provide license activation, signed license validation, expiry/grace behavior, and an offline activation path where commercially required.
- Provide installation preflight, health checks, upgrade/migration, backup, restore, and rollback documentation.
- Customer data and secrets remain in customer-controlled infrastructure.

The exact SaaS tenancy storage strategy (shared schema with tenant keys versus schema/database isolation) remains an architecture decision to be made after reviewing data access patterns and operational requirements.

## 6. Security baseline

- OIDC authentication with validated issuer, audience, signature, expiry, and state/nonce where applicable.
- Server-side authorization on every protected operation.
- Tenant isolation enforced in service and persistence layers.
- Short-lived and narrowly scoped Jitsi JWTs; secrets held only server-side.
- Signed, single-use, expiring guest invitations; avoid storing raw invitation tokens.
- Rate limits and abuse controls for guest redemption, meeting creation, and authentication-sensitive endpoints.
- Audit events for administrative changes, invitations, access changes, and recording operations.
- Explicit recording consent/notice, access controls, retention, and deletion policy.
- Secrets supplied through deployment secret management; never committed to the repository.
- Dependency, container-image, and configuration scanning in CI.

## 7. Reliability and operations

- Database migrations are versioned, repeatable where practical, and tested against supported upgrade paths.
- Health/readiness endpoints distinguish application health from dependency health.
- Backups include database and object storage metadata/content as applicable; restore is tested, not merely documented.
- Logs must not expose tokens, meeting credentials, or sensitive personal data.
- Define supported sizing only after load tests. The previously discussed audience range is a planning input, not a verified capacity claim.
- Media capacity is sized separately from API/web capacity because Jitsi has different network and compute requirements.

## 8. Initial delivery sequence

1. Read-only source audit and extraction map for SIMORGH-KARA branch hadi_vk_meet.
2. Establish independent repository foundation, conventions, CI, environment configuration, and database migrations.
3. Implement product-owned identity, organization, membership, authorization, and tenant context.
4. Extract and adapt meeting, guest invitation, Jitsi integration, and attendance capabilities.
5. Add recording/archive, calendar, minutes/action items, and AI capabilities in prioritized increments.
6. Deliver an installable On-Premise package and validate install/upgrade/backup/restore.
7. Add SaaS control plane, tenant provisioning, plans, quotas, billing integration, and operational tooling.
8. Complete security, isolation, functional, upgrade, and load testing before release.

Each stage must have acceptance criteria and tests. No production-readiness or capacity claim is made until verified.

## 9. Decisions still to confirm

- Initial supported deployment OS and CPU architectures.
- Expected concurrent meeting participants and concurrent rooms (distinct from registered user count).
- Whether On-Premise customers need one organization per installation or multiple isolated organizations.
- Recording: local disk, S3-compatible storage, or both; retention and consent defaults.
- Transcription/AI provider, data residency, and whether AI can be disabled entirely.
- Email delivery and calendar providers.
- SaaS billing provider, commercial plans, and trial policy.
- Identity-provider requirements beyond OIDC/Keycloak.
- Supported languages and localization priorities.

## 10. Source and extraction safeguards

- SIMORGH-KARA remains unchanged during extraction.
- Work from the explicitly selected source branch; do not assume its default branch contains the latest Meet work.
- Reuse only code whose ownership, dependencies, tests, and license are understood.
- Replace KARA-specific tenant, actor, database, API, and UI assumptions with product-owned contracts.
- Preserve attribution and review third-party license obligations.
- Keep the new product repository independent; do not import unrelated KARA ERP, HR, PLM, shop-floor, assistant, or team-platform modules.
