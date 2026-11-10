# Simorgh Meet API

NestJS API foundation with PostgreSQL, OIDC access-token validation, and database-backed organization membership checks.

## Run locally

```bash
npm install
cp apps/api/.env.example apps/api/.env
npm run build --workspace @simorgh-meet/api
npm run start --workspace @simorgh-meet/api
```

The API listens on `0.0.0.0:${PORT:-8080}`.

## OIDC authentication

Configure all three values together:

- `OIDC_ISSUER`: exact issuer URL from the identity provider
- `OIDC_AUDIENCE`: API audience/client identifier expected in the access token
- `OIDC_JWKS_URL`: HTTPS JWKS endpoint published by the identity provider

The initial verifier accepts RS256-signed JWT access tokens only and validates the signature, issuer, audience, expiry, issued-at claim, and subject. The API does not trust roles or organization IDs from token claims. No token, private key, or client secret is stored by this service.

## Organization access

- `GET /api/me/organizations` requires a valid OIDC Bearer access token and lists only active memberships for the matching issuer + subject identity.
- `GET /api/organizations/:organizationId/context` additionally checks the user's active membership and the organization's active status in PostgreSQL. The tenant context is populated server-side.

Users must be provisioned in `users` and assigned an active row in `organization_memberships` by a trusted administrative provisioning process. Public self-registration and first-user bootstrap are intentionally not exposed yet.

## Database migrations

Set `DATABASE_URL`, then run:

```bash
npm run db:migrate --workspace @simorgh-meet/api
```

Migrations run in filename order, each in its own transaction, under a PostgreSQL advisory lock. Checksums prevent silently editing already-applied migrations.

## Verification

```bash
npm run typecheck --workspace @simorgh-meet/api
npm run test --workspace @simorgh-meet/api
npm run db:migrate --workspace @simorgh-meet/api
```

The API currently exposes identity and tenant-context foundations only; meeting-management endpoints are not yet implemented.
