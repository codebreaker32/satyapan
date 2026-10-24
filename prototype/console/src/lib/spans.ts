// Which words each check points at. Spans come from the engine's quote-grounded claim; this file only maps them
// to anchors the leader lines can find. A signal that rests on something outside the text (the sender number,
// the media file, the bank's signature, the bank's flag) points at a row in "Also checked".
import type { CaseView, Claim, Family, Outcome, Severity, Signal } from './api'

export interface SpanRef {
  key: string // anchor id, e.g. "issuer", "account", "cue:secrecy", "amount:0"
  label: string // what the officer sees on hover
  start: number
  end: number
  text: string
}

export function collectSpans(claim: Claim): SpanRef[] {
  const out: SpanRef[] = []
  const push = (key: string, label: string, span: { text: string; start: number; end: number } | null | undefined) => {
    if (span && span.end > span.start) out.push({ key, label, ...span })
  }
  push('issuer', 'Claimed issuer', claim.issuer_span)
  push('instruction', 'Instruction', claim.instruction_span)
  push('channel', 'Channel', claim.channel_span)
  push('account', 'Payee account', claim.payee.account?.span)
  push('ifsc', 'IFSC', claim.payee.ifsc?.span)
  push('vpa', 'UPI ID', claim.payee.vpa?.span)
  push('claimed_owner', 'Who the account is said to belong to', claim.payee.claimed_owner_span)
  push('summons_no', 'Summons number', claim.document_ids.summons_no?.span)
  push('passcode', 'Passcode', claim.document_ids.passcode?.span)
  push('issue_date', 'Issue date', claim.document_ids.issue_date?.span)
  push('case_no', 'Case number', claim.document_ids.case_no?.span)
  claim.amounts.forEach((a, i) => push(`amount:${i}`, 'Amount', a.span))
  Object.entries(claim.pressure_cues).forEach(([cue, span]) => push(`cue:${cue}`, `Pressure: ${CUE_WORD[cue] ?? cue}`, span))
  push('caller_number', 'Caller number', claim.caller_number?.span)
  claim.urls.forEach((u, i) => push(`url:${i}`, 'Link', u.span))
  // Resolve overlaps: keep the earlier, longer span.
  out.sort((a, b) => a.start - b.start || b.end - a.end)
  const kept: SpanRef[] = []
  let cursor = -1
  for (const s of out) {
    if (s.start < cursor) continue
    kept.push(s)
    cursor = s.end
  }
  return kept
}

export const CUE_WORD: Record<string, string> = {
  arrest_threat: 'threat of arrest',
  secrecy: 'demand for secrecy',
  urgency: 'urgency',
  isolation: 'keeping you on the call',
  guaranteed_returns: 'guaranteed returns',
}

export const FAMILY_WORD: Record<Family, string> = {
  F1: 'Issuer rule',
  F2: 'Bank record',
  F3: 'Forensics',
  F4: 'Campaign memory',
  F5: 'Context',
}

export const SEVERITY_WORD: Record<Severity, string> = {
  hard: 'Hard rule',
  soft: 'Soft signal',
  info: 'For information',
  match: 'Match',
  abstain: 'Abstained',
}

export const EVIDENCE_WORD: Record<string, string> = {
  claim: 'the message itself',
  'issuer:ed_portal': 'ED verify-summon',
  'registry:suspect': 'I4C suspect registry',
  'bank:outbound_log': "the bank's outbound log",
  'bank:name_lookup': 'beneficiary name lookup',
  'bank:ledger': "the customer's ledger",
  'bank:signature': "the bank's content signature",
  'bank:paused_payment': "the paused payment's receiver",
  'web:registry': "the domain registry's record",
  'media:audio': 'the audio file',
  'media:document': 'the document file',
  'media:image': 'the image file',
  'media:video': 'the video file',
  'memory:template': 'campaign memory',
  flag: "the bank's flag",
}

export function evidenceWord(key: string): string {
  return EVIDENCE_WORD[key] ?? key
}

// Evidence keys that are mocked lookups in the prototype (the console labels them).
export const MOCKED_EVIDENCE = new Set(['issuer:ed_portal', 'registry:suspect', 'bank:outbound_log', 'bank:name_lookup', 'bank:ledger', 'bank:signature', 'bank:paused_payment'])

export const OUTCOME_WORD: Record<Outcome, { en: string; hi: string }> = {
  RED: { en: 'RED', hi: 'लाल' },
  AMBER: { en: 'AMBER', hi: 'पीला' },
  GREY: { en: 'GREY', hi: 'अनिश्चित' },
  MATCHES: { en: 'MATCHES', hi: 'मेल खाता है' },
}

// Anchors a signal points at. "span:<key>" is a highlighted phrase; "meta:<name>" is a row under the message.
const SPAN_TARGETS: Record<string, string[]> = {
  'R-AGENCY-PAY': ['issuer', 'instruction'],
  // The open-set half of R-AGENCY-PAY, split off on 19 Oct so its sentence could say what was read rather than
  // assert what the sender claims to be. It points at the same two spans; without this entry `targetsFor` falls
  // back to meta:text and the leader line aims at the whole message instead of the name and the demand.
  'R-STATE-NAME-PAY': ['issuer', 'instruction'],
  'R-COURT-PAY': ['issuer', 'instruction'],
  'R-ED-SUMMONS-NOTFOUND': ['summons_no', 'passcode'],
  'R-ED-NO-PASSCODE': ['summons_no'],
  'R-ED-WINDOW': ['summons_no', 'issue_date'],
  'R-ED-FOUND': ['summons_no', 'passcode'],
  'R-ED-CHANNEL': ['channel', 'issuer'],
  'R-RBI-INV': ['issuer', 'instruction'],
  'R-SEBI-VALID': ['vpa'],
  'R-CALLER-1600': ['caller_number'],
  'R-DOMAIN-BANKIN': ['url:0'],
  // the challan and the route it sends the payment along (only the ones present get a leader line)
  'R-CHALLAN-OFFICIAL': ['instruction', 'url:0', 'account', 'vpa', 'caller_number'],
  'R-DOMAIN-GOVIN': ['url:0'],
  'R-WEBSITE-NEW': ['url:0'],
  'R-SUSPECT': ['account', 'vpa', 'caller_number'],
  'R-BANK-NEVER-MOVE-FD': ['issuer', 'instruction'],
  'R-BANK-SELF': ['issuer'],
  'R-PAYEE-NAME': ['account', 'claimed_owner'],
  'R-PAYEE-NOT-SENDER': ['account', 'issuer'],
  'R-LEDGER': ['amount:0', 'instruction'],
  'R-PRESSURE-CUES': ['cue:*'],
}

const META_TARGETS: Record<string, string> = {
  'R-BANK-RM-PHONE': 'sender',
  'R-OWN-SIGNATURE': 'signature',
  'R-AUDIO-SYNTH': 'media',
  'R-VIDEO-SYNTH': 'media',
  'R-DOC-TAMPER': 'media',
  'R-DOC-AI': 'media',
  'R-CAMPAIGN-MATCH': 'text',
  'R-BANK-FLAG': 'flag',
  // the receiver comes from the bank's own transfer record, which the flag row shows, never from the message
  'R-RECEIVER-NAME': 'flag',
}

export function targetsFor(signal: Signal, spans: SpanRef[]): string[] {
  const keys = SPAN_TARGETS[signal.rule_id] ?? []
  const have = new Set(spans.map((s) => s.key))
  const hits: string[] = []
  for (const k of keys) {
    if (k === 'cue:*') spans.filter((s) => s.key.startsWith('cue:')).forEach((s) => hits.push(`span:${s.key}`))
    else if (have.has(k)) hits.push(`span:${k}`)
  }
  if (hits.length) return hits
  const meta = META_TARGETS[signal.rule_id]
  if (meta) return [`meta:${meta}`]
  if (signal.evidence_key.startsWith('media:')) return ['meta:media']
  return ['meta:text']
}

export function sortSignals(view: CaseView): { features: Signal[]; noted: Signal[] } {
  const v = view.case.verdict
  if (!v) return { features: [], noted: [] }
  const rank = (s: Signal) => {
    if (s.rule_id === v.anchor_rule) return 0
    if (s.rule_id === v.second_family) return 1
    if (s.severity === 'match') return 2
    if (s.severity === 'hard') return 3
    if (s.severity === 'soft' && s.escalate_alone) return 4
    if (s.severity === 'soft') return 5
    return 9
  }
  const shown = v.signals.filter((s) => ['hard', 'soft', 'match'].includes(s.severity))
  const rest = v.signals.filter((s) => !['hard', 'soft', 'match'].includes(s.severity))
  shown.sort((a, b) => rank(a) - rank(b))
  return { features: shown, noted: rest }
}

export function restsOn(view: CaseView): { anchor: Signal | null; second: Signal | null } {
  const v = view.case.verdict
  if (!v) return { anchor: null, second: null }
  const find = (id: string | null) => (id ? (v.signals.find((s) => s.rule_id === id) ?? null) : null)
  return { anchor: find(v.anchor_rule), second: find(v.second_family) }
}
