import type { CaseView } from '../lib/api'

// The engine's enum values in the officer's words ("BANK_SELF" printed as "BANK SELF", "MOVE_FD" as "move fd").
const ISSUER_NAMES: Record<string, string> = {
  ED: 'ED', CBI: 'CBI', POLICE: 'the police', COURT: 'a court', RBI: 'RBI', SEBI: 'SEBI', CUSTOMS: 'customs',
  TRAI_DOT: 'TRAI or the telecom department', TRANSPORT: 'the transport department', MUNICIPAL: 'a municipal body',
  BANK_SELF: 'the bank itself',
}
const INSTRUCTION_NAMES: Record<string, string> = {
  TRANSFER_TO_ACCOUNT: 'transfer to an account', MOVE_FD: 'break a fixed deposit', INVEST_FOR_RETURNS: 'invest for returns',
  RETURN_EXCESS_CREDIT: 'send back money credited by mistake', PAY_FEE_TO_VERIFY: 'pay a fee to verify',
  PAY_CHALLAN: 'pay a traffic challan', PAY_LOCAL_TAX: 'pay a local tax',
}

// What the engine could and could not read out of THIS message, on every outcome.
//
// The pass-5 judge pasted ten messages and five got a verdict worth arguing with. In four of the five the engine
// had quietly failed to read one field — a Devanagari masthead it did not recognise as a claim of identity, a
// passive "is required to be remitted" it did not see as an instruction — and the screen gave no sign of it. GREY
// already composes a prose version of this; RED, AMBER and MATCHES said nothing at all.
//
// Every line here is derived from the same claim object the rules consumed, never written by hand, so the strip
// and the verdict cannot disagree. It is deliberately dull: it reports, it does not judge.
interface Props {
  view: CaseView
}

// "Latin" is a script name an officer reads as a language, and the extractor's version string is an internal
// identifier that has no business in officer prose (the rulebook ids were taken out of it two passes ago for
// exactly this reason). Say what she would say.
const SCRIPT: Record<string, string> = {
  hi: 'in Devanagari',
  en: 'in the Roman alphabet',
  mixed: 'in a mix of Devanagari and the Roman alphabet',
}
// Where the text came from matters as much as what was read: an OCR layer can itself misread, and the panel whose
// job is naming what could and could not be read should not hide that it was reading a scan.
const SOURCE: Record<string, string> = {
  transcript: 'transcript of the voice note or video',
  ocr: 'text read off the scanned notice',
  text: 'message as pasted',
}

export function Coverage({ view }: Props) {
  const claim = view.case.claim
  const v = view.case.verdict
  if (!claim || !v) return null

  // On MATCHES the same three fields are facts about the message, never shortfalls of the check. The bank signed
  // this message and has it in its outbound log, so "no instruction about money and no payee" describes a genuine
  // statement SMS correctly and completely; filing it under what the check "could not read", with a footer calling
  // it a gap, told the officer the check had fallen short on the one outcome where it had not.
  const describes = v.outcome === 'MATCHES'

  const read: string[] = []
  const missed: string[] = []

  // The open set is not a claim of identity and the strip may not frame it as one. The net reads the FORM of a
  // name — and the form of "Narcotics Control Bureau" is the form of "Credit Information Bureau (India)
  // Limited" — so "an authority it claims to be" would be the same false assertion the engine's own rule was
  // split in two to avoid. The body's name is not substituted either: it is attacker-controlled text, and it is
  // already quoted and highlighted in the message beside this strip.
  ;(claim.claimed_issuer !== 'NONE' ? read : missed).push(
    claim.claimed_issuer === 'OTHER'
      ? 'a government-sounding name, which is not the same as a claim of identity'
      : claim.claimed_issuer !== 'NONE'
        ? `an authority it claims to be (${ISSUER_NAMES[claim.claimed_issuer] ?? claim.claimed_issuer.replace(/_/g, ' ')})`
        : 'no authority it claims to be',
  )
  ;(claim.instruction !== 'NONE' ? read : missed).push(
    claim.instruction !== 'NONE' ? `an instruction (${INSTRUCTION_NAMES[claim.instruction] ?? claim.instruction.replace(/_/g, ' ').toLowerCase()})` : 'no instruction about money',
  )
  const payee = claim.payee.account || claim.payee.ifsc || claim.payee.vpa
  ;(payee ? read : missed).push(payee ? 'a payee to send money to' : 'no payee to send money to')


  // Claim-only mode has no artefact: the officer ticked boxes, nothing was read from a message, and saying "read
  // as Latin by picklist. It read an authority..." credits the extractor with the officer's own input.
  const picklist = claim.source === 'officer_picklist'

  return (
    <section className="coverage" aria-label="What the check could read">
      <h2 className="coverage-h">
        {picklist ? 'What the officer entered' : describes ? 'What this check read' : 'What this check could read'}
      </h2>
      <p className="coverage-line">
        {picklist ? (
          <>Claim-only mode: nothing was read; the officer ticked {join(read)}.</>
        ) : claim.source === 'none' ? (
          // It used to read "Read in the Roman alphabet, from the none. It read nothing." about a recording that
          // reached the server silent: the strip named a script and a source for text that did not exist.
          <>No text came out of what the customer showed, so the check had nothing to read.</>
        ) : (
          <>
            Read {SCRIPT[claim.language_hint] ?? claim.language_hint}, from the {SOURCE[claim.source] ?? claim.source}.
            It read {join(read)}.
            {missed.length > 0 ? (describes ? ` This message carries ${join(missed)}.` : ` It found ${join(missed)}.`) : ''}
          </>
        )}
      </p>
    </section>
  )
}

function join(parts: string[]): string {
  if (parts.length === 0) return 'nothing'
  if (parts.length === 1) return parts[0]
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}
