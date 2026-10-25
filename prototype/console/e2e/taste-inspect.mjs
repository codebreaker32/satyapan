// The taste skill's rendered-page audit, wired up so it runs on a machine without a system Chrome.
//
//   satyapan serve --port 8010
//   node e2e/taste-inspect.mjs http://127.0.0.1:8010/#/scenarios --widths 1440,1280,390
//
// `lint.mjs` reads the source and ends with "Now run inspect.mjs on the rendered page". inspect.mjs wants a
// Chrome binary, which may not be on the PATH. Playwright's chromium is installed for the deck build, so point
// CHROME_PATH at that and forward the arguments through. No new dependency, nothing installed, nothing outside
// the repo written.
import { chromium } from '../../../deck/node_modules/playwright/index.mjs'

process.env.CHROME_PATH ??= chromium.executablePath()
await import('/home/aman/.agents/skills/design-taste-frontend/scripts/inspect.mjs')
