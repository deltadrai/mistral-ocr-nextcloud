import { generateUrl } from '@nextcloud/router'
import { showError, showLoading, showSuccess } from '@nextcloud/dialogs'
import { registerFileAction, FileAction } from '@nextcloud/files'

const SUPPORTED_MIME = [
	'application/pdf',
	'image/png',
	'image/jpeg',
	'image/tiff',
	'image/webp',
	'image/bmp',
	'image/heic',
	'image/heif',
]

const PROXY_BASE = '/apps/app_api/proxy/mistral_ocr/api/v1'
const POLL_INTERVAL_MS = 2000
const POLL_TIMEOUT_MS = 10 * 60 * 1000

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function fetchJob(jobId) {
	const res = await fetch(generateUrl(`${PROXY_BASE}/jobs`))
	if (!res.ok) {
		throw new Error(`Status request failed (${res.status})`)
	}
	const body = await res.json().catch(() => ({}))
	return (body.jobs || []).find((job) => job.id === jobId) || null
}

function filesUrlForPath(path) {
	const normalized = path.startsWith('/') ? path : `/${path}`
	const idx = normalized.lastIndexOf('/')
	const dir = normalized.slice(0, idx) || '/'
	const name = normalized.slice(idx + 1)
	return generateUrl('/apps/files/files?dir={dir}&scrollto={scrollto}', { dir, scrollto: name })
}

function resultPathFor(file, job) {
	if (job && job.result_path) {
		return job.result_path
	}
	const base = (file.basename || file.name || 'file').replace(/\.[^/.]+$/, '')
	return `${file.dirname || '/'}${base}.md`
}

function successNode(file, job) {
	const span = document.createElement('span')
	span.append(`${t('mistral_ocr', 'OCR finished:')} `)
	const link = document.createElement('a')
	link.href = filesUrlForPath(resultPathFor(file, job))
	link.textContent = resultPathFor(file, job).split('/').pop()
	span.append(link)
	return span
}

function hideToast(toast) {
	try {
		toast?.hideToast()
	} catch (e) {
		// toast already gone (e.g. closed manually) — the result toast below replaces it
	}
}

async function waitForJob(file, jobId, progressToast) {
	const deadline = Date.now() + POLL_TIMEOUT_MS
	let pollErrorShown = false
	while (Date.now() < deadline) {
		let job = null
		try {
			job = await fetchJob(jobId)
			pollErrorShown = false
		} catch (e) {
			if (!pollErrorShown) {
				pollErrorShown = true
				showError(t('mistral_ocr', 'Could not check OCR progress: {error}', { error: e.message }), { timeout: -1 })
			}
		}
		if (job && job.status === 'done') {
			hideToast(progressToast)
			showSuccess(successNode(file, job), { timeout: -1, close: true })
			return
		}
		if (job && job.status === 'failed') {
			hideToast(progressToast)
			showError(
				t('mistral_ocr', 'OCR failed: {error}', { error: job.error || t('mistral_ocr', 'unknown error') }),
				{ timeout: -1 },
			)
			return
		}
		await sleep(POLL_INTERVAL_MS)
	}
	hideToast(progressToast)
	showError(
		t('mistral_ocr', 'OCR is taking longer than expected. You will get a notification when the text is ready.'),
		{ timeout: -1 },
	)
}

async function runOcr(file) {
	let res
	try {
		res = await fetch(generateUrl(`${PROXY_BASE}/ocr`), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ fileId: file.fileid, force: true }),
		})
		if (!res.ok) {
			const body = await res.json().catch(() => ({}))
			throw new Error(body.detail || `Request failed (${res.status})`)
		}
	} catch (e) {
		showError(t('mistral_ocr', 'Could not start OCR: {error}', { error: e.message }), { timeout: -1 })
		return
	}
	const { jobId } = await res.json()
	const progressToast = showLoading(
		t('mistral_ocr', 'OCR in progress: {name}…', { name: file.basename || file.name }),
		{ close: true },
	)
	await waitForJob(file, jobId, progressToast)
}

registerFileAction(new FileAction({
	id: 'mistral-ocr-recognize',
	displayName: () => t('mistral_ocr', 'OCR with Mistral'),
	iconSvgInline: () => '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm3 5v2h2V8H7zm4 0v2h6V8h-6zm-4 4v2h2v-2H7zm4 0v2h6v-2h-6zm-4 4v2h10v-2H7z"/></svg>',
	enabled: (file) => SUPPORTED_MIME.includes(file.mime),
	exec: async (file) => { await runOcr(file); return true },
}))
