import { useCallback, useEffect, useState } from 'react'
import { api, type CaseSummary } from '../lib/api'
import { spellsAmount, when } from '../lib/format'
import { Rupee } from '../ui/rupee'
import { Trouble } from '../ui/trouble'

export function Cases({ reload = 0 }: { reload?: number }) {
  const [list, setList] = useState<CaseSummary[] | null>(null)
  const [trouble, setTrouble] = useState<unknown>(null)

  // The fetch is a named function so Retry can re-run it in place. It used to be an anonymous promise in the
  // effect with no `.catch` at all: with the wire cut this page rendered its heading, its lede and nothing else,
  // and the only trace was an unhandled rejection in the devtools console.
  const load = useCallback(() => {
    api
      .cases()
      .then((l) => {
        setList([...l].reverse())
        setTrouble(null) // on the answer, not on the request: Retry must not look successful before it is
      })
      .catch((e) => {
        setList(null)
        setTrouble(e)
      })
  }, [])

  useEffect(() => {
    load()
  }, [load, reload])

  return (
    <>
      <header className="page-head">
        <h1>Cases this session</h1>
        <a className="btn btn-primary" href="#/new">
          Open a new case
        </a>
      </header>
      <section className="section">
        {/* An empty list and a failed list are different facts. "No cases yet" is true about an empty session and
            a lie when the request never arrived, so it only ever renders off a list the service actually sent. */}
        {trouble ? (
          <Trouble error={trouble} what="the case list" onRetry={load} />
        ) : (
          list && list.length === 0 && <p className="muted">No cases yet; run a scenario or open one by hand.</p>
        )}
        <ul className="rows">
          {list?.map((c) => (
            <li className="row-item case-row" key={c.id}>
              {c.outcome ? <span className={`tag tag-${c.outcome}`}>{c.outcome}</span> : <span className="tag">no verdict</span>}
              <span>
                <a href={`#/case/${c.id}`} className="num">
                  {c.id}
                </a>{' '}
                · {c.flag.reason}
                {c.flag.amount_inr > 0 && !spellsAmount(c.flag.reason) && (
                  <>
                    {' · '}
                    <Rupee n={c.flag.amount_inr} />
                  </>
                )}
                {c.about && (
                  <>
                    {' · '}
                    <span className="muted">{c.about}</span>
                  </>
                )}
              </span>
              <span className="muted">{c.status}</span>
              <span className="muted">{when(c.created_at)}</span>
            </li>
          ))}
        </ul>
      </section>
    </>
  )
}
