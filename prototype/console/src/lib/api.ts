// Typed client for the Satyapan FastAPI service. Shapes mirror satyapan/models.py and api.py.

export type Outcome = 'RED' | 'AMBER' | 'GREY' | 'MATCHES'
export type Family = 'F1' | 'F2' | 'F3' | 'F4' | 'F5'
export type Severity = 'hard' | 'soft' | 'info' | 'match' | 'abstain'

export interface Span { text: string; start: number; end: number }
export interface Grounded { value: string; span: Span }

export interface Payee {
  account: Grounded | null
  ifsc: Grounded | null
  vpa: Grounded | null
  claimed_owner: string
  claimed_owner_span: Span | null
}

export interface DocumentIds {
  summons_no: Grounded | null
  passcode: Grounded | null
  issue_date: Grounded | null
  case_no: Grounded | null
}

export interface Claim {
  source: string
  text: string
  claimed_issuer: string
  issuer_span: Span | null
  channel: string
  channel_span: Span | null
  instruction: string
  instruction_span: Span | null
  payee: Payee
  document_ids: DocumentIds
  mentions_summons: boolean
  amounts: Grounded[]
  pressure_cues: Record<string, Span>
  caller_number: Grounded | null
  urls: Grounded[]
  language_hint: string
  extractor: string
  // the offline helper reader (Llama 3.2 3B, run locally) names the fields it filled; each is quoted from the message
  read_by_llm?: string[]
  digital_arrest_span?: Span | null
}

export interface Signal {
  rule_id: string
  family: Family
  severity: Severity
  evidence_key: string
  reason_en: string
  reason_hi: string
  citation: string
  citation_url: string
  citation_verified: boolean
  escalate_alone: boolean
  rule_version: string
  detail: Record<string, unknown>
}

export interface Verdict {
  outcome: Outcome
  headline_en: string
  headline_hi: string
  anchor_rule: string | null
  second_family: string | null
  no_money_cap?: boolean // two families agreed but no money demand was read, so AMBER and not RED
  explanation: string
  policy_version: string
  signals: Signal[]
  // set when media was attached and the detector could judge it: instruction and deepfake count half each
  scores?: {
    instruction_pct: number
    deepfake_pct: number
    combined_pct: number
    red_line_pct: number
    amber_line_pct: number
    // the rehearsal scenarios script their media result; the band says so next to the number
    deepfake_simulated?: boolean
  } | null
}

export interface Flag {
  reason: string
  amount_inr: number
  customer_ref: string
  payee_account?: string | null
  payee_ifsc?: string | null
  payee_vpa?: string | null
  channel?: string
}

export interface Consent {
  check: boolean
  report: boolean
  memory: boolean
  recorded_at: string | null
  read_aloud_lang: string
}

export interface MediaRef {
  filename: string
  kind: string
  sha256: string
  bytes: number
  perceptual_hash: string | null
  derived_text: string | null
  derived_text_engine: string | null
}

export interface Decision { at: string; actor: string; action: string; note: string }

export interface Case {
  id: string
  created_at: string
  flag: Flag
  consent: Consent
  media: MediaRef[]
  claim: Claim | null
  verdict: Verdict | null
  decisions: Decision[]
  status: string
}

export interface Reason { text: string; cite: string; rule_id: string }
export interface Card {
  lang: string
  outcome: Outcome
  headline: string
  stop_line: string
  reasons: Reason[]
  do_now: string
  coaching: string | null
  read_aloud: string
}

export interface CaseView {
  case: Case
  card?: { hi: Card; en: Card }
  review_triggers?: string[]
  inputs: {
    sender_number: string | null
    bank_signature_present: boolean
    forensics_simulated: boolean
    mode: 'claim-only' | 'media'
    // True on a RED case, and on one that was RED before an officer struck a field (the engine's own rule).
    release_needs_co_sign?: boolean
  }
  scenario?: {
    id: string
    title: string
    text: string | null
    picklist: Record<string, unknown> | null
    then_forensics: Record<string, unknown> | null
    expect: Outcome | null
  }
}

export interface Scenario {
  id: string
  title: string
  lang: string
  flag: Flag
  expect: Outcome | null
  mode: 'claim-only' | 'media'
  media_kind: string
  has_rehearsal_forensics: boolean
  has_reencode_step: boolean
}

// The face and voice checks' measured accuracy (calibration/accuracy.json, written by scripts/accuracy_card.py)
export interface AccuracyCounts {
  n: number
  judged: number
  flagged: number
  unsure: number
  no_signs: number
  declined: number
  sources: string[]
  false_alarm_heldout_pct?: number
}
export interface Accuracy {
  _note: string
  made: string
  models: { face?: string; voice?: string }
  cells: { check: 'face' | 'voice'; cell: string; t_fpr5: number; t_fpr20: number; genuine: AccuracyCounts; fake: AccuracyCounts }[]
  failure_cases: { check: string; text: string }[]
}

export interface Label { name: string; production_source: string; owner: string; route: string; mock: boolean }

export interface RuleMeta {
  id: string
  family: Family
  severity: Severity
  title: string
  citation: string
  citation_url: string
  verified: boolean
  checked: string
}

export interface SessionTiming {
  count: number
  session_p50_verdict_ms: number | null
  scope: string
}

export interface Meta {
  version: string
  policy_version: string
  bank_name: string
  rulebook: { version: string; sha256: string; rules: RuleMeta[] }
  adapters: Label[]
  forensics: {
    audio: Label
    document: Label
    // the local face and voice service, when the engine runs with SATYAPAN_FORENSICS_URL
    service?:
      | (Label & {
          health?: {
            ok?: boolean
            video?: { model?: string; calibrated_cells?: string[] }
            audio?: { installed?: boolean; loaded?: boolean; model?: string; error?: string | null }
          } | null
        })
      | null
  }
  signer: Label
  session_timing: SessionTiming
}

export interface EvidencePack {
  format: string
  signed_at: string
  manifest: Record<string, unknown>
  manifest_sha256: string
  signature: { alg: string; public_key: string; value: string; [k: string]: unknown }
}

export interface MemoryEntry {
  id: string
  status: string
  [k: string]: unknown
}

export interface CaseSummary { id: string; created_at: string; status: string; flag: Flag; outcome: Outcome | null; about: string | null }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// A dead wire is not a refusal. With the network cut, the officer used to read "Refused: Failed to fetch" in the
// action pane — a raw browser string, carrying the same word as a genuine policy refusal, and silent on the only
// question that matters, whether the decision was recorded. It was not: the request never reached the service, so
// nothing was written, and the officer can press the button again.
//
// The same class is thrown by the read paths, where nothing was being recorded in the first place, so the
// consequence clause belongs to the path and `ui/trouble.tsx` writes it: "Not recorded: ..." for a decision,
// "Not loaded: ..." for a screen. What stays here is the one fact both share — the service did not answer.
//
// `name` is blank on purpose. The message is officer-facing prose, and `String(err)` on an Error prefixes it with
// the name, so any caller that stringifies this one used to put "Error: " in front of a sentence meant for a
// branch counter. Nothing branches on the name; `instanceof OfflineError` is the test everywhere.
export class OfflineError extends Error {
  constructor() {
    super('The Satyapan service did not answer, so nothing on this screen could be loaded. Check that it is running, then try again.')
    this.name = ''
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new OfflineError()
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    } catch {
      /* no JSON body */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

// `satyapan evaluate`'s own output (data/eval/results.json), shown as it is.
export interface EvalTally { n: number; RED: number; AMBER: number; GREY: number; MATCHES: number }
export interface EvalRow { id: string; source: string; label: 'scam' | 'genuine'; in_scope: boolean | null; category: string; lang: string; outcome: Outcome; fired: string[] }
export interface Evaluation {
  _note: string
  made: string
  commit: string
  environment: { audio_detector: string; meaning_model: boolean; website_registry: string; rulebook: string }
  summary: {
    in_scope_scams: EvalTally & { flagged_pct: number; stopped_pct: number; missed_pct: number }
    genuine: EvalTally & { false_stop_pct: number; asked_to_verify_pct: number; left_alone_pct: number }
    out_of_scope_scams: EvalTally & { flagged_pct: number }
    by_category: Array<EvalTally & { label: string; category: string }>
    missed: string[]
    false_stops: string[]
    asked_to_verify: string[]
    total: number
  }
  excluded: Array<{ id: string; why: string }>
  rows: EvalRow[]
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  meta: () => call<Meta>('/meta'),
  scenarios: () => call<Scenario[]>('/scenarios'),
  runScenario: (id: string) => call<CaseView>(`/scenarios/${id}/run`, { method: 'POST' }),
  reencode: (id: string, caseId: string) => call<CaseView>(`/scenarios/${id}/reencode`, json({ case_id: caseId })),

  cases: () => call<CaseSummary[]>('/cases'),
  openCase: (flag: Flag) => call<CaseView>('/cases', json({ flag })),
  getCase: (id: string) => call<CaseView>(`/cases/${id}`),
  consent: (id: string, c: { check: boolean; report: boolean; memory: boolean; lang: string }) =>
    call<CaseView>(`/cases/${id}/consent`, json(c)),
  addText: (
    id: string,
    body: { text: string; source?: string; sender_number?: string | null; signed?: boolean; kind?: string; filename?: string },
  ) => call<CaseView>(`/cases/${id}/text`, json(body)),
  addMedia: (id: string, file: File, opts: { derived_text?: string; sender_number?: string; language?: string; channel?: 'live-replay' } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    if (opts.derived_text) fd.append('derived_text', opts.derived_text)
    if (opts.sender_number) fd.append('sender_number', opts.sender_number)
    fd.append('language', opts.language ?? 'hi')
    if (opts.channel) fd.append('channel', opts.channel)
    return call<CaseView>(`/cases/${id}/media`, { method: 'POST', body: fd })
  },
  addPicklist: (id: string, body: Record<string, unknown>) => call<CaseView>(`/cases/${id}/picklist`, json(body)),
  run: (id: string) => call<CaseView>(`/cases/${id}/run`, { method: 'POST' }),
  decide: (id: string, body: { actor: string; action: string; note?: string; co_signer?: string | null }) =>
    call<CaseView>(`/cases/${id}/decide`, json(body)),
  strike: (id: string, field: string, actor: string) => call<CaseView>(`/cases/${id}/strike`, json({ field, actor })),
  simulateForensics: (id: string, result: Record<string, unknown>) =>
    call<CaseView>(`/cases/${id}/forensics/simulate`, json(result)),
  evidence: (id: string) => call<EvidencePack>(`/cases/${id}/evidence`),
  evidenceDownloadUrl: (id: string) => `/api/cases/${id}/evidence?download=true`,
  verify: (pack: unknown) => call<{ ok: boolean; reason: string }>('/evidence/verify', json(pack)),

  demoReset: () => call<{ ok: boolean; cases_cleared: number }>('/demo/reset', { method: 'POST' }),

  evaluation: () => call<Evaluation>('/evaluation'),
  accuracy: () => call<Accuracy>('/accuracy'),
  memory: () => call<{ entries: MemoryEntry[] }>('/memory'),
  propose: (caseId: string, analyst: string, note = '') =>
    call<MemoryEntry>('/memory/propose', json({ case_id: caseId, analyst, note })),
  approve: (entryId: string, analyst: string) => call<MemoryEntry>(`/memory/${entryId}/approve`, json({ analyst })),
}
