/**
 * Mistral OCR — ExApp settings page.
 *
 * AppAPI renders this into its own "embedded" template, which is just
 * <div id="content"></div> plus the script and stylesheet we registered with
 * nc.ui.resources.set_script/set_style("top_menu", "admin", ...). So everything
 * visible here is drawn by this bundle.
 *
 * Build: npm run build:admin -> js/admin_page.js (+ css moved to css/admin.css).
 */

import { createApp } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcInputField from '@nextcloud/vue/components/NcInputField'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcPasswordField from '@nextcloud/vue/components/NcPasswordField'
import NcSelect from '@nextcloud/vue/components/NcSelect'
import NcSettingsSection from '@nextcloud/vue/components/NcSettingsSection'
import NcTextField from '@nextcloud/vue/components/NcTextField'

import { t } from './l10n/index.js'

import './admin_page.css'

/**
 * Absolute API root of this ExApp as seen by the browser.
 *
 * The page is served from <root>/apps/app_api/embedded/mistral_ocr/admin while the
 * API lives behind <root>/apps/app_api/proxy/mistral_ocr/api/v1, so the segment has
 * to be swapped. Deriving it keeps the page working when Nextcloud itself is
 * installed in a subdirectory.
 */
function apiBase() {
	const path = window.location.pathname.replace(/\/+$/, '')
	const swapped = path.replace(/\/embedded\/([^/]+)\/.*$/, '/proxy/$1')
	if (swapped === path) {
		// Not an embedded page (opened directly); assume the proxy layout.
		return path.replace(/\/admin$/, '') + '/api/v1'
	}
	return swapped + '/api/v1'
}

const BASE = apiBase()

async function api(path, options) {
	const res = await fetch(BASE + path, options)
	const body = await res.json().catch(() => ({}))
	if (!res.ok) {
		// FastAPI puts the typed, user-facing message in "detail".
		throw new Error(body.detail || `Request failed (${res.status})`)
	}
	return body
}

const OUTPUT_MODES = [
	{ value: 'sidecar', label: () => t('Sidecar file (<name>.md)') },
	{ value: 'task_result', label: () => t('Task result only') },
	{ value: 'description', label: () => t('File description (experimental)') },
]

const EMPTY_FORM = {
	base_url: '',
	model: '',
	max_file_size_mb: 50,
	max_pages: 100,
	timeout_seconds: 120,
	default_output_mode: 'sidecar',
	allowed_mime_types: [],
	include_image_base64: false,
	notify_on_success: false,
}

const Settings = {
	name: 'MistralOcrSettings',
	components: {
		NcButton,
		NcCheckboxRadioSwitch,
		NcInputField,
		NcNoteCard,
		NcPasswordField,
		NcSelect,
		NcSettingsSection,
		NcTextField,
	},
	data() {
		return {
			loading: true,
			saving: false,
			testing: false,
			apiKeyConfigured: false,
			apiKey: '',
			form: { ...EMPTY_FORM },
			saved: { ...EMPTY_FORM },
			mimeTypes: '',
			note: null, // { type: 'success'|'error'|'warning', text: string }
			testResult: null, // { type: 'success'|'error', text: string }
		}
	},
	computed: {
		dirty() {
			if (this.apiKey !== '') {
				return true
			}
			return JSON.stringify(this.form) !== JSON.stringify(this.saved)
		},
		outputModeOptions() {
			return OUTPUT_MODES.map((m) => ({ value: m.value, label: m.label() }))
		},
		selectedOutputMode: {
			get() {
				return this.outputModeOptions.find((o) => o.value === this.form.default_output_mode) || null
			},
			set(option) {
				this.form.default_output_mode = option ? option.value : 'sidecar'
			},
		},
	},
	async mounted() {
		await this.load()
	},
	methods: {
		t,
		async load() {
			this.loading = true
			this.note = null
			try {
				const data = await api('/admin/settings')
				const s = { ...EMPTY_FORM, ...(data.settings || {}) }
				this.form = s
				this.saved = { ...s }
				this.mimeTypes = (s.allowed_mime_types || []).join(', ')
				this.apiKeyConfigured = !!data.apiKeyConfigured
			} catch (err) {
				this.note = { type: 'error', text: t('Settings could not be loaded: {error}', { error: err.message }) }
			} finally {
				this.loading = false
			}
		},
		async save() {
			if (!this.dirty || this.saving) {
				return
			}
			this.saving = true
			this.note = null
			try {
				const payload = {
					base_url: this.form.base_url,
					model: this.form.model,
					max_file_size_mb: Number(this.form.max_file_size_mb),
					max_pages: Number(this.form.max_pages),
					timeout_seconds: Number(this.form.timeout_seconds),
					default_output_mode: this.form.default_output_mode,
					allowed_mime_types: this.mimeTypes.split(',').map((v) => v.trim()).filter(Boolean),
					include_image_base64: !!this.form.include_image_base64,
					notify_on_success: !!this.form.notify_on_success,
				}
				if (this.apiKey !== '') {
					payload.api_key = this.apiKey
				}
				const data = await api('/admin/settings', {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload),
				})
				const s = { ...EMPTY_FORM, ...(data.settings || {}) }
				this.form = s
				this.saved = { ...s }
				this.mimeTypes = (s.allowed_mime_types || []).join(', ')
				this.apiKey = ''
				this.apiKeyConfigured = !!data.apiKeyConfigured
				this.note = { type: 'success', text: t('Settings saved.') }
			} catch (err) {
				this.note = { type: 'error', text: t('Settings could not be saved: {error}', { error: err.message }) }
			} finally {
				this.saving = false
			}
		},
		async testConnection() {
			if (this.testing) {
				return
			}
			this.testing = true
			this.testResult = null
			try {
				const res = await api('/admin/test-connection', { method: 'POST' })
				this.testResult = res.modelAvailable
					? { type: 'success', text: t('Connection works and the model is available.') }
					: {
						type: 'warning',
						text: t('Connection works, but the model is not available for this key.'),
					}
			} catch (err) {
				this.testResult = { type: 'error', text: t('Connection test failed: {error}', { error: err.message }) }
			} finally {
				this.testing = false
			}
		},
		discard() {
			this.form = { ...this.saved }
			this.mimeTypes = (this.saved.allowed_mime_types || []).join(', ')
			this.apiKey = ''
			this.note = null
		},
	},
	template: `
<div class="mistral-ocr-settings">
	<div class="mistral-ocr-settings__head">
		<h2>Mistral OCR</h2>
		<p class="mistral-ocr-settings__intro">
			{{ t('Send files and images to the Mistral OCR API and store the result as Markdown.') }}
		</p>
	</div>

	<NcNoteCard v-if="loading" type="info" class="mistral-ocr-settings__note">{{ t('Loading settings…') }}</NcNoteCard>
	<NcNoteCard v-if="note" :type="note.type" class="mistral-ocr-settings__note">{{ note.text }}</NcNoteCard>

	<NcSettingsSection :name="t('Connection')">
		<div class="mistral-ocr-settings__field">
			<NcPasswordField
				v-model="apiKey"
				:label="t('Mistral API key')"
				:helper-text="t('Stored encrypted; leave empty to keep the current key.')"
				:disabled="loading"
				autocomplete="off" />
			<NcNoteCard :type="apiKeyConfigured ? 'success' : 'warning'" class="mistral-ocr-settings__badge">
				{{ apiKeyConfigured ? t('API key configured') : t('No API key configured yet') }}
			</NcNoteCard>
		</div>

		<NcTextField
			v-model="form.base_url"
			:label="t('API base URL')"
			:helper-text="t('Use https://api.eu.mistral.ai for EU data residency.')"
			:disabled="loading"
			placeholder="https://api.mistral.ai" />

		<NcTextField
			v-model="form.model"
			:label="t('Model')"
			:disabled="loading"
			placeholder="mistral-ocr-4-1" />

		<div class="mistral-ocr-settings__actions">
			<NcButton :disabled="testing || loading" @click="testConnection">
				{{ testing ? t('Testing…') : t('Test connection') }}
			</NcButton>
			<NcNoteCard v-if="testResult" :type="testResult.type" class="mistral-ocr-settings__badge">
				{{ testResult.text }}
			</NcNoteCard>
		</div>
	</NcSettingsSection>

	<NcSettingsSection :name="t('Processing')">
		<div class="mistral-ocr-settings__field">
			<NcSelect
				v-model="selectedOutputMode"
				:options="outputModeOptions"
				:input-label="t('Default output')"
				:helper-text="t('Where the extracted text goes by default.')"
				:disabled="loading" />
		</div>

		<div class="mistral-ocr-settings__row">
			<NcInputField
				v-model="form.max_file_size_mb"
				type="number"
				:label="t('Maximum file size (MB)')"
				:disabled="loading" />
			<NcInputField
				v-model="form.max_pages"
				type="number"
				:label="t('Maximum pages per document')"
				:disabled="loading" />
			<NcInputField
				v-model="form.timeout_seconds"
				type="number"
				:label="t('Request timeout (seconds)')"
				:disabled="loading" />
		</div>

		<NcTextField
			v-model="mimeTypes"
			:label="t('Allowed MIME types')"
			:helper-text="t('Comma separated; files of other types are rejected.')"
			:disabled="loading" />

		<NcCheckboxRadioSwitch
			:model-value="form.include_image_base64"
			type="switch"
			:disabled="loading"
			@update:model-value="(v) => (form.include_image_base64 = v)">
			{{ t('Include rendered page images in the result') }}
		</NcCheckboxRadioSwitch>

		<NcCheckboxRadioSwitch
			:model-value="form.notify_on_success"
			type="switch"
			:disabled="loading"
			@update:model-value="(v) => (form.notify_on_success = v)">
			{{ t('Send a notification when OCR finishes') }}
		</NcCheckboxRadioSwitch>
	</NcSettingsSection>

	<div class="mistral-ocr-settings__footer">
		<span v-if="dirty" class="mistral-ocr-settings__dirty">{{ t('You have unsaved changes.') }}</span>
		<NcButton :disabled="!dirty || saving || loading" @click="discard">
			{{ t('Discard changes') }}
		</NcButton>
		<NcButton variant="primary" :disabled="!dirty || saving || loading" @click="save">
			{{ t('Save changes') }}
		</NcButton>
	</div>
</div>
`,
}

const mountPoint = document.getElementById('content') || document.body
createApp(Settings).mount(mountPoint)
