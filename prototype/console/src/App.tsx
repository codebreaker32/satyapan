import { useCallback, useEffect, useState } from 'react'
import { OfflineError, api, type CaseView as View, type Meta } from './lib/api'
import { href, useRoute, type Route } from './lib/router'
import { CaseView } from './views/CaseView'
import { Cases } from './views/Cases'
import { Evaluation } from './views/Evaluation'
import { Memory } from './views/Memory'
import { NewCase } from './views/NewCase'
import { Rulebook, integrationHonesty } from './views/Rulebook'
import { Scenarios } from './views/Scenarios'

const NAV: Array<{ route: Route; label: string }> = [
  { route: { name: 'scenarios' }, label: 'Scenarios' },
  { route: { name: 'cases' }, label: 'Cases' },
  { route: { name: 'memory' }, label: 'Memory' },
  { route: { name: 'rulebook' }, label: 'Rulebook' },
  { route: { name: 'evaluation' }, label: 'Evaluation' },
]

export default function App() {
  const route = useRoute()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [metaTrouble, setMetaTrouble] = useState<unknown>(null)
  const [views, setViews] = useState<Record<string, View>>({})
  // Bumped by the banner's Retry. Every view that fetches on mount watches it, so one press brings the whole
  // screen back instead of only the rail's half of it: the officer who presses Retry on the banner while she is
  // looking at an empty case list means "load this screen", not "load the version string".
  const [reload, setReload] = useState(0)

  // The trouble clears when the answer arrives, never when the request leaves: a banner that disappears the
  // instant Retry is pressed says the wire is back before anybody knows whether it is.
  const loadMeta = useCallback(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m)
        setMetaTrouble(null)
      })
      .catch((e) => setMetaTrouble(e))
  }, [])

  useEffect(() => {
    loadMeta()
  }, [loadMeta])

  // Re-runs the fetches in place. It used to be `window.location.reload()`, which does come back on a hash route,
  // but it also throws away every case the officer opened in this session, and the wire coming back is not a
  // reason to lose them.
  const retry = useCallback(() => {
    loadMeta()
    setReload((n) => n + 1)
  }, [loadMeta])

  const remember = useCallback((v: View) => setViews((prev) => ({ ...prev, [v.case.id]: v })), [])

  const current = route.name === 'case' ? 'cases' : route.name === 'new' ? 'cases' : route.name

  return (
    <div className="app">
      <aside className="rail">
        <div className="rail-top">
          <a className="wordmark" href="#/scenarios">
            <span className="hi" lang="hi">
              सत्यापन
            </span>
            <span className="en">Satyapan</span>
          </a>
          {/* The product's own sentence, under its name. It used to sit in the rail's foot in small grey type,
              below a column of empty dark, which is the last place anyone reads. */}
          <p className="rail-line">Verify the instruction, not just the pixels.</p>
        </div>
        <nav className="nav" aria-label="Sections">
          {NAV.map((n) => (
            <a key={n.label} href={href(n.route)} aria-current={current === n.route.name ? 'page' : undefined}>
              {n.label}
            </a>
          ))}
        </nav>
        <div className="rail-foot">
          {meta && (
            <p>
              <strong>{meta.bank_name}</strong>
            </p>
          )}
          {/* The mock disclosure, word for word, folded into one line that opens: eleven lines of grey fine print
              on every screen read as small print a visitor learns to skip, not as a statement they can check. */}
          {meta && (
            <details className="rail-disclose">
              <summary>Everything shown is synthetic</summary>
              <p>{integrationHonesty(meta)}</p>
            </details>
          )}
          <p>Team “Team”: Aman Bihari, Bhawna</p>
        </div>
      </aside>
      <main className="main">
        {/* No port and no shell command: the port was hardcoded and wrong whenever the service ran anywhere else,
            and no branch officer is going to type `satyapan serve`. Say what happened and what she can do. The
            banner is about the service; each view says separately what this screen could not read, because an
            officer reading "nothing is current" still needs to know the empty list in front of her is a failure
            and not an empty session. */}
        {metaTrouble ? (
          <div className="banner" role="alert">
            <span>
              {metaTrouble instanceof OfflineError
                ? 'The Satyapan service is not answering, so nothing on this screen is current. Ask whoever set the laptop up to start it, then press Retry.'
                : 'The Satyapan service answered without the rulebook and the labels this screen reads from, so parts of it are missing. Press Retry.'}
            </span>
            <button className="btn btn-sm" onClick={retry}>
              Retry
            </button>
          </div>
        ) : null}
        {route.name === 'scenarios' && <Scenarios onRun={remember} reload={reload} />}
        {route.name === 'cases' && <Cases reload={reload} />}
        {route.name === 'new' && <NewCase onView={remember} />}
        {route.name === 'case' && (
          <CaseView id={route.id} view={views[route.id]} onView={remember} meta={meta} reload={reload} />
        )}
        {route.name === 'memory' && <Memory reload={reload} />}
        {route.name === 'rulebook' && <Rulebook meta={meta} trouble={metaTrouble} onRetry={retry} />}
        {route.name === 'evaluation' && <Evaluation reload={reload} />}
      </main>
    </div>
  )
}
