# Vendored docker-jitsi-meet compose files

Source: https://github.com/jitsi/docker-jitsi-meet at tag `stable-11031`
(files: `docker-compose.yml`, `jibri.yml`, `transcriber.yml`, `LICENSE`).
License: Apache License 2.0 (see `LICENSE`).

These files are kept **unmodified** so upstream upgrades are a plain file replacement.
All Simorgh Meet customization lives in `../simorgh.yml` (compose overlay) and the
installer-generated `.env`. To upgrade Jitsi, replace these files with the ones from
the new tag, update `JITSI_IMAGE_VERSION` in `tools/package/versions.env`, and rebuild
the bundle.
