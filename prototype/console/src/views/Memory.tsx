import { useCallback, useEffect, useState } from 'react'
import { api, type MemoryEntry } from '../lib/api'
import { when } from '../lib/format'
import { Trouble, writeTrouble } from '../ui/trouble'

// Campaign memory: fingerprints of cases two analysts confirmed. A match only ever adds a soft signal.
// The same analyst under another spelling counts once. The engine compares a fuller identity key (lookalike letters
// and invisible marks too); this only keeps the button from inviting a press the engine will not count.
const nameKey = (s: string) => s.normalize('NFKC').toLowerCase().trim()
const sameAnalyst = (approvals: string[], analyst: string) => approvals.some((a) => nameKey(a) === nameKey(analyst))

export function Memory({ reload = 0 }: { reload?: number }) {
  const [entries, setEntries] = useState<MemoryEntry[] | null>(null)
  const [analyst, setAnalyst] = useState('analyst.suresh')
  // Two different failures with two different consequences: the list did not load (nothing was read, and Retry
  // reads it again), or an approval did not record (the two-person rule did not advance, and the button is still
  // there). `String(e)` carried neither, and put "Error: " in front of both.
  const [trouble, setTrouble] = useState<unknown>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    return api
      .memory()
      .then((m) => {
        setEntries(m.entries)
        setTrouble(null) // on the answer, not on the request: Retry must not look successful before it is
      })
      .catch((e) => {
        setEntries(null)
        setTrouble(e)
      })
  }, [])

  useEffect(() => {
    load()
  }, [load, reload])

  const approve = async (id: string) => {
    setError(null)
    try {
      await api.approve(id, analyst)
      await load()
    } catch (e) {
      setError(writeTrouble(e))
    }
  }

  return (
    <>
      <header className="page-head">
        <div className="stack">
          <h1>Campaign memory</h1>
          <p>Two different analysts approve each template. A match is soft: never RED on its own.</p>
          {/* A div, not a p: `.page-head p` would override the notice colour. */}
          <div className="notice" style={{ maxWidth: '70ch' }}>
            <span className="tag tag-sim">Seeded demo data</span> The shipped entries are synthetic; this session's proposals clear on reset.
          </div>
        </div>
        <label className="field">
          <span>Approving analyst</span>
          <input className="input" value={analyst} onChange={(e) => setAnalyst(e.target.value)} />
        </label>
      </header>
      <section className="section">
        {error && (
          <p className="notice notice-warn" role="alert">
            {error}
          </p>
        )}
        {trouble ? (
          <Trouble error={trouble} what="campaign memory" onRetry={load} />
        ) : (
          entries &&
          entries.length === 0 && (
            <p className="muted">Nothing in memory yet; propose a template from a case and a second analyst approves it.</p>
          )
        )}
        <ul className="rows">
          {entries?.map((e) => {
            const approvals = (e.approvals as string[] | undefined) ?? []
            const pending = e.status === 'pending'
            return (
              <li className="row-item memory" key={e.id}>
                <div className="stack" style={{ gap: 2 }}>
                  <strong>{e.id}</strong>
                  <span className={pending ? 'tag tag-sim' : 'tag'}>{pending ? 'Pending second approval' : 'Confirmed'}</span>
                </div>
                <div className="stack" style={{ gap: 4 }}>
                  <span>
                    <strong>{String(e.issuer)}</strong> · {String(e.instruction).replaceAll('_', ' ').toLowerCase()} · seen {String(e.count)}{' '}
                    {Number(e.count) === 1 ? 'time' : 'times'} · {when(String(e.first_seen))} to {when(String(e.last_seen))}
                  </span>
                  <span className="template">{String(e.template_text)}</span>
                  <span className="small muted">
                    Approvals: {approvals.join(', ') || 'none'}
                    {e.note ? ` · ${String(e.note)}` : ''}
                  </span>
                </div>
                <div>
                  {/* an approval with nobody's name on it is no approval: the two-person rule is the whole control
                      here, and the service refuses a blank analyst id */}
                  {pending && (
                    <button className="btn" onClick={() => approve(e.id)} disabled={sameAnalyst(approvals, analyst) || analyst.trim() === ''}>
                      {sameAnalyst(approvals, analyst) ? 'Needs a second analyst' : 'Approve'}
                    </button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      </section>
    </>
  )
}
