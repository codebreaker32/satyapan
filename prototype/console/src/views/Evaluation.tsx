import { useCallback, useEffect, useState } from 'react'
import { api, type Accuracy, type Evaluation as Result, type EvalRow } from '../lib/api'
import { Trouble } from '../ui/trouble'

// The labelled evaluation, exactly as `satyapan evaluate` wrote it (data/eval/results.json). Nothing is computed
// here: the page shows the file's own numbers, its own lists, and the line that says the set is synthetic.
export function Evaluation({ reload = 0 }: { reload?: number }) {
  const [result, setResult] = useState<Result | null>(null)
  const [trouble, setTrouble] = useState<unknown>(null)

  const load = useCallback(() => {
    return api
      .evaluation()
      .then((r) => {
        setResult(r)
        setTrouble(null)
      })
      .catch((e) => {
        setResult(null)
        setTrouble(e)
      })
  }, [])

  useEffect(() => {
    load()
  }, [load, reload])

  if (trouble) return <Trouble error={trouble} what="the evaluation" onRetry={load} />
  if (!result) return <p className="muted">Loading the evaluation…</p>

  const s = result.summary
  const rows = new Map(result.rows.map((r) => [r.id, r]))
  const named = (ids: string[]) =>
    ids.length === 0 ? (
      <p className="muted">None.</p>
    ) : (
      <ul className="stack" style={{ gap: 4 }}>
        {ids.map((id) => {
          const r = rows.get(id) as EvalRow
          return (
            <li key={id}>
              <span className="hash">{id}</span> · {r.category} · {r.outcome}
              {r.fired.length > 0 && <span className="muted small"> · {r.fired.join(', ')}</span>}
            </li>
          )
        })}
      </ul>
    )

  return (
    <div className="stack" style={{ gap: 24 }}>
      <header className="page-head">
        <div className="stack">
          <h1>Evaluation</h1>
          <p>
            <strong>{result._note}</strong> {s.total} messages, each labelled scam or genuine by what it really is, run through
            the engine on {result.made}
            {result.commit ? ` (commit ${result.commit})` : ''}. Rulebook {result.environment.rulebook}; audio detector{' '}
            {result.environment.audio_detector}; meaning model {result.environment.meaning_model ? 'on' : 'off'}.
          </p>
        </div>
      </header>

      <section className="section">
        <h2>Headline</h2>
        <div className="grid-2">
          <div className="stack">
            <h3>Scams in scope ({s.in_scope_scams.n})</h3>
            <p>
              <strong>{s.in_scope_scams.flagged_pct}% flagged</strong>: {s.in_scope_scams.RED} stopped (RED), {s.in_scope_scams.AMBER}{' '}
              sent to verification (AMBER). {s.in_scope_scams.GREY + s.in_scope_scams.MATCHES} missed.
            </p>
          </div>
          <div className="stack">
            <h3>Genuine messages ({s.genuine.n})</h3>
            <p>
              <strong>{s.genuine.RED} stopped</strong> ({s.genuine.false_stop_pct}%). {s.genuine.AMBER} asked to verify first (
              {s.genuine.asked_to_verify_pct}%), {s.genuine.GREY + s.genuine.MATCHES} left alone ({s.genuine.left_alone_pct}%).
            </p>
          </div>
          <div className="stack">
            <h3>Scams outside scope ({s.out_of_scope_scams.n})</h3>
            <p>
              {s.out_of_scope_scams.RED + s.out_of_scope_scams.AMBER} flagged ({s.out_of_scope_scams.flagged_pct}%). Family
              emergency, lottery, job and similar scams are not what Satyapan checks; they are listed so the gap is visible.
            </p>
          </div>
        </div>
      </section>

      <DetectorAccuracy reload={reload} />

      <section className="section">
        <h2>By category</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Label</th>
              <th>Category</th>
              <th>n</th>
              <th>RED</th>
              <th>AMBER</th>
              <th>GREY</th>
              <th>MATCHES</th>
            </tr>
          </thead>
          <tbody>
            {s.by_category.map((c) => (
              <tr key={c.label + c.category}>
                <td>{c.label}</td>
                <td>{c.category}</td>
                <td>{c.n}</td>
                <td>{c.RED}</td>
                <td>{c.AMBER}</td>
                <td>{c.GREY}</td>
                <td>{c.MATCHES}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="section">
        <h2>In-scope scams missed</h2>
        {named(s.missed)}
        <h2>Genuine messages stopped</h2>
        {named(s.false_stops)}
        <h2>Genuine messages asked to verify first</h2>
        {named(s.asked_to_verify)}
        <h2>Left out of the numbers</h2>
        {result.excluded.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <ul className="stack" style={{ gap: 4 }}>
            {result.excluded.map((e) => (
              <li key={e.id}>
                <span className="hash">{e.id}</span>: {e.why}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

const CELL_WORDS: Record<string, string> = {
  'video/hd': 'HD video',
  'video/sd': 'WhatsApp-size video',
  'hi/clean': 'Hindi, clean recording',
  'hi/whatsapp-opus': 'Hindi, WhatsApp voice note',
  'hi/phone-8k': 'Hindi, phone call (8 kHz)',
  'en/clean': 'English, clean recording',
  'en/whatsapp-opus': 'English, WhatsApp voice note',
  'en/phone-8k': 'English, phone call (8 kHz)',
}

const SOURCE_WORDS: Record<string, string> = {
  itw: 'In-the-Wild (English)',
  fleurs: 'Google FLEURS (Hindi)',
  indicsynth: 'IndicSynth (Hindi clones)',
  gramvaani: 'Gram Vaani (Hindi phone calls)',
  'wikimedia-commons': 'Wikimedia Commons',
  'unidatapro-sample': 'UniDataPro face-swap sample',
}
// "fleurs (simulated)" -> "Google FLEURS (Hindi), re-encoded"; "wikimedia-commons+whatsapp-like" -> "..., WhatsApp-size copies"
function sourceWords(id: string): string {
  const [base, how] = id.replace(' (simulated)', '+re-encoded').split('+')
  const word = SOURCE_WORDS[base] ?? base
  return how ? `${word}, ${how === 'whatsapp-like' ? 'WhatsApp-size copies' : 're-encoded'}` : word
}

// The face and voice checks' measured accuracy, exactly as scripts/accuracy_card.py wrote it from the calibration
// runs: the outcomes are the ones the officer sees (flagged, unsure, no signs), false alarms are also counted on
// genuine clips that did not set the threshold, and the failure cases are named. A judge's first question about a
// detector is "how often is it wrong on real people"; the answer is on screen, with its sample sizes.
function DetectorAccuracy({ reload }: { reload: number }) {
  const [acc, setAcc] = useState<Accuracy | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    api
      .accuracy()
      .then((a) => {
        setAcc(a)
        setFailed(false)
      })
      .catch(() => setFailed(true))
  }, [reload])
  if (failed)
    return (
      <section className="section">
        <h2>Face and voice checks</h2>
        <p className="muted">The measured accuracy of the face and voice checks is not on this laptop (scripts/accuracy_card.py writes it).</p>
      </section>
    )
  if (!acc) return null
  return (
    <section className="section">
      <h2>Face and voice checks: measured accuracy</h2>
      <p>
        {acc._note} Face: {acc.models.face}. Voice: {acc.models.voice}. Made {acc.made}.
      </p>
      <table className="table">
        <thead>
          <tr>
            <th>Check</th>
            <th>Kind of input</th>
            <th>Genuine clips judged</th>
            <th>False alarms</th>
            <th>False alarms, held out</th>
            <th>Genuine unsure</th>
            <th>Fakes judged</th>
            <th>Caught</th>
            <th>Unsure</th>
            <th>Missed</th>
            <th>Declined (genuine / fake)</th>
          </tr>
        </thead>
        <tbody>
          {acc.cells.map((c) => (
            <tr key={c.cell}>
              <td>{c.check}</td>
              <td>{CELL_WORDS[c.cell] ?? c.cell}</td>
              <td>{c.genuine.judged}</td>
              <td>{c.genuine.flagged}</td>
              <td>{c.genuine.false_alarm_heldout_pct ?? '-'}%</td>
              <td>{c.genuine.unsure}</td>
              <td>{c.fake.judged}</td>
              <td>{c.fake.flagged}</td>
              <td>{c.fake.unsure}</td>
              <td>{c.fake.no_signs}</td>
              <td>
                {c.genuine.declined} / {c.fake.declined}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        Flagged counts in the score; unsure is not counted; declined means the check would not judge the clip (too short, face
        too small, frames disagree). Sources:{' '}
        {[...new Set(acc.cells.flatMap((c) => [...c.genuine.sources, ...c.fake.sources]).map(sourceWords))].join('; ')}.
      </p>
      <h3>Where it fails</h3>
      <ul className="stack" style={{ gap: 4 }}>
        {acc.failure_cases.map((f) => (
          <li key={f.text}>
            <b>{f.check}:</b> {f.text}
          </li>
        ))}
      </ul>
    </section>
  )
}
