import { getLanguage } from '@nextcloud/l10n'
import de from './de.json'

/**
 * Bundled translation catalogues, keyed by Nextcloud language code.
 *
 * Why not AppAPI's native path: info.xml's <translations_folder> is only honoured
 * when AppAPI extracts an app archive (ExAppService sets it from the extracted
 * directory), and a Docker-only deploy never produces one. Without an installed
 * l10n/<lang>.js, ExAppUIL10NMiddleware injects nothing into the embedded page and
 * @nextcloud/l10n's t() would return English. So the catalogues ship in the bundle
 * and are selected from the UI language at runtime.
 *
 * Source strings are the English text; add a language by dropping <lang>.json next
 * to de.json and listing it in CATALOGS.
 */
const CATALOGS = { de }

/**
 * Translate an English source string into the current UI language.
 *
 * @param {string} text English source string (also the fallback)
 * @param {object} [vars] Values substituted into {placeholders}
 * @return {string}
 */
export function t(text, vars) {
	const catalog = CATALOGS[getLanguage()]
	let out = (catalog && catalog[text]) || text
	if (vars) {
		for (const key of Object.keys(vars)) {
			out = out.split(`{${key}}`).join(String(vars[key]))
		}
	}
	return out
}
