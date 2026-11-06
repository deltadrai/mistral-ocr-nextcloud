/* global fetch, document */
const base = '/apps/app_api/proxy/mistral_ocr/api/v1'
const status = document.getElementById('status')

function setStatus(msg, isError) {
	status.textContent = msg
	status.style.color = isError ? '#c00' : '#080'
}

async function api(path, options) {
	const res = await fetch(`${base}${path}`, options)
	const body = await res.json().catch(() => ({}))
	if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
	return body
}

async function load() {
	const data = await api('/admin/settings')
	const s = data.settings
	document.getElementById('base_url').value = s.base_url
	document.getElementById('model').value = s.model
	document.getElementById('max_file_size_mb').value = s.max_file_size_mb
	document.getElementById('max_pages').value = s.max_pages
	document.getElementById('timeout_seconds').value = s.timeout_seconds
	document.getElementById('default_output_mode').value = s.default_output_mode
	document.getElementById('allowed_mime_types').value = s.allowed_mime_types.join(', ')
	document.getElementById('include_image_base64').checked = s.include_image_base64
	document.getElementById('notify_on_success').checked = s.notify_on_success
	setStatus(data.apiKeyConfigured ? 'API key configured.' : 'No API key configured yet.')
}

async function save() {
	const payload = {
		base_url: document.getElementById('base_url').value,
		model: document.getElementById('model').value,
		max_file_size_mb: Number(document.getElementById('max_file_size_mb').value),
		max_pages: Number(document.getElementById('max_pages').value),
		timeout_seconds: Number(document.getElementById('timeout_seconds').value),
		default_output_mode: document.getElementById('default_output_mode').value,
		allowed_mime_types: document.getElementById('allowed_mime_types').value.split(',').map((s) => s.trim()).filter(Boolean),
		include_image_base64: document.getElementById('include_image_base64').checked,
		notify_on_success: document.getElementById('notify_on_success').checked,
	}
	const key = document.getElementById('api_key').value
	if (key) payload.api_key = key
	await api('/admin/settings', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload),
	})
	setStatus('Settings saved.')
}

async function testConnection() {
	setStatus('Testing…')
	const res = await api('/admin/test-connection', { method: 'POST' })
	setStatus(`OK. Model available: ${res.modelAvailable}`)
}

document.getElementById('save').addEventListener('click', () => save().catch((e) => setStatus(e.message, true)))
document.getElementById('test').addEventListener('click', () => testConnection().catch((e) => setStatus(e.message, true)))
load().catch((e) => setStatus(e.message, true))
