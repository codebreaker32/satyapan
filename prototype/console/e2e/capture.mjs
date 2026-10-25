// The console's capture tool. One command takes every screen a judge or a reviewer looks at, at the three
// widths the run holds us to: 1440x900, the venue projector's 1280x720, and 390 wide.
//
//   cd satyapan/console && npm run build
//   /home/aman/projects/raksham/satyapan/.venv/bin/satyapan serve --port 8010
//   node e2e/capture.mjs pass1-after            -> docs/cloud-run/captures/pass1-after/
//   node e2e/capture.mjs pass1-after --only case-red --widths 1280
//   node e2e/capture.mjs pass1-offline --offline  -> the same screens with the service unreachable
//
// `--offline` aborts the whole /api surface in the browser, which is what the officer sees when the service is
// not running. It is a mode of this script rather than a script of its own, for the reason below: four one-off
// capture scripts had each drifted out of date before pass 1 replaced them with this one.
//
// It replaced three one-off capture scripts (capture-1280x720, capture-scenarios, capture-pass6). Each had been
// written for one pass and each still selected `.row-item.scenario`, the row class the pass-6 landing rewrite
// removed, so all three silently stopped working and the next pass's "before" captures would have been taken by
// hand. The selectors live in ONE place now, beside the e2e that has to keep them true.
//
// Shots are viewport-sized by default, never fullPage: a capture that scrolls hides the fold, and the fold is
// the thing being judged. `--full` adds a whole-page shot beside each viewport one.
import { chromium } from '../../../deck/node_modules/playwright/index.mjs'
import { mkdir } from 'node:fs/promises'

const argv = process.argv.slice(2)
const label = argv.find((a) => !a.startsWith('-'))
if (!label) {
  console.log('usage: node e2e/capture.mjs <label> [--base URL] [--widths 1440,1280,390] [--only name,name] [--full]')
  process.exit(1)
}
const flag = (name, fallback) => {
  const i = argv.indexOf(`--${name}`)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback
}
const base = flag('base', process.env.E2E_BASE ?? 'http://127.0.0.1:8010')
const full = argv.includes('--full')
const offline = argv.includes('--offline')
const widths = flag('widths', '1440,1280,390').split(',').map(Number)
const only = flag('only', null)?.split(',')
const WAIT = 20000

const VIEWPORT = { 1440: { width: 1440, height: 900 }, 1280: { width: 1280, height: 720 }, 390: { width: 390, height: 844 } }

// Every screen worth a capture. A `scenario` shot runs that fixture through the engine first and lands on the
// case screen, so the four outcomes are captured from a live verdict and never from a stored one.
const SHOTS = [
  { name: 'landing', route: '#/scenarios', ready: '.scenario-row' },
  { name: 'cases', route: '#/cases', ready: '.page-head' },
  { name: 'memory', route: '#/memory', ready: '.page-head' },
  { name: 'rulebook', route: '#/rulebook', ready: '.page-head' },
  { name: 'newcase', route: '#/new', ready: 'form, .page-head' },
  { name: 'evaluation', route: '#/evaluation', ready: '.page-head' },
  { name: 'case-red', scenario: 'S3-ed-summons' },
  { name: 'case-amber', scenario: 'S5c-ed-summons-1h-old' },
  { name: 'case-grey', scenario: 'S5b-real-rbi-advisory' },
  { name: 'case-matches', scenario: 'S5a-genuine-bank-notice' },
  { name: 'case-claimonly', scenario: 'S4-claim-only' },
]

const healthy = await fetch(`${base}/api/health`).then((r) => r.ok).catch(() => false)
if (!healthy) {
  console.log(`no Satyapan service at ${base}; start it with: .venv/bin/satyapan serve --port 8010`)
  process.exit(1)
}
const scenarios = await fetch(`${base}/api/scenarios`).then((r) => r.json())
const titleById = Object.fromEntries(scenarios.map((s) => [s.id, s.title]))

const dir = new URL(`../../../docs/cloud-run/captures/${label}/`, import.meta.url).pathname
await mkdir(dir, { recursive: true })

// The offline set is every route that fetches on mount, plus the new-case form after a failed submit. A scenario
// shot needs the engine, so the one case screen here is opened while the wire is still up and then read with it
// cut — which is also the real sequence: the officer is mid-case when the service goes away.
let offlineShots = null
if (offline) {
  const ran = await fetch(`${base}/api/scenarios/S1-rm-voice-note/run`, { method: 'POST' }).then((r) => r.json())
  offlineShots = [
    { name: 'landing', route: '#/scenarios' },
    { name: 'cases', route: '#/cases' },
    { name: 'memory', route: '#/memory' },
    { name: 'rulebook', route: '#/rulebook' },
    { name: 'newcase', route: '#/new' },
    { name: 'newcase-submitted', route: '#/new', submit: true },
    { name: 'case', route: `#/case/${ran.case.id}` },
  ]
}
const shots = offlineShots ?? SHOTS

// Same path the officer takes, and the same selectors the e2e uses: the whole row is the control, and the twelve
// controls sit behind a disclosure that `<details>` leaves unrendered until it is open.
async function openCase(page, id) {
  await page.goto(`${base}/#/scenarios`)
  await page.waitForSelector('.scenario-row', { timeout: WAIT })
  const row = page.locator('.scenario-row', { hasText: titleById[id] })
  // A closed <details> still holds its children in the DOM, so the test is visibility, never existence.
  if (!(await row.first().isVisible())) {
    await page.locator('details.home-more summary').click()
    await page.waitForSelector('details.home-more[open] .scenario-row', { state: 'visible', timeout: WAIT })
  }
  await row.locator('.scenario-hit').click()
  await page.waitForSelector('.band', { timeout: WAIT })
}

const browser = await chromium.launch()
const written = []
try {
  for (const w of widths) {
    const ctx = await browser.newContext({ viewport: VIEWPORT[w] ?? { width: w, height: 900 } })
    const page = await ctx.newPage()
    if (offline) await page.route('**/api/**', (r) => r.abort())
    for (const shot of shots) {
      if (only && !only.includes(shot.name)) continue
      if (shot.scenario) {
        if (!titleById[shot.scenario]) throw new Error(`no such scenario: ${shot.scenario}`)
        await openCase(page, shot.scenario)
      } else {
        await page.goto(`${base}/${shot.route}`)
        // App fetches /api/meta once per document and a hash-only goto is a same-document navigation, so without
        // this the second offline shot onward would reuse a meta that had already loaded.
        if (offline) await page.reload()
        await page.waitForSelector(shot.ready ?? '.main', { timeout: WAIT })
      }
      if (shot.submit) {
        await page.locator('textarea').first().fill('RBI alert: transfer 3,80,000 to account 300112233445 immediately.')
        await page.getByRole('button', { name: 'Run the check' }).click()
        await page.waitForSelector('.notice-warn', { timeout: WAIT })
        await page.locator('.notice-warn').first().scrollIntoViewIfNeeded()
      }
      await page.evaluate(() => document.fonts.ready)
      await page.waitForTimeout(1200) // the one-time leader draw and the band transition settle
      if (!shot.submit) await page.evaluate(() => window.scrollTo(0, 0))
      const path = `${dir}${w}--${offline ? 'offline-' : ''}${shot.name}--fold.png`
      await page.screenshot({ path })
      written.push(path)
      if (full) {
        const fullPath = `${dir}${w}--${offline ? 'offline-' : ''}${shot.name}--full.png`
        await page.screenshot({ path: fullPath, fullPage: true })
        written.push(fullPath)
      }
    }
    await ctx.close()
  }
} finally {
  await browser.close()
  // Leave the demo as it was found: these runs create a case per scenario shot.
  await fetch(`${base}/api/demo/reset`, { method: 'POST' }).catch(() => {})
}
console.log(`wrote ${written.length} captures to ${dir}`)
for (const p of written) console.log(`  ${p.split('/').pop()}`)
