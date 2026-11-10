# Simorgh Meet API

Initial API foundation built with NestJS 10 and TypeScript.

## Run locally

```bash
npm install
cp apps/api/.env.example apps/api/.env
npm run build --workspace @simorgh-meet/api
npm run start --workspace @simorgh-meet/api
```

The API listens on `0.0.0.0:${PORT:-8080}`.

- `GET /api/health/live` — process liveness; does not depend on PostgreSQL.
- `GET /api/health/ready` — readiness; requires a reachable PostgreSQL database.

## Database migrations

Set `DATABASE_URL` to a PostgreSQL database, then run:

```bash
npm run db:migrate --workspace @simorgh-meet/api
```

Migrations are applied in filename order, each in its own transaction. A PostgreSQL advisory lock prevents concurrent migration runners. Applied migration checksums are recorded in `public.schema_migrations`; editing an already-applied migration causes the runner to fail rather than silently changing database history.

The first migration creates product-owned organizations, OIDC user identities, memberships, meetings, participants, guest invitations, attendance sessions, and media-provider event tables. It does not create or depend on any KARA schema.

No business-domain endpoints are exposed yet. Authentication and tenant authorization must be implemented before protected product APIs are added.
