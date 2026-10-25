import { useCallback, useEffect, useState } from 'react'
import { api, type CaseView, type Scenario, type SessionTiming } from '../lib/api'
import { rupees } from '../lib/format'
import { go } from '../lib/router'
import { Trouble, writeTrouble } from '../ui/trouble'

// The finale runs through fixtures: five beats that show the mechanism, then the controls that show it is not
// trigger-happy. Every verdict on screen comes from the engine at the moment you press Run.
const DEMO_ORDER = ['S1-rm-voice-note', 'S1b-rm-own-phone', 'S2-rbi-video', 'S3-ed-summons', 'S4-claim-only']

// The engine verdicts in milliseconds, so a fixed "X.X s" would round to a meaningless 0.0 s.
// Show ms below a second, seconds above; the e2e mirrors this formatting.
const fmtVerdictTime = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`)

const KIND_WORD: Record<string, string> = {
  audio: 'voice note',
  video: 'video, audio track',
  image: 'scanned notice',
  pdf: 'PDF notice',
  text: 'text message',
}

export function Scenarios({ onRun, reload = 0 }: { onRun: (v: CaseView) => void; reload?: number }) {
  const [list, setList] = useState<Scenario[] | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [trouble, setTrouble] = useState<unknown>(null)
  const [resetArmed, setResetArmed] = useState(false)
  const [resetArmedAt, setResetArmedAt] = useState(0)
  const [resetDone, setResetDone] = useState<string | null>(null)
  const [timing, setTiming] = useState<SessionTiming | null>(null)
  // What the engine returned for each scenario in THIS session. Never the asserted value: a row only takes an
  // outcome colour once the engine has produced one, which is what keeps "nothing is pre-computed" true on screen.
  const [ran, setRan] = useState<Record<string, string>>({})

  // Session timing only: wall time to verdict in this serve session, cleared by the demo reset. Never a benchmark.
  const refreshTiming = () => {
    api.meta().then((m) => setTiming(m.session_timing)).catch(() => {})
  }

  // The landing is a read path like the others, and it was the last one still answering a dead wire with a bare
  // amber bar and no way back. The trouble is cleared on the ANSWER, never on the request, so Retry cannot look
  // like it worked before it has.
  const load = useCallback(() => {
    api
      .scenarios()
      .then((s) => {
        setList(s)
        setTrouble(null)
      })
      .catch((e) => setTrouble(e))
    refreshTiming()
  }, [])

  useEffect(() => {
    load()
  }, [load, reload])

  const run = async (id: string) => {
    setRunning(id)
    setError(null)
    try {
      const view = await api.runScenario(id)
      refreshTiming()
      const outcome = view.case.verdict?.outcome
      if (outcome) setRan((prev) => ({ ...prev, [id]: outcome }))
      onRun(view)
      go({ name: 'case', id: view.case.id })
    } catch (e) {
      setError(writeTrouble(e))
    } finally {
      setRunning(null)
    }
  }

  // Rehearsal: two deliberate clicks to reset, so a stray click, a double-click or a reflexive Enter never
  // wipes a live demo. Fixtures are never touched.
  const reset = async () => {
    if (!resetArmed) {
      setResetArmed(true)
      setResetArmedAt(Date.now())
      setResetDone(null)
      return
    }
    if (Date.now() - resetArmedAt < 500) return   // a double-click or immediate Enter is not a second decision
    setResetArmed(false)
    setError(null)
    try {
      const out = await api.demoReset()
      setResetDone(`Cleared ${out.cases_cleared} ${out.cases_cleared === 1 ? 'case' : 'cases'}; fixtures untouched.`)
      refreshTiming() // the server clears session timings on reset, so the p50 line drops away
      setRan({})      // and the rows go back to colourless: the engine has not run since the reset
      setList(await api.scenarios())
    } catch (e) {
      setError(writeTrouble(e))
    }
  }

  if (!list) {
    // The headline and the lede stay: they are what the screen IS, and a juror who arrives on a dead service
    // should still read what Satyapan does rather than an error on a blank page.
    return (
      <>
        <header className="page-head home-head">
          <div className="stack">
            <h1>Check the instruction behind a flagged transfer</h1>
            <p className="lede">
              The bank paused a transfer; an “official” notice tells the customer to send the money.
            </p>
          </div>
        </header>
        <section className="section">
          {trouble ? (
            <Trouble error={trouble} what="the scenario list" onRetry={load} />
          ) : (
            <p className="muted">Loading scenarios…</p>
          )}
        </section>
      </>
    )
  }

  const demo = DEMO_ORDER.map((id) => list.find((s) => s.id === id)).filter((s): s is Scenario => Boolean(s))
  const controls = list.filter((s) => !DEMO_ORDER.includes(s.id))

  return (
    <>
      {/* A worklist, not a document. The judge's words for the old landing were "the demo's first frame is a grey
          document": 114 words of prose and seventeen identical black Run buttons before a juror saw a single
          verdict. The product's one memorable object is the verdict band, and it was a click away from everything
          anyone saw first. Now the whole row is the control, the five beats are the first frame, and a row that
          has been run repaints in its own outcome colour, so the screen changes state in front of the room. */}
      <header className="page-head home-head">
        <div className="stack">
          <h1>Check the instruction behind a flagged transfer</h1>
          <p className="lede">
            The bank paused a transfer; an “official” notice tells the customer to send the money.
          </p>
        </div>
        <a className="btn" href="#/new">
          Open a case by hand
        </a>
      </header>

      {/* A run or a reset that did not work. It belongs beside the rows it was about, not in place of them: the
          list loaded, so replacing the whole screen with the failure would throw away what did work. */}
      {error && (
        <section className="section" style={{ paddingBottom: 0 }}>
          <p className="notice notice-warn" role="alert" style={{ maxWidth: '80ch' }}>
            {error}
          </p>
        </section>
      )}

      <section className="section home-list">
        <div className="home-sec">
          <h2>Five beats that show the mechanism</h2>
          {/* "pytest asserts RED" used to sit on every row, so the first thing a juror's eye met on the product's
              home screen was a test-runner's name. The claim it was making is worth keeping and belongs here,
              said once, in words anyone in the room can follow. Before a run a row now says nothing at all about
              the answer, which is the stronger version of "nothing is pre-computed". */}
          <p className="muted">Nothing is pre-computed: press a row to run the engine.</p>
        </div>
        <ul className="rows beats">
          {demo.map((s, i) => (
            <Row key={s.id} s={s} n={i + 1} ran={ran[s.id]} running={running} onRun={run} />
          ))}
        </ul>

        {/* Twelve controls behind a disclosure. They are the restraint evidence and they matter, but seventeen
            interchangeable rows in the first frame is what made this read as a harness rather than a product. */}
        <details className="home-more">
          <summary>
            {controls.length} more cases: controls that should not fire, and further attacks
          </summary>
          <ul className="rows">
            {controls.map((s) => (
              <Row key={s.id} s={s} ran={ran[s.id]} running={running} onRun={run} />
            ))}
          </ul>
        </details>
      </section>

      {/* The rehearsal controls live at the foot, not on the product's home screen: a reset button beside the
          headline told a juror they were looking at a demo harness before they had looked at anything else. */}
      <section className="section home-foot">
        <div className="inline">
          <span className="muted small">Rehearsal controls</span>
          {resetDone && <span className="muted small">{resetDone}</span>}
          <button type="button" className={resetArmed ? 'btn btn-primary btn-sm' : 'btn btn-sm'} disabled={running !== null}
                  onClick={reset} onBlur={() => setResetArmed(false)}>
            {resetArmed ? 'Press again to reset the demo' : 'Reset the demo'}
          </button>
          {timing && timing.count > 0 && timing.session_p50_verdict_ms != null && (
            <span className="muted small">
              p50 engine verdict time this session: {fmtVerdictTime(timing.session_p50_verdict_ms)} · engine only ·
              session timing, not a benchmark
            </span>
          )}
        </div>
      </section>
    </>
  )
}

// One control per row, and the row is it. The outcome colour only ever appears after the engine produced it:
// before a run the row says what the regression asserts, in words, with no colour; after a run it carries the
// verdict the engine just returned. A coloured edge on an unrun row would be the screen claiming an answer it
// has not computed, which is the one thing the landing's "nothing is pre-computed" line promises it never does.
function Row({ s, n, ran, running, onRun }: { s: Scenario; n?: number; ran?: string; running: string | null; onRun: (id: string) => void }) {
  const busy = running === s.id
  return (
    <li className={`scenario-row${n ? ' beat' : ''}${ran ? ` ran edge-${ran}` : ''}`}>
      <button type="button" className="scenario-hit" disabled={running !== null} onClick={() => onRun(s.id)}>
        {n && <span className="beat-no">{n}</span>}
        <span className="stack" style={{ gap: 2 }}>
          <span className="title">{s.title}</span>
          <span className="flag">
            Bank flag: {s.flag.reason}
            {s.mode === 'claim-only' ? ' · claim-only mode' : ` · ${KIND_WORD[s.media_kind] ?? s.media_kind}`}
            {s.has_rehearsal_forensics ? ' · forensics simulated' : ''}
          </span>
        </span>
        <span className="stack" style={{ gap: 2, textAlign: 'right' }}>
          {s.flag.amount_inr > 0 && <span className="rupee">{rupees(s.flag.amount_inr)}</span>}
          <span className="expect">{busy ? 'Running…' : ran ? `engine returned ${ran}` : ''}</span>
        </span>
      </button>
    </li>
  )
}

