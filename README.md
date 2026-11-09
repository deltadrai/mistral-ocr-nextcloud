# Mistral OCR for Nextcloud (ExApp)

[![CI](https://github.com/deltadrai/mistral-ocr-nextcloud/actions/workflows/ci.yml/badge.svg)](https://github.com/deltadrai/mistral-ocr-nextcloud/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/deltadrai/mistral-ocr-nextcloud?sort=semver)](https://github.com/deltadrai/mistral-ocr-nextcloud/releases)

A Nextcloud **External App (ExApp)** that sends files and images to the
[Mistral OCR API](https://docs.mistral.ai/capabilities/document/) and turns them
into machine-readable **Markdown** — automatically via the workflow engine, or
manually from the Files app, or on demand from any Task Processing consumer
(Assistant, Talk, third-party apps).

- Registers a **Task Processing provider** for the built-in task type
  `core:image2text:ocr` (input: Nextcloud file ID, output: Markdown text).
- Adds a **file context-menu action** "OCR with Mistral".
- Exposes a **Flow (workflow engine) operation** for "file created / updated /
  tag assigned → Mistral OCR".
- Default output is a **sidecar file** `<original-name>.md` in the same folder.

## 🤖 Install prompt for AI agents

Paste this into your coding agent (Claude Code, Copilot, Cursor, …) to install and configure the app on a Nextcloud instance:

> Install the **Mistral OCR** Nextcloud ExApp (app id `mistral_ocr`, image
> `ghcr.io/deltadrai/mistral-ocr-nextcloud`, repo `deltadrai/mistral-ocr-nextcloud`)
> on this Nextcloud 30–35 instance. The registry, image and tag are read from
> `info.xml`; there is no image flag on the register command.
> 1. Make sure **AppAPI** is enabled and a deploy daemon is registered — check
>    with `occ app_api:daemon:list`. If none exists, register one (HaRP on
>    NC 32+, or a local Docker socket / Docker Socket Proxy);
>    see *Installation & registration* below.
> 2. Register the ExApp against that daemon:
>    `occ app_api:app:register mistral_ocr <daemon-name> --info-xml https://raw.githubusercontent.com/deltadrai/mistral-ocr-nextcloud/main/appinfo/info.xml --wait-finish`
> 3. Enable it under **Settings → Administration → AppAPI** (the *External Apps*
>    list), or with `occ app_api:app:enable mistral_ocr`.
> 4. Set the **Mistral API key** (from <https://console.mistral.ai>) on the app's
>    settings page: open the **Mistral OCR** entry in the top navigation
>    (administrators only), or run
>    `occ app_api:app:config:set mistral_ocr mistral_ocr_api_key --value <key> --sensitive=1`.
>    Then click **"Test connection"** to validate the key and the model.

## Architecture

```
┌──────────────┐   AppAPI (occ app_api:app:register)   ┌───────────────────────────┐
│  Nextcloud   │ ─────────────────────────────────────▶ │  ExApp container (Python) │
│  (NC 30–35)  │ ◀────────────── OCS / WebDAV ────────── │  FastAPI + nc_py_api      │
└──────────────┘                                        │  - task processing worker │
       ▲                                                │  - job queue (persisted)  │
       │ Task Processing / Flow / Files UI              │  - Mistral OCR client     │
       │                                                └───────────┬───────────────┘
       │                                                            │ HTTPS, Bearer key
       │                                                 ┌──────────▼───────────────┐
       └──────────── sidecar .md / notifications ────── │  api.mistral.ai /v1/ocr │
                                                          └──────────────────────────┘
```

**Data flow (GDPR-relevant):** file bytes are fetched server-side from
Nextcloud over the AppAPI/DAV channel (no public share links are created),
sent as a base64 data URI to `POST {base_url}/v1/ocr`, and only the extracted
Markdown text comes back. The API key is stored encrypted at rest via the
AppAPI secrets mechanism (`appconfig` with `sensitive=True`) and is never
logged or returned by any API response. Document content and OCR text are
never written to logs (debug redaction: only file IDs, MIME types, sizes and
error classes are logged). Use `https://api.eu.mistral.ai` for EU data
residency — configure it in the admin settings. Mistral acts as a data
processor under its DPA; review [Mistral's data processing terms](https://mistral.ai/terms/)
with your DPO before enabling automatic OCR on personal data.

## Requirements

- Nextcloud 30–35 with the **AppAPI** app (`app_api`) enabled.
- A Deploy Daemon: **HaRP** (recommended, NC 32+) or Docker Socket Proxy.
- A Mistral API key from <https://console.mistral.ai>.

## Installation & registration

There is no flag for the image: `occ app_api:app:register` takes the app id and
the **name of an already-registered deploy daemon**, and reads registry, image
and tag from `<docker-install>` in `info.xml`. So register a daemon first.

```bash
# 1. Register a deploy daemon (once per instance).
#
#    HaRP — the supported path on Nextcloud 32+:
occ app_api:daemon:register harp "HaRP" docker-install http \
  appapi-harp:8780 "https://your-nextcloud.example.com" \
  --harp --harp_frp_address appapi-harp:8782 \
  --harp_shared_key '<at least 12 chars>' --set-default
#
#    or a local Docker socket / Docker Socket Proxy:
occ app_api:daemon:register local_docker "Local Docker" docker-install http \
  /var/run/docker.sock "https://your-nextcloud.example.com" \
  --net nextcloud --set-default

# 2. Register the ExApp against that daemon.
occ app_api:app:register mistral_ocr local_docker \
  --info-xml https://raw.githubusercontent.com/deltadrai/mistral-ocr-nextcloud/main/appinfo/info.xml \
  --wait-finish
```

`--info-xml` accepts a URL or a local absolute path, so pointing it at
`appinfo/info.xml` inside the instance works too. `occ app_api:daemon:list` and
`occ app_api:app:list` show what is registered.

If no Deploy Daemon is configured, registration fails with a clear message from
AppAPI — install HaRP or the Docker Socket Proxy first.

`appinfo/info.xml` pins `<image-tag>` to the released version (the app store
rejects floating tags), so registration always deploys `0.1.18`. CI also pushes
`:latest` (tracking `main`) and `:sha-<commit>`; to deploy those instead, either
edit `<image-tag>` or point the daemon's registry mapping at a local build:

```bash
occ app_api:daemon:registry:add local_docker --registry-from ghcr.io --registry-to local
```

After registration:

1. Enable the app under **Settings → Administration → AppAPI** (the *External
   Apps* list). Enabling calls `PUT /enabled`, which registers the Task
   Processing provider, the Files action and the admin-only top-menu entry.
2. Open **Mistral OCR** in the top navigation (administrators only) and set the
   **API key**. That page is AppAPI's *embedded* template with this app's bundled
   Vue app rendered into it — there is no standalone URL to bookmark, and
   non-admins get a 404. The same values can be posted to
   `POST /api/v1/admin/settings`.
3. Click **"Test connection"** — validates the key and that the configured model
   is available to it.

The settings page is translated; German ships in `js/src/l10n/de.json` and is
selected from the user's Nextcloud language.

## Usage

- **Assistant / Task Processing consumers:** once the provider is registered,
  `core:image2text:ocr` tasks are routed to this app automatically. The
  extracted Markdown is returned as the task output.
- **Files app:** right-click a PDF/image → **"OCR with Mistral"**.
  A `<name>.md` sidecar appears next to the file. Running it again overwrites
  that sidecar and Nextcloud keeps the previous text as a file version.
  If the `.md` is currently locked — typically because it is open in the
  Nextcloud Text editor — the write is refused with HTTP 423 and the job fails
  with "*The Markdown result could not be saved because the file is locked…*".
  Text locks carry no expiry, so close the file and run OCR again rather than
  waiting for a retry.
- **Workflow engine (Flow):** create a flow with trigger *File created* /
  *File updated* / *Tag assigned* and the operation provided by this app
  (per-flow options: output mode override, page range, tags on success/failure).

### Sample workflow: auto-OCR an inbox folder

1. Admin → **Flow** → *Add flow* → trigger: **File created** in folder
   `/OCR-Inbox`, MIME type `application/pdf`.
2. Operation: **Mistral OCR** with output mode `sidecar`.
3. Result: every PDF dropped into `/OCR-Inbox` gets an `OCR-Inbox/<name>.md`
   within seconds. Unchanged files are **not** re-OCR'd (fingerprint guard);
   edit the file and the new version is processed again.

## Configuration reference

| Setting | Default | Notes |
|---|---|---|
| API key | — | stored encrypted (AppAPI secrets), never exposed |
| Base URL | `https://api.mistral.ai` | HTTPS only; `https://api.eu.mistral.ai` for EU |
| Model | `mistral-ocr-4-1` | aliases `mistral-ocr-4`, `mistral-ocr-latest` work too |
| Max file size | 50 MB | larger files are rejected with a typed error |
| Max pages | 100 | page-range selection for manual runs |
| Allowed MIME types | pdf, png, jpeg, tiff, webp, bmp, heic/heif | configurable |
| Default output mode | `sidecar` | `sidecar` / `task_result` / `description` (experimental) |
| `include_image_base64` | off | also retrieve rendered page images |
| Timeout | 120 s | retries with exponential backoff on 429/5xx (max 3) |

## Output modes

1. **Sidecar file** — `<name>.md` next to the original, one `## Page N` section
   per page. Indexable by Nextcloud full-text search automatically (see open
   question below).
2. **Task result only** — text returned through the Task Processing API for
   consuming apps.
3. **File description** — appends extracted text to the file description
   (experimental).

**Non-goal:** producing a searchable PDF (text layer on the original).
Mistral OCR returns text, not PDFs. For searchable PDFs use
[`workflow_ocr`](https://apps.nextcloud.com/apps/workflow_ocr) (OCRmyPDF).

## Reliability & security

- Job queue is persisted to disk (`APP_PERSISTENT_STORAGE`) and survives
  Nextcloud/app restarts; jobs are idempotent via the fingerprint guard
  (`sha256(file_id | etag | model)`).
- HTTPS-only base URLs are enforced; the API key never appears in logs or API
  responses.
- Failures always produce a Nextcloud notification with a user-facing message
  (invalid key / quota / unsupported file / too many pages / timeout); success
  notifications are optional.
- A custom event `mistral_ocr:ocr_completed` / `mistral_ocr:ocr_failed` is emitted
  per processed file for other apps to react to.

## Development

```bash
make install-dev
make test       # pytest (Mistral client mocked, no network)
make lint       # ruff check + format
make validate   # appinfo/info.xml against the Nextcloud App Store schema
make check      # everything CI runs: lint, tests, manifest, JS bundle
make js-build   # rebundle js/files_action.js, js/admin_page.js and css/admin.css
make docker-build
make smoke      # run the image and probe /api/v1/health
```

CI (`.github/workflows/ci.yml`) runs lint, tests, the manifest schema check and
the JS bundle check, then builds the image, smoke-tests it and — on `main` and
on `v*` tags — pushes it to GHCR. Integration tests against a real API key can
be added by setting `MISTRAL_API_KEY` in CI secrets.

The app-store schema used by `make validate` is vendored in `scripts/schema/`;
refresh it with `make update-schema`.

## Releases

Versioning is [Semantic Versioning](https://semver.org/). The version is the
single source of truth in `appinfo/info.xml` and is mirrored into
`package.json`, `src/mistral_ocr/__init__.py` and `CHANGELOG.md` — never edit
those by hand, bump them together:

```bash
make release VERSION=0.2.0     # rewrites all four files
# edit CHANGELOG.md: move the Unreleased entries under the new heading
git commit -am 'chore(release): v0.2.0'
git tag v0.2.0 && git push && git push --tags
```

Pushing the tag makes CI:

1. re-run lint, tests, the manifest schema check and the JS bundle check,
2. fail if the tag does not match `<version>` in `appinfo/info.xml`,
3. build and push `ghcr.io/deltadrai/mistral-ocr-nextcloud:0.2.0` (multi-arch:
   `linux/amd64` and `linux/arm64`) plus `:sha-<commit>`,
4. publish a GitHub release whose notes are the tag's `CHANGELOG.md` section.

`:latest` is only moved by pushes to `main`, so tagging an older release never
rolls it backwards.

The app store requires `<image-tag>` to match `<version>`, so the manifest
always pins the released tag instead of `latest`. `tests/test_release_metadata.py`
fails the build if any of those versions drift apart.

Release checklist:

- [ ] `make check` is green
- [ ] `CHANGELOG.md` describes the release under the new version
- [ ] `make release VERSION=x.y.z` ran and the diff looks right
- [ ] `make smoke` boots the image and answers `/api/v1/health`
- [ ] tag pushed, CI green, GHCR image and GitHub release published

## Assumptions (from the open questions in the spec)

1. **Organization-wide admin API key** (BYO per-user keys later); settings
   storage is split so per-user keys can be added without migration.
2. **Sidecar Markdown is the primary output**; searchable PDF is out of scope.
3. **Target NC 30–35, AppAPI ≥ 4.0**.
4. Files are fetched **server-side** over the AppAPI/DAV channel; no public
   share links are created.
5. **Full-text search:** sidecar `.md` files are plain files in the user's
   storage, so `files_fulltextsearch` (or the built-in search) indexes them
   like any other text file — a custom index is intentionally not built.
   Assumed sufficient; verify with your search backend in production.

## License

AGPL-3.0-or-later. See [LICENSE](LICENSE).
