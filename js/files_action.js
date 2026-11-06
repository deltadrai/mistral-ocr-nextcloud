import { generateUrl } from '@nextcloud/router'
import { showError, showSuccess } from '@nextcloud/dialogs'
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

async function runOcr(file) {
	try {
		const res = await fetch(generateUrl('/apps/app_api/proxy/mistral_ocr/api/v1/ocr'), {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ fileId: file.fileid, force: true }),
		})
		if (!res.ok) {
			const body = await res.json().catch(() => ({}))
			throw new Error(body.detail || `Request failed (${res.status})`)
		}
		showSuccess(t('mistral_ocr', 'OCR started. You will get a notification when the text is ready.'))
	} catch (e) {
		showError(t('mistral_ocr', 'Could not start OCR: {error}', { error: e.message }))
	}
}

registerFileAction(new FileAction({
	id: 'mistral-ocr-recognize',
	displayName: () => t('mistral_ocr', 'Recognize text with Mistral OCR'),
	iconSvgInline: () => '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm3 5v2h2V8H7zm4 0v2h6V8h-6zm-4 4v2h2v-2H7zm4 0v2h6v-2h-6zm-4 4v2h10v-2H7z"/></svg>',
	enabled: (file) => SUPPORTED_MIME.includes(file.mime),
	exec: async (file) => { await runOcr(file); return true },
}))
