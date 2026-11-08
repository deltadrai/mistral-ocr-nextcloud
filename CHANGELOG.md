# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Earlier `v0.1.0`–`v0.1.17` tags were development snapshots: they were never
published as GitHub releases and no container image was pushed for them. The
first release with artifacts is `0.1.18`.

## [Unreleased]

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
- The container image is built for `linux/amd64` and `linux/arm64`, carries OCI
  labels, and has a `HEALTHCHECK` against `/api/v1/health`.
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
