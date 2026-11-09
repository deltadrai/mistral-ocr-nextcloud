# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Earlier `v0.1.0`–`v0.1.17` tags were development snapshots: they were never
published as GitHub releases and no container image was pushed for them. The
first release with artifacts is `0.1.18`.

## [Unreleased]

### Fixed

- The admin settings help text pointed at `/exapps/mistral_ocr/admin`, which does
  not exist. AppAPI 34 serves ExApp pages only through its proxy, so the app's
  own settings page is at
  `https://<nextcloud>/apps/app_api/proxy/mistral_ocr/admin` (administrators
  only). There is no menu entry for it, which is what made it undiscoverable.
- Re-OCR'ing a file whose sidecar Markdown is locked — typically because it is
  open in the Nextcloud Text editor, which locks `.md` files with no expiry —
  failed with a raw `[423] Locked <upload: …>` WebDAV error and no guidance. It
  now raises a typed `SidecarLockedError`, notifies the user to close the file,
  and leaves the file unmarked so the job can be retried. Other write failures
  report `SidecarWriteError` instead of the raw DAV message.
- CI pushed the `<version>` image tag on every `main` push, so merging a commit
  would have overwritten the released image that `info.xml` and the app store
  pin. The version tag is now gated on `v*` tag pushes; `main` only moves
  `:latest` and `:sha-<commit>`. Guarded by a test.
- The documented file-action label was "Recognize text with Mistral OCR"; the
  app registers **"OCR with Mistral"**. Fixed in the README and in the app-store
  description.
- README installation instructions used `--docker-hub` and `--harp-url`, neither
  of which exists on `occ app_api:app:register`. The command takes the app id and
  a **deploy daemon name**, and reads registry, image and tag from
  `<docker-install>` in `info.xml`. The documented flow now matches what AppAPI
  34 accepts, and enabling happens under **Settings → Administration → AppAPI**.

### Changed

- Removed the `HEALTHCHECK` instruction. CI publishes OCI media types, which have
  no healthcheck field, so the directive added in 0.1.18 was silently dropped and
  never reached the published image. `/api/v1/health` remains for the CI smoke
  test; AppAPI polls `/heartbeat` itself.

## [0.1.18] - 2025-11-08

First published release: container image on GHCR, signed-off manifest and a
GitHub release with these notes.

### Added

- Task Processing provider for `core:image2text:ocr`, so the Assistant app, Talk
  and any other Task Processing consumer can OCR files through Mistral.
- "OCR with Mistral" action in the Files context menu, with progress toasts and
  a link to the produced Markdown file.
- Flow (workflow engine) operation for *file created* / *file updated* /
  *tag assigned* triggers.
- Three output modes: sidecar `<name>.md` next to the source file, task result
  only, or file description.
- Persistent job queue with a fingerprint guard (`sha256(file_id | etag | model)`)
  so unchanged files are not OCR'd twice.
- Admin settings in Nextcloud (declarative settings form) plus a standalone
  `/admin` page for the API key, base URL, model, limits and timeouts.
- "Test API key & model" setup check.
- EU endpoint support (`https://api.eu.mistral.ai`) for data residency.
- Nextcloud notifications for failures, and optional notifications on success.
- `mistral_ocr:ocr_completed` / `mistral_ocr:ocr_failed` events for other apps.

### Changed

- `appinfo/info.xml` now passes the Nextcloud App Store schema: flat
  `<category>` elements, `<image-tag>` instead of `<tag>`, and no invalid
  `<backend>app_api</backend>` dependency. The `<image-tag>` is pinned to the
  release version because the store rejects floating tags.
- Runtime dependencies are pinned exactly so a rebuilt tag ships the same code.
- The container image is built for `linux/amd64` and `linux/arm64` and carries
  OCI labels. (The `HEALTHCHECK` added here was dropped by the OCI export and is
  removed again under *Unreleased*.)
- CI validates the manifest against the app store schema, smoke-tests the built
  image, refuses a tag that does not match `<version>`, and publishes the image
  plus a GitHub release on `v*` tags.

### Security

- The Mistral API key is stored encrypted through the AppAPI secrets mechanism
  and is never logged or returned by an API response.
- HTTPS-only base URLs; file content and OCR text are never written to logs.
- Files are fetched server-side over the AppAPI/DAV channel — no public share
  links are created.

[Unreleased]: https://github.com/deltadrai/mistral-ocr-nextcloud/compare/v0.1.18...HEAD
[0.1.18]: https://github.com/deltadrai/mistral-ocr-nextcloud/releases/tag/v0.1.18
