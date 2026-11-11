# Simorgh Meet

**Independent video-meeting and collaboration platform by Simorgh.**

Simorgh Meet is developed as one product and one codebase for two delivery models:

- **On-Premise:** customer-managed deployment and licensing.
- **SaaS:** centrally operated service with tenant provisioning and subscription entitlements.

Jitsi is the initial media engine. Product identity, organizations, memberships, meetings, invitations, attendance, permissions, and licensing belong to Simorgh Meet itself. The product must not require SIMORGH-KARA at runtime.

## Repository status

- **On-Premise offline package** (`deploy/on-premise`, `tools/package`): one self-extracting installer
  with Docker Engine, Compose, all images and AI models; configuration wizard; `simorgh-meet` management CLI
  (backup/restore/upgrade/users/minutes). Verified by a real install of the full stack.
- **Automatic AI minutes** (`services/ai`): Persian streaming STT compatible with Jitsi Jigasi (per-speaker
  audio, live captions) + local LLM minutes with decisions and action items, stored in PostgreSQL.
- **API foundation** (`apps/api`) and product schema (`apps/api/migrations`), including rooms, groups,
  recordings, transcripts, minutes, action items, calendar feeds and attendance.
- The web portal and meeting-management API endpoints are not built yet — see the feature map.

## Documentation

- [On-Premise installation guide (فارسی/English)](docs/ON-PREMISE-INSTALL.md)
- [AI minutes & Persian/Kermani speech recognition](docs/AI-MINUTES-AND-PERSIAN-STT.md)
- [Feature map and status](docs/FEATURE-MAP.md)
- [Product architecture](docs/PRODUCT-ARCHITECTURE.md)
- [KARA extraction plan](docs/EXTRACTION-PLAN.md)
- [Security baseline](docs/SECURITY-BASELINE.md)

## Building the offline installer

On a machine with internet access and Docker (once per release):

```bash
tools/package/fetch-artifacts.sh
```

```bash
tools/package/build-images.sh
```

```bash
tools/package/build-bundle.sh
```

Install on the target server (no internet needed): `sudo sh simorgh-meet-<version>.run`.

## Development

Requirements: Node.js 20.11+ and npm 10+.

```bash
npm install
cp apps/api/.env.example apps/api/.env
npm run build
npm run typecheck
```

The API can start without a database for liveness checks. Readiness reports unavailable until a valid PostgreSQL `DATABASE_URL` is configured.

## AI service development

```bash
cd services/ai && pip install -e ".[test,whisper]" && python -m pytest -q
```

Set `TEST_DATABASE_URL` to a disposable database with the API migrations applied to include the
PostgreSQL persistence test. `tools/ci/validate-deploy.sh` renders a full On-Premise configuration and
validates the compose stack.

No KARA source code has been copied into this repository.
