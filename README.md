# Mistral OCR for Nextcloud (ExApp)

A Nextcloud **External App (ExApp)** that sends files and images to the
[Mistral OCR API](https://docs.mistral.ai/capabilities/document/) and turns them
into machine-readable **Markdown** — automatically via the workflow engine, or
manually from the Files app, or on demand from any Task Processing consumer
(Assistant, Talk, third-party apps).

- Registers a **Task Processing provider** for the built-in task type
  `core:image2text:ocr` (input: Nextcloud file ID, output: Markdown text).
- Adds a **file context-menu action** "Recognize text with Mistral OCR".
- Exposes a **Flow (workflow engine) operation** for "file created / updated /
  tag assigned → Mistral OCR".
- Default output is a **sidecar file** `<original-name>.md` in the same folder.

## 🤖 Install prompt for AI agents

Paste this into your coding agent (Claude Code, Copilot, Cursor, …) to install and configure the app on a Nextcloud instance:

> Install the **Mistral OCR** Nextcloud ExApp (app id `mistral_ocr`, Docker image
> `ghcr.io/deltadrai/mistral-ocr-nextcloud:latest`, repo `deltadrai/mistral-ocr-nextcloud`)
> on this Nextcloud 30–35 instance:
> 1. Make sure the **AppAPI** app is enabled and a deploy daemon is configured
>    (HaRP on NC 32+, or the Docker Socket Proxy).
> 2. Register the ExApp from the instance's `occ`:
>    `occ app_api:app:register mistral_ocr --info-xml https://raw.githubusercontent.com/deltadrai/mistral-ocr-nextcloud/main/appinfo/info.xml --docker-hub ghcr.io/deltadrai/mistral-ocr-nextcloud:latest`
>    (add `--harp-url https://<your-harp-host>` when using HaRP).
> 3. Enable it under **Apps → AppAPI → Mistral OCR**.
> 4. In the app's admin settings, set the **Mistral API key** (from
>    <https://console.mistral.ai>), base URL, model and limits, then click
>    **"Test API key & model"** to validate the configuration.

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

```bash
# Build and push the image (or use a prebuilt one)
make docker-build docker-push   # ghcr.io/deltadrai/mistral-ocr-nextcloud:latest

# Register the ExApp with AppAPI (HaRP)
occ app_api:app:register mistral_ocr \
  --info-xml https://raw.githubusercontent.com/deltadrai/mistral-ocr-nextcloud/main/appinfo/info.xml \
  --docker-hub ghcr.io/deltadrai/mistral-ocr-nextcloud:latest \
  --harp-url https://your-harp.example.com

# Or with Docker Socket Proxy
occ app_api:app:register mistral_ocr \
  --info-xml appinfo/info.xml \
  --docker-hub ghcr.io/deltadrai/mistral-ocr-nextcloud:latest
```

If no Deploy Daemon is configured, registration fails with a clear message from
AppAPI — install HaRP or the Docker Socket Proxy first.

After registration:

1. Enable the app in **Apps → AppAPI → Mistral OCR** (`PUT /enabled` runs
   automatically; it registers the Task Processing provider and starts the
   worker).
2. Open the app's admin page (`/admin`) or call `POST /api/v1/admin/settings`
   and set the **API key**, base URL, model and limits.
3. Click **"Test API key & model"** — validates the key and that the configured
   model is available to it.

## Usage

- **Assistant / Task Processing consumers:** once the provider is registered,
  `core:image2text:ocr` tasks are routed to this app automatically. The
  extracted Markdown is returned as the task output.
- **Files app:** right-click a PDF/image → **"Recognize text with Mistral OCR"**.
  A `<name>.md` sidecar appears next to the file (collisions are handled by
  Nextcloud file versioning).
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
make docker-build
```

CI (`.github/workflows/ci.yml`) runs lint + tests and builds the Docker image.
Integration tests against a real API key can be added by setting
`MISTRAL_API_KEY` in CI secrets.

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
