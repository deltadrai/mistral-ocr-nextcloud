/**
 * Progress toasts for the "OCR with Mistral" Files action.
 *
 * The action itself is registered through AppAPI (`ui/files-actions-menu`) and executed by
 * AppAPI's own files plugin, so this script must NOT register a second FileAction — it only
 * watches the ExApp's job queue and reports progress. AppAPI injects it into the Files page
 * via `ui/script` as a *classic* script (Nextcloud only emits `type="module"` for `.mjs`), so
 * it is bundled to a self-contained IIFE — see package.json.
 *
 * Toasts use Toastify directly with Nextcloud's own toast classes (`.toast-success`,
 * `.toast-error`, `.toast-info`), which core loads on every page via core/css/toast.css.
 * Bundling `@nextcloud/dialogs` for the same thing pulls in the whole dialog/filepicker
 * stack (~540 kB); this stays in the tens of kB.
 */
import Toastify from 'toastify-js'

const PROXY_BASE = '/apps/app_api/proxy/mistral_ocr/api/v1'
const POLL_INTERVAL_MS = 2000
// A job older than this is not ours to announce (left over from an earlier session).
const MAX_JOB_AGE_MS = 10 * 60 * 1000

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function apiUrl(path) {
	return OC.generateUrl(`${PROXY_BASE}${path}`)
}

function toast(text, { type = 'toast-info', duration = -1, close = true, node = null } = {}) {
	return Toastify({
		text: node || text,
		escapeMarkup: !node,
		className: type,
		duration,
		close,
		gravity: 'bottom',
		position: 'right',
		stopOnFocus: true,
	}).showToast()
}

async function fetchMyJobs() {
	const res = await fetch(apiUrl('/jobs?mine=1'), { headers: { Accept: 'application/json' } })
	if (!res.ok) {
		throw new Error(`Job status request failed (${res.status})`)
	}
	const body = await res.json().catch(() => ({}))
	return Array.isArray(body.jobs) ? body.jobs : []
}

function filesUrlForPath(path) {
	const normalized = path.startsWith('/') ? path : `/${path}`
	const idx = normalized.lastIndexOf('/')
	const dir = normalized.slice(0, idx) || '/'
	const name = normalized.slice(idx + 1)
	return OC.generateUrl(`/apps/files/files?dir=${encodeURIComponent(dir)}&scrollto=${encodeURIComponent(name)}`)
}

function resultNode(job) {
	const span = document.createElement('span')
	span.append(`${t('mistral_ocr', 'OCR finished:')} `)
	const path = job.result_path || ''
	const link = document.createElement('a')
	link.href = filesUrlForPath(path)
	link.textContent = path.split('/').pop() || t('mistral_ocr', 'result')
	span.append(link)
	return span
}

function hide(toastEl) {
	try {
		toastEl?.hideToast()
	} catch (e) {
		// already gone
	}
}

async function watch() {
	/** jobId -> last status we reported */
	const reported = new Map()
	let progressToast = null
	let pending = 0

	// Anything already finished when we arrive is history, not news.
	for (const job of await fetchMyJobs().catch(() => [])) {
		if (job.status !== 'pending') {
			reported.set(job.id, job.status)
		}
	}

	while (document.visibilityState !== 'hidden') {
		await sleep(POLL_INTERVAL_MS)
		let jobs
		try {
			jobs = await fetchMyJobs()
		} catch (e) {
			continue // transient: ExApp restarting or network blip
		}

		for (const job of jobs) {
			if (reported.get(job.id) === job.status) {
				continue
			}
			const age = Date.now() - (job.created_at || 0) * 1000
			if (job.status === 'pending') {
				if (!reported.has(job.id) && age < MAX_JOB_AGE_MS) {
					pending += 1
				}
				reported.set(job.id, 'pending')
				continue
			}
			if (reported.get(job.id) === 'pending') {
				pending = Math.max(0, pending - 1)
			}
			reported.set(job.id, job.status)
			if (job.status === 'done') {
				toast(null, { type: 'toast-success', node: resultNode(job) })
			} else if (job.status === 'failed') {
				toast(
					t('mistral_ocr', 'OCR failed: {error}', {
						error: job.error || t('mistral_ocr', 'unknown error'),
					}),
					{ type: 'toast-error' },
				)
			}
		}

		// One shared "in progress" toast, so a batch of files does not stack toasts.
		if (pending > 0 && progressToast === null) {
			progressToast = toast(t('mistral_ocr', 'OCR in progress…'), { type: 'toast-info' })
		} else if (pending === 0 && progressToast !== null) {
			hide(progressToast)
			progressToast = null
		}

		// Keep the map from growing in a long-lived tab.
		if (reported.size > 100) {
			for (const [id, status] of reported) {
				if (status !== 'pending') {
					reported.delete(id)
				}
			}
		}
	}
}

if (document.readyState === 'loading') {
	document.addEventListener('DOMContentLoaded', () => {
		watch()
	})
} else {
	watch()
}
