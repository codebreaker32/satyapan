import { useCallback, useEffect, useState } from 'react'
import { api, type CaseView as View, type Meta } from '../lib/api'
import { clock, spellsAmount, when } from '../lib/format'
import { Actions, statusWord } from '../ui/actions'
import { Rupee } from '../ui/rupee'
import { VerdictBand } from '../ui/band'
import { CustomerCard } from '../ui/card'
import { Check } from '../ui/check'
import { Coverage } from '../ui/coverage'
import { EvidencePanel } from '../ui/evidence'
import { Trouble, writeTrouble } from '../ui/trouble'

interface Props {
  id: string
  view: View | undefined
  onView: (v: View) => void
  meta: Meta | null
  reload?: number
}

// One obvious path through a case. The step strip names the three steps and jumps to them; the hash is the router's,
// so these scroll rather than navigate.
const STEPS: Array<[string, string]> = [
  ['claims', 'What the message claims'],
  ['checked', 'What we checked it against'],
  ['record', 'The record and the evidence'],
]

// Steps 1 and 2 are the two columns of one grid above 960px, so scrolling alone would land you in the same place
// twice. The jump also moves focus to the step's own heading (tabIndex -1), which is what tells a keyboard or
// screen-reader user — and the e2e — which of the two columns the strip actually took you to. `scroll-margin-top`
// on the targets keeps the sticky strip off the heading it just jumped to.
const jumpTo = (id: string) => {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  el.focus({ preventScroll: true })
}

export function CaseView({ id, view, onView, meta, reload = 0 }: Props) {
  // The case itself not arriving replaces the page: there is no case to show. A re-encode or a proposal failing is
  // not that, and it used to be treated as if it were — `setError` here blanked the whole case screen, verdict
  // band and customer card included, because the officer pressed a rehearsal button with the wire down. Those two
  // now answer beside their own controls.
  const [trouble, setTrouble] = useState<unknown>(null)
  const [reencodeError, setReencodeError] = useState<string | null>(null)
  const [proposeError, setProposeError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [analyst, setAnalyst] = useState('analyst.aman')
  const [proposed, setProposed] = useState<string | null>(null)

  const loadCase = useCallback(() => {
    api
      .getCase(id)
      .then((v) => {
        setTrouble(null) // on the answer, not on the request: Retry must not look successful before it is
        onView(v)
      })
      .catch((e) => setTrouble(e))
  }, [id, onView])

  useEffect(() => {
    if (!view) loadCase()
  }, [view, loadCase, reload])

  if (!view && trouble)
    return (
      <>
        <header className="page-head">
          <div className="stack">
            {/* `case-head` so the id keeps the display face it has everywhere else in the console, at the
                heading's own size: the rule that takes `.num` off its 1.2em step is scoped to this class. */}
            <h1 className="case-head">
              Case <span className="num">{id}</span>
            </h1>
          </div>
        </header>
        <section className="section">
          <Trouble error={trouble} what={`case ${id}`} onRetry={loadCase} />
        </section>
      </>
    )
  if (!view) return <p className="section muted">Loading case {id}…</p>

  const titles: Record<string, string> = {}
  meta?.rulebook.rules.forEach((r) => (titles[r.id] = r.title))
  const c = view.case
  const f3 = c.verdict?.signals.find((s) => s.family === 'F3')
  const canReencode = Boolean(view.scenario?.then_forensics) && f3?.severity !== 'abstain'

  const reencode = async () => {
    if (!view.scenario) return
    setBusy(true)
    setReencodeError(null)
    try {
      const next = await api.reencode(view.scenario.id, c.id)
      onView({ ...next, scenario: view.scenario })
    } catch (e) {
      setReencodeError(writeTrouble(e))
    } finally {
      setBusy(false)
    }
  }

  const propose = async () => {
    setBusy(true)
    setProposeError(null)
    try {
      const e = await api.propose(c.id, analyst, 'proposed from the console')
      setProposed(`${e.id} proposed as ${e.status}; a second analyst must approve it in Memory.`)
    } catch (e) {
      setProposeError(writeTrouble(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {c.verdict && <VerdictBand view={view} titles={titles} />}

      {/* The counter pane. What the customer hears and what the officer does next sit together, above the fold at
          1280x720, because the card is the only artefact the customer ever sees. The officer's forensic detail is
          one step below, never between the verdict and the card. */}
      {c.verdict && (
        <section className="counter">
          <div className="counter-col">
            <h2>What you tell the customer</h2>
            {view.card ? (
              <CustomerCard hi={view.card.hi} en={view.card.en} />
            ) : (
              <p className="muted">No card for this case yet.</p>
            )}
          </div>
          <div className="counter-col counter-act">
            <h2>What you do next</h2>
            <Actions view={view} onView={(v) => onView({ ...v, scenario: view.scenario })} />
          </div>
        </section>
      )}

      {c.verdict && (
        <nav className="steps" aria-label="This case, step by step">
          {STEPS.map(([id, label], i) => (
            <button type="button" className="step" key={id} onClick={() => jumpTo(id)}>
              <b>{i + 1}</b> {label}
            </button>
          ))}
          <a className="step step-out" href="#/cases">
            All cases
          </a>
        </nav>
      )}

      {c.verdict && <Coverage view={view} />}

      {view.scenario?.then_forensics && (
        <div className="actions">
          {canReencode ? (
            <>
              <span style={{ fontWeight: 600 }}>Rehearsal step: the same voice note after WhatsApp re-encoding at 8 kHz, where forensics abstain.</span>
              <button className="btn" onClick={reencode} disabled={busy}>
                Re-encode and run again
              </button>
            </>
          ) : (
            <p className="notice">Forensics abstained after re-encoding. The verdict did not move: it rests on the same two checks.</p>
          )}
          {reencodeError && (
            <p className="notice notice-warn" role="alert">
              {reencodeError}
            </p>
          )}
        </div>
      )}

      {c.claim && <Check view={view} titles={titles} />}

      <section className="section">
        <h2 id="record" tabIndex={-1}>
          <span className="step-no">3</span> The record and the evidence
        </h2>
        <div className="grid-2">
          <div className="stack">
            <h3 className="case-head">
              <span>Case</span> <span className="num">{c.id}</span> <span className="tag">{statusWord(c.status)}</span>
            </h3>
            <div className="rows">
              <div className="row-item label">
                <strong>Opened</strong>
                <span>{when(c.created_at)}</span>
              </div>
              <div className="row-item label">
                <strong>Bank flag</strong>
                <span>
                  {c.flag.reason}
                  {c.flag.amount_inr > 0 && !spellsAmount(c.flag.reason) && (
                    <>
                      {' · '}
                      <Rupee n={c.flag.amount_inr} />
                    </>
                  )}
                  {(c.flag.payee_vpa || c.flag.payee_account) && (
                    <>
                      {' · paying to '}
                      <span className="hash">{c.flag.payee_vpa || c.flag.payee_account}</span>
                    </>
                  )}
                  {' · '}
                  {c.flag.channel}
                </span>
              </div>
              <div className="row-item label">
                <strong>Consent, read aloud in {c.consent.read_aloud_lang === 'hi' ? 'Hindi' : 'English'}</strong>
                <span>
                  check this message: {c.consent.check ? 'yes' : 'no'} · include it in a report: {c.consent.report ? 'yes' : 'no'} · add its
                  fingerprint to campaign memory: {c.consent.memory ? 'yes' : 'no'}
                  {c.consent.recorded_at ? ` · recorded ${clock(c.consent.recorded_at)}` : ''}
                </span>
              </div>
              <div className="row-item label">
                <strong>Mode</strong>
                <span>{view.inputs.mode === 'claim-only' ? 'claim-only: the officer ticked what she was told' : 'media shown by the customer'}</span>
              </div>
              {c.verdict && (
                <div className="row-item label">
                  <strong>Policy</strong>
                  <span>
                    {c.verdict.policy_version} · rulebook {meta?.rulebook.version ?? ''} · {c.verdict.explanation}
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="stack">
            <h3>Decisions</h3>
            {c.decisions.length === 0 && <p className="muted">No decision yet. The screen advises; the officer decides.</p>}
            <ul className="rows">
              {c.decisions.map((d, i) => (
                <li className="row-item decision" key={i}>
                  <time dateTime={d.at}>{clock(d.at)}</time>
                  <span>
                    <strong>{d.actor}</strong> {d.action.replaceAll('_', ' ')}
                    {d.note ? ` · ${d.note}` : ''}
                  </span>
                </li>
              ))}
            </ul>
            {c.consent.memory && c.claim && (
              <div className="inline" style={{ marginTop: 8 }}>
                <input className="input" style={{ width: 200 }} value={analyst} onChange={(e) => setAnalyst(e.target.value)} aria-label="Analyst id" />
                {/* the service refuses an unnamed proposal, so the screen says so before the officer presses it */}
                <button className="btn" onClick={propose} disabled={busy || proposed !== null || analyst.trim() === ''}>
                  Propose for campaign memory
                </button>
                {proposed && <span className="muted">{proposed}</span>}
                {proposeError && (
                  <p className="notice notice-warn" role="alert">
                    {proposeError}
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </section>

      {c.verdict && (
        <section className="section section-alt">
          <h2>Signed evidence pack</h2>
          <EvidencePanel caseId={c.id} signer={meta?.signer ?? null} version={c.decisions.length} />
        </section>
      )}
    </>
  )
}
