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

No business-domain endpoints are exposed yet. Authentication and tenant authorization must be implemented before protected product APIs are added.
