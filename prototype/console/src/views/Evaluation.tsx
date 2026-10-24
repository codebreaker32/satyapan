import { useCallback, useEffect, useState } from 'react'
import { api, type Evaluation as Result, type EvalRow } from '../lib/api'
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
