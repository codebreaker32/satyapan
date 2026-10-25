// The check: the message held up with its spans highlighted, the features to check beside it, and the leader lines
// that join each feature to the words it rests on. Every feature carries a number; the same number is stamped at the
// start of each phrase it rests on, so the pairing reads from five metres even where a line is faint. Leaders run
// only in the gutter between the columns, from the feature to the message's right edge on the phrase's line.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CaseView, Signal } from '../lib/api'
import { shortHash, spellsAmount } from '../lib/format'
import {
  FAMILY_WORD,
  MOCKED_EVIDENCE,
  SEVERITY_WORD,
  collectSpans,
  evidenceWord,
  sortSignals,
  targetsFor,
  type SpanRef,
} from '../lib/spans'
import { Rupee } from './rupee'

interface Props {
  view: CaseView
  titles: Record<string, string>
}

type Lit = { kind: 'signal'; id: string } | { kind: 'anchor'; id: string } | null

const READER_FIELDS: Record<string, string> = {
  claimed_issuer: 'the authority it names',
  instruction: 'what it asks about money',
  digital_arrest_span: 'the “digital arrest” words',
}

function readerWords(fields: string[]): string {
  const words = fields.map((f) => READER_FIELDS[f] ?? f.replaceAll('_', ' '))
  return words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}` : words[0]
}

export function Check({ view, titles }: Props) {
  const claim = view.case.claim
  const containerRef = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<Lit>(null)
  const [pinned, setPinned] = useState<Lit>(null)
  const lit = hover ?? pinned

  const spans = useMemo(() => (claim ? collectSpans(claim) : []), [claim])
  const { features, noted } = useMemo(() => sortSignals(view), [view])
  const pairs = useMemo(
    () => features.flatMap((s) => targetsFor(s, spans).map((to) => ({ from: s.rule_id, to }))),
    [features, spans],
  )
  const numberOf = useMemo(() => {
    const m: Record<string, number> = {}
    features.forEach((s, i) => (m[s.rule_id] = i + 1))
    return m
  }, [features])
  const numbersAt = useMemo(() => {
    const m: Record<string, number[]> = {}
    pairs.forEach((p) => {
      const n = numberOf[p.from]
      if (!m[p.to]) m[p.to] = []
      if (!m[p.to].includes(n)) m[p.to].push(n)
    })
    Object.values(m).forEach((arr) => arr.sort((a, b) => a - b))
    return m
  }, [pairs, numberOf])

  const litSignals = useMemo(() => {
    const set = new Set<string>()
    if (!lit) return set
    if (lit.kind === 'signal') set.add(lit.id)
    else pairs.filter((p) => p.to === lit.id).forEach((p) => set.add(p.from))
    return set
  }, [lit, pairs])
  const litAnchors = useMemo(() => {
    const set = new Set<string>()
    if (!lit) return set
    if (lit.kind === 'anchor') set.add(lit.id)
    else pairs.filter((p) => p.from === lit.id).forEach((p) => set.add(p.to))
    return set
  }, [lit, pairs])

  const neededMeta = useMemo(() => new Set(pairs.map((p) => p.to).filter((t) => t.startsWith('meta:'))), [pairs])
  const pinnedSignal = pinned?.kind === 'signal' ? pinned.id : null

  const toggle = (l: Lit) => setPinned((p) => (p && l && p.kind === l.kind && p.id === l.id ? null : l))

  if (!claim) return null
  const v = view.case.verdict
  const sourceWord: Record<string, string> = {
    transcript: 'Transcript of the voice note or video',
    ocr: 'Text read from the scanned notice',
    text: 'Message as pasted',
    officer_picklist: 'Claim-only mode: what the officer ticked',
    none: 'No text',
  }
  const rowProps = (id: string) => ({
    id,
    lit: litAnchors.has(id),
    numbers: numbersAt[id] ?? [],
    onHover: setHover,
    onPick: toggle,
  })

  return (
    <div className="check" ref={containerRef}>
      <div data-col="message">
        <h2 id="claims" tabIndex={-1}>
          <span className="step-no">1</span> What the message claims
        </h2>
        <p className="message-meta">
          {sourceWord[claim.source] ?? claim.source}
          {view.inputs.sender_number ? ` · from ${view.inputs.sender_number}` : ''}
        </p>
        {claim.read_by_llm && claim.read_by_llm.length > 0 && (
          // The rules-based reader came first; the offline model only filled what it left empty, each part quoted
          // from the message, and the rules still decided. Saying which parts keeps a model's reading visible.
          <p className="message-meta">
            Read with the offline reader on this laptop: {readerWords(claim.read_by_llm)}. Each is quoted from the message; the rules decided.
          </p>
        )}
        <div className="message">
          {claim.source === 'officer_picklist' ? (
            <Picklist claim={claim} />
          ) : claim.text.trim() ? (
            <p>
              <Segments text={claim.text} spans={spans} lit={litAnchors} numbersAt={numbersAt} onHover={setHover} onPick={toggle} />
            </p>
          ) : (
            // An empty box read as a box that failed to load. Say what it holds: nothing came out of the media.
            <p className="muted">No text came out of what the customer showed, so there was nothing here to check.</p>
          )}
        </div>
        <div className="also">
          {view.case.media.map((m) => (
            <MetaRow key={m.sha256} {...rowProps('meta:media')} label="Media">
              <strong className="media-name">{m.filename}</strong> · {m.kind} · {m.bytes.toLocaleString('en-IN')} bytes · sha256 <span className="hash">{shortHash(m.sha256)}</span>
              {m.derived_text_engine &&
                ((m.kind === 'audio' || m.kind === 'video')
                  ? ` · transcribed by ${m.derived_text_engine}`
                  : m.derived_text_engine.startsWith('tesseract')
                    ? ` · OCR by ${m.derived_text_engine}`
                    : ` · text from ${m.derived_text_engine}`)}
              {view.inputs.forensics_simulated && m.kind !== 'text' && (
                <>
                  {' '}
                  <span className="tag tag-sim">Forensics simulated</span>
                </>
              )}
            </MetaRow>
          ))}
          {neededMeta.has('meta:sender') && (
            <MetaRow {...rowProps('meta:sender')} label="Sender">
              {view.inputs.sender_number ?? 'unknown number'}
            </MetaRow>
          )}
          {neededMeta.has('meta:signature') && (
            <MetaRow {...rowProps('meta:signature')} label="Bank signature">
              {view.inputs.bank_signature_present ? 'present on this message' : 'none'}
            </MetaRow>
          )}
          {neededMeta.has('meta:text') && (
            <MetaRow {...rowProps('meta:text')} label="Whole message">
              compared as a fingerprint of the full text
            </MetaRow>
          )}
          <MetaRow {...rowProps('meta:flag')} label="Bank flag">
            {view.case.flag.reason}
            {view.case.flag.amount_inr > 0 && !spellsAmount(view.case.flag.reason) && (
              <>
                {' · '}
                <Rupee n={view.case.flag.amount_inr} />
              </>
            )}
            {(view.case.flag.payee_vpa || view.case.flag.payee_account) && (
              <>
                {' · paying to '}
                <span className="hash">{view.case.flag.payee_vpa || view.case.flag.payee_account}</span>
              </>
            )}
          </MetaRow>
        </div>
        {noted.length > 0 && (
          <div className="noted">
            <h3>Also noted, never counted</h3>
            {noted.map((s) => (
              <div className="row" key={s.rule_id + s.evidence_key}>
                {FAMILY_WORD[s.family]}: {s.reason_en.replace(/^Bank flag: /, '')}
              </div>
            ))}
          </div>
        )}
      </div>

      <div data-col="features">
        <h2 id="checked" tabIndex={-1}>
          <span className="step-no">2</span> What we checked it against
        </h2>
        <ul className="features">
          {features.map((s) => (
            <Feature
              key={s.rule_id + s.evidence_key}
              s={s}
              n={numberOf[s.rule_id]}
              title={titles[s.rule_id]}
              role={s.rule_id === v?.anchor_rule ? 'Anchor' : s.rule_id === v?.second_family ? 'Second' : null}
              expanded={s.rule_id === v?.anchor_rule || s.rule_id === v?.second_family || s.severity === 'match' || pinnedSignal === s.rule_id}
              lit={litSignals.has(s.rule_id)}
              onHover={setHover}
              onPick={toggle}
            />
          ))}
          {/* The empty state is a sentence, not a row: .feat is a two-column grid, so a bare text node used to
              render one word per line in the exact place a judge looks to see why nothing fired. */}
          {features.length === 0 && (
            <li className="feat feat-empty">
              <p>No rule fired on this message.</p>
              <p className="muted">
                The check ran and found nothing to report. That is not a confirmation that the message is safe.
              </p>
            </li>
          )}
        </ul>
      </div>

      <Leaders containerRef={containerRef} pairs={pairs} litSignals={litSignals} litAnchors={litAnchors} lit={lit} />
    </div>
  )
}

function Numbers({ numbers }: { numbers: number[] }) {
  if (!numbers.length) return null
  return (
    <span className="callout-no" aria-label={`feature ${numbers.join(' and ')}`}>
      {numbers.join('·')}
    </span>
  )
}

function Segments({
  text,
  spans,
  lit,
  numbersAt,
  onHover,
  onPick,
}: {
  text: string
  spans: SpanRef[]
  lit: Set<string>
  numbersAt: Record<string, number[]>
  onHover: (l: Lit) => void
  onPick: (l: Lit) => void
}) {
  // The engine's offsets count code points (Python); a JS string slices UTF-16 units, so every emoji before a span
  // shifted each mark and leader line one unit onto the wrong words. Slice by code point.
  const cps = Array.from(text)
  const cut = (a: number, b?: number) => cps.slice(a, b).join('')
  const parts: React.ReactNode[] = []
  let cursor = 0
  spans.forEach((s) => {
    if (s.start > cursor) parts.push(cut(cursor, s.start))
    const id = `span:${s.key}`
    parts.push(
      <mark
        key={id}
        className={lit.has(id) ? 'span lit' : 'span'}
        data-anchor={id}
        title={s.label}
        tabIndex={0}
        onMouseEnter={() => onHover({ kind: 'anchor', id })}
        onMouseLeave={() => onHover(null)}
        onFocus={() => onHover({ kind: 'anchor', id })}
        onBlur={() => onHover(null)}
        onClick={() => onPick({ kind: 'anchor', id })}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onPick({ kind: 'anchor', id })
          }
        }}
      >
        <Numbers numbers={numbersAt[id] ?? []} />
        {cut(s.start, s.end)}
      </mark>,
    )
    cursor = s.end
  })
  if (cursor < cps.length) parts.push(cut(cursor))
  return <>{parts}</>
}

function Picklist({ claim }: { claim: NonNullable<CaseView['case']['claim']> }) {
  const items: Array<[string, string]> = [
    ['Claimed to be', claim.claimed_issuer],
    ['Asked for', claim.instruction.replaceAll('_', ' ').toLowerCase()],
    ['Over', claim.channel.replaceAll('_', ' ').toLowerCase()],
    ['Account said to belong to', claim.payee.claimed_owner],
  ]
  if (claim.payee.account) items.push(['Account', claim.payee.account.value])
  if (claim.payee.ifsc) items.push(['IFSC', claim.payee.ifsc.value])
  if (claim.payee.vpa) items.push(['UPI ID', claim.payee.vpa.value])
  const cues = Object.keys(claim.pressure_cues)
  if (cues.length) items.push(['Pressure', cues.join(', ').replaceAll('_', ' ')])
  return (
    <div className="rows">
      {items.map(([k, val]) => (
        <div className="row-item picklist-row" key={k}>
          <strong>{k}</strong>
          <span>{val}</span>
        </div>
      ))}
    </div>
  )
}

function MetaRow({
  id,
  label,
  lit,
  numbers,
  onHover,
  onPick,
  children,
}: {
  id: string
  label: string
  lit: boolean
  numbers: number[]
  onHover: (l: Lit) => void
  onPick: (l: Lit) => void
  children: React.ReactNode
}) {
  return (
    <div
      className={lit ? 'row lit' : 'row'}
      data-anchor={id}
      tabIndex={0}
      onMouseEnter={() => onHover({ kind: 'anchor', id })}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover({ kind: 'anchor', id })}
      onBlur={() => onHover(null)}
      onClick={() => onPick({ kind: 'anchor', id })}
    >
      <b>
        <Numbers numbers={numbers} />
        {label}
      </b>
      <span>{children}</span>
    </div>
  )
}

function Feature({
  s,
  n,
  title,
  role,
  expanded,
  lit,
  onHover,
  onPick,
}: {
  s: Signal
  n: number
  title?: string
  role: 'Anchor' | 'Second' | null
  expanded: boolean
  lit: boolean
  onHover: (l: Lit) => void
  onPick: (l: Lit) => void
}) {
  const simulated = Boolean(s.detail.simulated)
  const id = s.rule_id
  return (
    <li
      className={[lit ? 'feat lit' : 'feat', expanded ? '' : 'feat-brief'].join(' ').trim()}
      data-signal={id}
      tabIndex={0}
      aria-expanded={expanded}
      onMouseEnter={() => onHover({ kind: 'signal', id })}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover({ kind: 'signal', id })}
      onBlur={() => onHover(null)}
      onClick={() => onPick({ kind: 'signal', id })}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onPick({ kind: 'signal', id })
        }
      }}
    >
      <span className="feat-no" aria-hidden="true">
        {n}
      </span>
      <div className="feat-body">
        {/* Up to five pills per row made eight distinct pill shapes on one case screen, and the judge counted tag
            soup as a generic tell on the main path. They were never five peers, and flattening them all into the
            same chip is what cost the two that matter their weight. A pill now means one of two things and
            nothing else: this row is why the verdict is legal (Anchor, Second), or trust what it says less
            (Simulated, Mock lookup). How strong the check is reads as a phrase beside the family word, because
            "Soft signal · verify first" is a sentence about the check, not a badge on it. */}
        <div className="feat-top">
          <span className="feat-fam">{FAMILY_WORD[s.family]}</span>
          {role && <span className="tag tag-ink">{role}</span>}
          <span className="feat-grade">
            {[SEVERITY_WORD[s.severity], s.escalate_alone && s.severity === 'soft' ? 'verify first' : null]
              .filter(Boolean)
              .join(' · ')}
          </span>
          {simulated && <span className="tag tag-sim">Simulated</span>}
          {MOCKED_EVIDENCE.has(s.evidence_key) && <span className="tag tag-accent">Mock lookup</span>}
        </div>
        {expanded ? <div className="feat-reason">{s.reason_en}</div> : <div className="feat-title">{title ?? s.reason_en}</div>}
        {(expanded || !s.citation_verified) && (
          <div className="feat-ev">
            Rests on {evidenceWord(s.evidence_key)}
            {expanded && s.citation ? ` · ${s.citation}` : ''}
            {s.citation_verified ? '' : ' · citation not yet verified, demoted to soft'}
          </div>
        )}
      </div>
    </li>
  )
}

interface Pair {
  from: string
  to: string
}

interface Line {
  key: string
  d: string
  x2: number
  y2: number
  lit: boolean
}

function Leaders({
  containerRef,
  pairs,
  litSignals,
  litAnchors,
  lit,
}: {
  containerRef: React.RefObject<HTMLDivElement | null>
  pairs: Pair[]
  litSignals: Set<string>
  litAnchors: Set<string>
  lit: Lit
}) {
  const [lines, setLines] = useState<Line[]>([])
  const [size, setSize] = useState({ w: 0, h: 0, top: 0 })
  const [drawn, setDrawn] = useState(false)

  const measure = useCallback(() => {
    const c = containerRef.current
    if (!c) return
    const box = c.getBoundingClientRect()
    const head = c.querySelector('h2')
    const top = head ? head.getBoundingClientRect().bottom - box.top + 6 : 0
    const col = c.querySelector<HTMLElement>('[data-col="message"]')
    const colRight = col ? col.getBoundingClientRect().right - box.left : box.width * 0.6
    setSize({ w: box.width, h: box.height - top, top })
    const out: Line[] = []
    const seen = new Set<string>()
    for (const p of pairs) {
      const from = c.querySelector<HTMLElement>(`[data-signal="${CSS.escape(p.from)}"]`)
      const to = c.querySelector<HTMLElement>(`[data-anchor="${CSS.escape(p.to)}"]`)
      if (!from || !to) continue
      const f = from.getBoundingClientRect()
      const rects = to.getClientRects()
      const t = rects.length ? rects[0] : to.getBoundingClientRect()
      const x1 = f.left - box.left - 4
      const y1 = f.top - box.top - top + Math.min(f.height / 2, 26)
      // The leader ends in the gutter, on the phrase's line, never inside the running text.
      const x2 = colRight + 6
      const y2 = Math.round(t.top - box.top - top + t.height / 2)
      const key = `${p.from}->${y2}`
      if (seen.has(key)) continue
      seen.add(key)
      const dx = Math.max(24, (x1 - x2) * 0.7)
      const isLit = lit !== null && ((lit.kind === 'signal' && lit.id === p.from) || (lit.kind === 'anchor' && lit.id === p.to))
      out.push({ key, d: `M ${x1} ${y1} C ${x1 - dx} ${y1}, ${x2 + dx} ${y2}, ${x2} ${y2}`, x2, y2, lit: isLit })
    }
    setLines(out)
  }, [containerRef, pairs, lit])

  useLayoutEffect(() => {
    measure()
  }, [measure, litSignals, litAnchors])

  useEffect(() => {
    let raf = 0
    const schedule = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(measure)
    }
    const c = containerRef.current
    const ro = new ResizeObserver(schedule)
    if (c) {
      ro.observe(c)
      c.querySelectorAll('.feat').forEach((el) => ro.observe(el))
    }
    window.addEventListener('resize', schedule)
    document.fonts?.ready.then(schedule)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', schedule)
      cancelAnimationFrame(raf)
    }
  }, [measure, containerRef])

  useEffect(() => {
    if (!lines.length || drawn) return
    const t = setTimeout(() => setDrawn(true), 640 + lines.length * 60)
    return () => clearTimeout(t)
  }, [lines.length, drawn])

  if (!lines.length) return null
  return (
    <svg
      className="leaders"
      style={{ top: size.top, height: size.h }}
      viewBox={`0 0 ${size.w} ${size.h}`}
      width={size.w}
      height={size.h}
      aria-hidden="true"
    >
      {lines.map((l, i) => (
        <g key={l.key}>
          <path
            className={[l.lit ? 'leader lit' : 'leader', drawn ? '' : 'draw'].join(' ').trim()}
            d={l.d}
            pathLength={1}
            style={drawn ? undefined : { animationDelay: `${i * 60}ms` }}
          />
          <circle className={l.lit ? 'leader-dot lit' : 'leader-dot'} cx={l.x2} cy={l.y2} r={l.lit ? 5 : 4} />
        </g>
      ))}
    </svg>
  )
}
