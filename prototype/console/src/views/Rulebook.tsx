import type { Label, Meta } from '../lib/api'
import { FAMILY_WORD, SEVERITY_WORD } from '../lib/spans'
import { Trouble } from '../ui/trouble'

// The rows of the integrations table, in the order the page shows them: outside lookups, the forensics components
// (with the local face and voice service when the engine uses one), then the evidence signer.
export function integrationRows(meta: Meta): Label[] {
  const service = meta.forensics.service
  return [...meta.adapters, meta.forensics.audio, meta.forensics.document, ...(service ? [service] : []), meta.signer]
}

// One sentence about what is mocked, counted from the same labels the table prints, so the rail and the
// Rulebook page can never disagree about the arithmetic.
//
// The forensics clause says what is actually loaded, read from /api/meta, never a fixed sentence: it used to say "no
// calibrated audio detector is loaded" on the same screen where the live face and voice checks ran. Calling a
// stand-in "running" would present it as live, and calling a running check absent is just as untrue.
export function integrationHonesty(meta: Meta): string {
  const mocked = meta.adapters.filter((a) => a.mock).length
  const lookups = `${mocked} of ${meta.adapters.length} outside lookups${meta.signer.mock ? ' and the evidence signer' : ''} are mocks`
  const sim = 'the rehearsal scenarios script a result marked SIMULATED'
  const service = meta.forensics.service
  if (service) {
    const h = service.health
    if (!h?.ok) return `${lookups}; the document check runs here, but the face and voice service is not answering, so those checks abstain; ${sim}.`
    const voice = h.audio?.loaded ?? h.audio?.installed
    const checks = voice
      ? 'the face check, the voice check and the document check run here on this laptop'
      : 'the face check and the document check run here on this laptop; the voice model is not loaded, so the voice check abstains'
    return `${lookups}; ${checks}, and each says "unsure" when it cannot judge; ${sim}.`
  }
  const voiceHere = !meta.forensics.audio.production_source.startsWith('No voice detector')
  return `${lookups}; the document check runs here, ${voiceHere ? 'and so does the voice check' : 'no voice detector is loaded, so the voice check abstains'}; ${sim}.`
}

// Every rule with its citation, and every outside lookup with the label that says what it mocks.
//
// The whole page is rendered from `/api/meta`, which App fetches, so App hands down whatever went wrong with it
// along with the way to ask again. Without that this page said "Loading…" for as long as the service stayed down —
// a sentence that is false the moment the request has already failed, and a word that reads as "slow" rather
// than "broken".
export function Rulebook({ meta, trouble, onRetry }: { meta: Meta | null; trouble?: unknown; onRetry?: () => void }) {
  if (!meta)
    return (
      <>
        <header className="page-head">
          <div className="stack">
            <h1>Rulebook</h1>
          </div>
        </header>
        <section className="section">
          {trouble ? (
            <Trouble error={trouble} what="the rulebook and the integration labels" onRetry={onRetry ?? (() => {})} />
          ) : (
            <p className="muted">Loading…</p>
          )}
        </section>
      </>
    )
  const labels = integrationRows(meta)
  return (
    <>
      <header className="page-head">
        <div className="stack">
          <h1>Rulebook {meta.rulebook.version}</h1>
          <p>
            An unverified citation is demoted to soft, so it never anchors a RED. Hash <span className="hash">{meta.rulebook.sha256.slice(0, 16)}</span>.
          </p>
        </div>
      </header>
      <section className="section">
        <h2>Rules</h2>
        <ul className="rows">
          {meta.rulebook.rules.map((r) => (
            <li className="row-item rule" key={r.id}>
              <div className="stack" style={{ gap: 2 }}>
                <strong>{r.title}</strong>
                <span className="small muted">
                  {r.id} · {FAMILY_WORD[r.family]}
                </span>
              </div>
              <div className="stack" style={{ gap: 2 }}>
                <span className="cite">
                  {r.citation}
                  {r.checked ? ` · checked ${r.checked}` : ''}
                </span>
                {r.citation_url && (
                  <a className="cite" href={r.citation_url} target="_blank" rel="noreferrer">
                    {r.citation_url}
                  </a>
                )}
              </div>
              <div className="inline">
                <span className="tag">{SEVERITY_WORD[r.severity]}</span>
                <span className={r.verified ? 'tag' : 'tag tag-sim'}>{r.verified ? 'Citation verified' : 'Citation unverified'}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="section section-alt">
        <h2>Integrations, honestly labelled</h2>
        <p className="muted">
          {integrationHonesty(meta)}
        </p>
        <ul className="rows">
          {labels.map((l) => (
            <li className="row-item label" key={l.name}>
              <div className="stack" style={{ gap: 4 }}>
                <strong>{l.name}</strong>
                <span className={l.mock ? 'tag tag-accent' : 'tag'} style={{ justifySelf: 'start' }}>
                  {l.mock ? 'Mock' : 'Real component'}
                </span>
              </div>
              <div className="stack" style={{ gap: 2 }}>
                <span>{l.production_source}</span>
                <span className="small muted">
                  Owner: {l.owner} · Route: {l.route}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section className="section">
        <h2>Versions</h2>
        <p className="muted">
          Satyapan {meta.version} · fusion policy {meta.policy_version} · bank name in the rulebook: {meta.bank_name}
        </p>
      </section>
    </>
  )
}
