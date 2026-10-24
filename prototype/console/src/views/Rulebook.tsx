import type { Label, Meta } from '../lib/api'
import { FAMILY_WORD, SEVERITY_WORD } from '../lib/spans'
import { Trouble } from '../ui/trouble'

// The rows of the integrations table, in the order the page shows them: outside lookups, the forensics
// components (voice, video when the engine reports one, document), then the evidence signer.
export function integrationRows(meta: Meta): Label[] {
  const video = meta.forensics.video ? [meta.forensics.video] : []
  return [...meta.adapters, meta.forensics.audio, ...video, meta.forensics.document, meta.signer]
}

// One sentence about what is mocked, counted from the same labels the table prints, so the rail and the
// Rulebook page can never disagree about the arithmetic.
//
// The forensics clause says what is loaded, not what is "not a mock". The default audio component is
// NullAudioForensics: it abstains on every clip because no calibrated detector ships, and the rehearsal
// scenarios script a SIMULATED result instead, labelled as such on the case. Calling it "running" would present
// a stand-in as live, which is the one thing this sentence exists to prevent.
export function integrationHonesty(meta: Meta): string {
  const mocked = meta.adapters.filter((a) => a.mock).length
  const lookups = `${mocked} of ${meta.adapters.length} outside lookups${meta.signer.mock ? ' and the evidence signer' : ''} are mocks`
  // Read off the labels the engine sends, so the sentence follows what is actually loaded on this machine.
  const voice = /DF Arena|AASIST/.test(meta.forensics.audio.production_source)
    ? 'the voice check runs here'
    : 'no calibrated voice detector is loaded, so voice checks abstain'
  const video = meta.forensics.video
  const face = !video
    ? ''
    : /GenD/.test(video.production_source)
      ? ', videos also get the face check'
      : ', videos get the voice check on their sound only'
  return `${lookups}; the document detector runs here, ${voice}${face}, and the rehearsal scenarios script a result marked SIMULATED.`
}

// Every rule with its citation, and every outside lookup with the label that says what it mocks.
//
// The whole page is rendered from `/api/meta`, which App fetches, so App hands down whatever went wrong with it
// along with the way to ask again. Without that this page said "Loading…" for as long as the service stayed down —
// a sentence that is false the moment the request has already failed, and the one word a judge reads as "slow"
// rather than "broken".
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
            Each rule carries a primary citation and the date it was checked. A rule whose citation is not verified is demoted to soft when
            the rulebook loads, so it can never anchor a RED. Rulebook hash <span className="hash">{meta.rulebook.sha256.slice(0, 16)}</span>.
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
          In the prototype every outside lookup reads a JSON file. The label says what the real source is, who owns it and how it is reached.{' '}
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
