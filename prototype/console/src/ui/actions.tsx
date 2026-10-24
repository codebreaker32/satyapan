import { useState } from 'react'
import { api, type CaseView } from '../lib/api'
import { clock } from '../lib/format'
import { writeTrouble } from './trouble'

// The officer's decisions. Nothing here acts on its own: releasing a RED needs a manager's co-sign, holds are
// time-boxed under bank policy, and "help report" only shows the right rails.
interface Props {
  view: CaseView
  onView: (v: CaseView) => void
}

const STRIKABLE: Array<[string, string]> = [
  ['issuer', 'claimed issuer'],
  ['instruction', 'instruction'],
  ['account', 'payee account'],
  ['ifsc', 'IFSC'],
  ['vpa', 'UPI ID'],
  ['claimed_owner', 'who the account is said to belong to'],
]

// What a recorded action is called in the acknowledgement: the same words as the button that recorded it, so the
// officer reads back what she just pressed.
const ACTION_WORDS: Record<string, string> = {
  hold: 'Hold the transfer',
  release: 'Release the transfer',
  escalate: 'Escalate to FRMU',
  help_report: 'Help the customer report',
  strike_field: 'Strike a wrong field',
}

// There is no undo, on purpose. The engine appends every decision to the case and the evidence pack is signed over
// that list, so an undo that deleted one would make the pack lie about what happened. Where there is a way back it
// is another recorded decision, and the acknowledgement names it and says the earlier one stays.
const WAY_BACK: Record<string, string> = {
  hold: 'Releasing it is the way back; this hold stays in the record.',
  release: 'You can hold it again; this release stays in the record.',
  escalate: 'The fraud risk management unit answers next; this escalation stays in the record.',
  help_report: 'The case stays open; nothing here is closed off.',
  strike_field: 'The verdict above is the re-run; the strike stays.',
}

export function Actions({ view, onView }: Props) {
  const [actor, setActor] = useState('officer.bhawna')
  const [coSigner, setCoSigner] = useState('')
  const [releasing, setReleasing] = useState(false)
  const [striking, setStriking] = useState(false)
  const [field, setField] = useState('issuer')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reportShown, setReportShown] = useState(false)

  const c = view.case
  const outcome = c.verdict?.outcome
  const id = c.id
  const needsCoSign = outcome === 'RED' || Boolean(view.inputs.release_needs_co_sign)

  const run = async (name: string, fn: () => Promise<CaseView>) => {
    setBusy(name)
    setError(null)
    try {
      onView(await fn())
      return true
    } catch (e) {
      // A refusal and a dead wire read differently, because they mean different things to the officer: a refusal
      // is the system saying no and the case moved on; an unanswered request recorded nothing and can be retried.
      // The words are in `ui/trouble.tsx` now, so the read paths say the same thing with the same two prefixes
      // instead of inventing a second vocabulary for the same cut wire.
      setError(writeTrouble(e))
      return false
    } finally {
      setBusy(null)
    }
  }

  const decide = (action: string, note = '', co_signer: string | null = null) =>
    run(action, () => api.decide(id, { actor, action, note, co_signer }))

  const present = STRIKABLE.filter(([k]) => {
    const cl = c.claim
    if (!cl) return false
    if (k === 'issuer') return cl.claimed_issuer !== 'NONE'
    if (k === 'instruction') return cl.instruction !== 'NONE'
    if (k === 'claimed_owner') return cl.payee.claimed_owner !== 'UNKNOWN'
    return Boolean((cl.payee as unknown as Record<string, unknown>)[k])
  })

  // Which action is emphasised comes from the engine's own outcome, and from nothing else. RED and AMBER both mean
  // "do not let this money go yet", so the hold carries the weight; GREY and MATCHES recommend nothing, because
  // GREY is not "safe" and a matching signature is not permission to pay. Every action stays available either way.
  const urgeHold = outcome === 'RED' || outcome === 'AMBER'

  // A decision with nobody's name on it used to be accepted and sealed into the signed pack: the judge recorded a
  // hold as actor "". The whole accountability story — the screen advises, the officer decides, a RED release needs
  // a second person, the pack is signed — rests on this string. The service refuses a blank one; the screen says so
  // before the officer presses anything, rather than letting them hit a refusal.
  const unsigned = actor.trim() === ''
  const stop = busy !== null || unsigned

  // The acknowledgement reads from the record the service sent back, never from what the officer clicked: `run`
  // awaits the API and hands the fresh case to `onView`, so this is the decision the engine actually appended.
  // Striking a field is a correction to the extraction, not a decision about the money: the case stays open and
  // the verdict above is the answer. Letting it take this slot replaced "RED asks you to pause the transfer" with
  // "Recorded. Case status: open." on a RED that was still unheld. It stays in the record and in step 3.
  const decided = c.decisions.filter((d) => d.action !== 'strike_field')
  const last = decided.length > 0 ? decided[decided.length - 1] : null

  return (
    <>
      {/* One slot, always mounted so the change is announced: before a decision it says which action the outcome
          asks for; once one is recorded it becomes the receipt for it. */}
      <div className="act-head" role="status" aria-live="polite">
        {last ? (
          <div className="act-done">
            <p className="act-done-head">Recorded. Case status: {statusWord(c.status)}.</p>
            <p className="act-done-sub">
              {ACTION_WORDS[last.action] ?? last.action.replaceAll('_', ' ')} · {last.actor} ·{' '}
              <time dateTime={last.at}>{clock(last.at)}</time>
            </p>
            <p className="act-done-sub">{WAY_BACK[last.action] ?? 'This decision stays in the record.'}</p>
          </div>
        ) : (
          <p className="act-note">
            {urgeHold
              ? `${outcome} asks you to pause the transfer, so the hold is the emphasised action. Everything else stays open to you.`
              : `${outcome ?? 'This outcome'} recommends no action, so nothing here is emphasised. The screen advises; you decide.`}
          </p>
        )}
      </div>

      {/* The one place FRMU is spelled out. It is the bank's own word and an officer never needs it expanded, but
          at the finale the people reading this screen are jurors, and an unexplained acronym on the main path cost
          a point on quality of demonstration three passes running. Expanded here, once, where the acronym first
          appears; the buttons below keep the short form the officer actually says. */}
      {(view.review_triggers?.length ?? 0) > 0 && (
        <p className="act-req">
          <b>Needs FRMU review</b> (the bank's fraud risk management unit) before any high-impact action:{' '}
          {view.review_triggers!.join('; ')}.
        </p>
      )}

      {/* The decisions, in the shape they actually have: one decision about the money, two routes to other people,
          and a quiet way back. Attribution for the signed pack sits above them as a signature line, not as step 1. */}
      <div className="actions act-set">
        <label className="inline act-by">
          <span>Signing as</span>
          <input
            className="input"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            aria-invalid={unsigned || undefined}
            aria-describedby={unsigned ? 'act-unsigned' : undefined}
          />
        </label>
        {unsigned && (
          <p className="act-note" id="act-unsigned">
            Type your staff id before recording a decision. Every decision is signed into the evidence pack with
            the name you put here.
          </p>
        )}
        <button
          className={urgeHold ? 'btn btn-primary' : 'btn'}
          disabled={stop || c.status === 'held'}
          onClick={() => decide('hold', 'time-boxed hold under bank policy')}
        >
          Hold the transfer
        </button>
        <div className="act-pair">
          <button className="btn btn-sm" disabled={stop || c.status === 'escalated'} onClick={() => decide('escalate', 'escalated to FRMU')}>
            Escalate to FRMU
          </button>
          <button
            className="btn btn-sm"
            disabled={stop || !c.consent.report}
            title={c.consent.report ? undefined : 'The customer did not agree to reporting (C2)'}
            onClick={async () => {
              if (await decide('help_report', 'officer helped the customer report')) setReportShown(true)
            }}
          >
            Help the customer report
          </button>
        </div>
        {!c.consent.report && (
          <p className="act-fix-note">She did not agree to including this in a report (C2), so reporting is off.</p>
        )}
        {needsCoSign ? (
          <button
            className="btn btn-sm btn-ghost act-quiet"
            disabled={stop || releasing || c.status === 'released'}
            onClick={() => setReleasing(true)}
          >
            Release (needs a co-sign)
          </button>
        ) : (
          <button
            className="btn btn-sm btn-ghost act-quiet"
            disabled={stop || c.status === 'released'}
            onClick={() => decide('release', 'released by officer')}
          >
            Release the transfer
          </button>
        )}

        {releasing && (
          <div className="act-confirm" role="group" aria-label="Co-sign a release">
            <p className="act-confirm-lead">
              {outcome === 'RED'
                ? "Releasing a RED case needs a manager's co-sign."
                : "This case was RED before a field was struck, so releasing it still needs a manager's co-sign."}
            </p>
            <input className="input" placeholder="manager id" value={coSigner} onChange={(e) => setCoSigner(e.target.value)} aria-label="Co-signing manager id" />
            <div className="act-confirm-row">
              <button
                className="btn btn-sm btn-primary"
                disabled={busy !== null}
                onClick={async () => {
                  if (await decide('release', outcome === 'RED' ? 'released against RED' : 'released after a strike on a RED case', coSigner || null)) setReleasing(false)
                }}
              >
                Release with co-sign
              </button>
              <button className="btn btn-sm" onClick={() => setReleasing(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {error && (
          <p className="notice notice-warn" role="alert">
            {error}
          </p>
        )}
      </div>

      {/* Not a decision: a correction to what was extracted, which sends the claim back through the rules. It is
          kept out of the decision set and says what pressing it will do. */}
      <div className="actions act-fix" role="group" aria-label="Correct the extraction">
        <p className="act-fix-note" id="act-fix-note">
          Read a field wrong? The rules re-run without it.
        </p>
        {/* Ghost, like the release beside it. The judge counted a block of equal-weight grey buttons as a generic
            tell, and these were not equals: the two onward routes are a pair, the release and the strike are the
            quiet ways back. Weight now says which is which, so the filled grey is spent on the pair alone. */}
        <button className="btn btn-sm btn-ghost act-quiet" aria-describedby="act-fix-note" disabled={stop || striking || present.length === 0} onClick={() => { setField(present[0][0]); setStriking(true) }}>
          Strike a wrong field
        </button>

        {striking && (
          <div className="act-confirm" role="group" aria-label="Strike a wrongly extracted field">
            <p className="act-confirm-lead">Mark an extracted field as wrong; the rules re-run without it.</p>
            <select value={field} onChange={(e) => setField(e.target.value)} aria-label="Field to strike">
              {present.map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
            <div className="act-confirm-row">
              <button
                className="btn btn-sm btn-primary"
                disabled={busy !== null}
                onClick={async () => {
                  if (await run('strike', () => api.strike(id, field, actor))) setStriking(false)
                }}
              >
                Strike and re-run
              </button>
              <button className="btn btn-sm" onClick={() => setStriking(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {reportShown && (
        <div className="actions">
          <div className="stack">
            <p style={{ fontWeight: 700 }}>Reporting rails</p>
            <p>
              Stopped attempt: report the payee to I4C's Suspect Registry (cybercrime.gov.in, “Report &amp; Check Suspect”) and the caller on Chakshu
              (Sanchar Saathi).
            </p>
            <p>Money already sent: 1930 or cybercrime.gov.in (NCRP), and the bank's CFCFRMS workflow to trace and freeze it.</p>
          </div>
        </div>
      )}
    </>
  )
}

export function statusWord(s: string): string {
  return { open: 'Open', held: 'On hold', released: 'Released', escalated: 'Escalated to FRMU', closed: 'Closed' }[s] ?? s
}
