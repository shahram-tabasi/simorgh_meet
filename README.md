# Simorgh Meet

**Independent video-meeting and collaboration platform by Simorgh.**

Simorgh Meet is developed as one product and one codebase for two delivery models:

- **On-Premise:** customer-managed deployment and licensing.
- **SaaS:** centrally operated service with tenant provisioning and subscription entitlements.

Jitsi is the initial media engine. Product identity, organizations, memberships, meetings, invitations, attendance, permissions, and licensing belong to Simorgh Meet itself. The product must not require SIMORGH-KARA at runtime.

## Repository status

The repository currently contains the initial architecture/security documents and the API foundation milestone. Meeting-domain extraction is not yet complete.

## Documentation

- [Product architecture](docs/PRODUCT-ARCHITECTURE.md)
- [KARA extraction plan](docs/EXTRACTION-PLAN.md)
- [Security baseline](docs/SECURITY-BASELINE.md)

## Development

Requirements: Node.js 20.11+ and npm 10+.

```bash
npm install
cp apps/api/.env.example apps/api/.env
npm run build
npm run typecheck
```

The API can start without a database for liveness checks. Readiness reports unavailable until a valid PostgreSQL `DATABASE_URL` is configured.

## Current milestone

**API foundation:** NestJS application bootstrap, environment parsing, PostgreSQL connection lifecycle, and health/readiness endpoints.

No KARA source code has been copied into this repository yet.
