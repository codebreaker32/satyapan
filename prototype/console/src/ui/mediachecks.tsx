import { useEffect, useState } from 'react'
import { api, type Accuracy, type CaseView, type Signal } from '../lib/api'
import { CELL_WORDS, modelWords, sameDecimals } from '../lib/cells'
import { sortSignals } from '../lib/spans'
import { Trouble } from './trouble'

// What each face, voice or document check found, one line per check, with the numbers that make it checkable: the
// score against the line for that kind of input, how many genuine clips set that line, and how often genuine clips
// that did not set it were flagged (calibration/accuracy.json, through /api/accuracy). The first question about a
// detector is "how often is it wrong about real people"; the answer belongs beside the result, not only on the
// Evaluation page. Officer-only: the customer card never shows a score.

let accuracyOnce: Promise<Accuracy> | null = null

// One request per session while it succeeds. A failed read is forgotten so the next mount, or Retry, asks again,
// and the screen says the figures were not read rather than printing the results without them (DESIGN.md's
// three prefixes: a dead wire on a read is "Not loaded").
function useAccuracy(): { acc: Accuracy | null; error: unknown; retry: () => void } {
  const [acc, setAcc] = useState<Accuracy | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    accuracyOnce ??= api.accuracy()
    let live = true
    accuracyOnce.then(
      (a) => live && (setAcc(a), setError(null)),
      (e) => {
        accuracyOnce = null
        if (live) setError(e ?? new Error('not loaded'))
      },
    )
    return () => {
      live = false
    }
  }, [attempt])
  return { acc, error, retry: () => setAttempt((n) => n + 1) }
}

const CHECK_WORDS: Record<string, string> = {
  'media:video': 'Face check',
  'media:audio': 'Voice check',
  'media:document': 'Document check',
}

interface Detail {
  status?: string
  band?: string
  score?: number | null
  model?: string
  cell?: string
  simulated?: boolean
  deepfake_pct?: number | null
}

function fileFor(s: Signal, view: CaseView): string | undefined {
  const kinds = s.evidence_key === 'media:video' ? ['video'] : s.evidence_key === 'media:audio' ? ['audio', 'video'] : ['image', 'pdf']
  const files = view.case.media.filter((m) => kinds.includes(m.kind))
  return files.length === 1 ? files[0].filename : undefined
}

function resultWords(d: Detail): { word: string; tone: 'flag' | 'clean' | 'unsure' | 'sim' } {
  if (d.simulated) return { word: 'Scripted for rehearsal', tone: 'sim' }
  if (d.status === 'synthetic' || d.status === 'edited') return { word: `Signs found, ${(d.band ?? 'moderate').split(' ')[0]}`, tone: 'flag' }
  if (d.status === 'clean') return { word: 'No signs found', tone: 'clean' }
  return { word: 'Unsure', tone: 'unsure' }
}

// "1.00000" on a projector reads as a certain fake; it is a rounding. Say "above 0.99999" instead.
function scoreWords(sc: string): string {
  const n = sc.split('.')[1]?.length ?? 0
  return sc === (1).toFixed(n) ? `above ${(1 - 10 ** -n).toFixed(n)}` : sc
}

function why(s: Signal, d: Detail, acc: Accuracy | null): string {
  if (d.simulated) return 'This rehearsal scenario scripts the answer; no detector looked at a file.'
  const cell = acc?.cells.find((c) => c.cell === d.cell)
  const kind = (d.cell && CELL_WORDS[d.cell]) || 'this kind of input'
  const model = `The ${modelWords(d.model)} ${s.evidence_key === 'media:video' ? 'face' : 'voice'} model`
  const heldOut = cell?.genuine.false_alarm_heldout_pct
  if (s.evidence_key === 'media:document') {
    const counted = d.deepfake_pct != null ? ` It counts ${d.deepfake_pct}% in the deepfake half.` : ' It is not counted.'
    return `${s.reason_en.replace(/ It is one of the checks, not proof on its own\.$/, '')} Document checks read error levels and the file's own labels; they are not calibrated on genuine documents.${counted}`
  }
  if ((d.status === 'synthetic' || d.status === 'edited') && cell && d.score != null) {
    const [sc, line] = sameDecimals(d.score, cell.t_fpr5)
    const rate = heldOut != null ? ` On genuine clips that did not help set it, ${heldOut}% were flagged.` : ''
    return `${model} scored ${scoreWords(sc)}, past the line of ${line} for ${kind}, which was set on ${cell.genuine.judged} genuine clips.${rate} It counts ${d.deepfake_pct ?? 70}% in the deepfake half.`
  }
  if (d.status === 'clean' && cell && d.score != null) {
    const [sc, line] = sameDecimals(d.score, cell.t_fpr20)
    return `${model} scored ${scoreWords(sc)}, below ${line}, where it starts to say unsure for ${kind}. It counts 0% in the deepfake half, and it does not confirm the file is genuine.`
  }
  if (d.status === 'abstain') {
    const reason = s.reason_en.replace(/^[^:]*:\s*unsure:\s*/i, '').replace(/\.$/, '')
    if (cell && d.score != null && /grey band/.test(reason)) {
      const [sc, hi] = sameDecimals(d.score, cell.t_fpr5)
      const [, lo] = sameDecimals(d.score, cell.t_fpr20)
      return `${model} scored ${scoreWords(sc)}, between ${lo} and ${hi} for ${kind}: too close to call. It is not counted.`
    }
    return `${reason.charAt(0).toUpperCase()}${reason.slice(1)}. It is not counted.`
  }
  return s.reason_en
}

export function MediaChecks({ view }: { view: CaseView }) {
  const { acc, error, retry } = useAccuracy()
  const v = view.case.verdict
  const checks = v ? v.signals.filter((s) => s.family === 'F3') : []
  if (checks.length === 0) return null
  // the same number the check's feature row carries in step 2, so the row and this explanation read as one thing
  const numberOf: Record<string, number> = {}
  sortSignals(view).features.forEach((s, i) => (numberOf[s.rule_id + s.evidence_key] = i + 1))
  const onlyFaceVoice = checks.every((s) => s.evidence_key === 'media:video' || s.evidence_key === 'media:audio')
  const settled = acc !== null || error !== null
  return (
    <section className="section media-checks" aria-labelledby="media-checks-h">
      <h3 className="case-head" id="media-checks-h">
        {onlyFaceVoice ? 'What the face and voice checks found' : 'What the media checks found'}
      </h3>
      <ul className="mc-list">
        {checks.map((s) => {
          const d = s.detail as Detail
          const r = resultWords(d)
          const file = fileFor(s, view)
          const no = numberOf[s.rule_id + s.evidence_key]
          return (
            <li key={s.rule_id + s.evidence_key} className={`mc-row mc-${r.tone}`}>
              <div className="mc-what">
                <strong>
                  {no && <span className="callout-no">{no}</span>}
                  {CHECK_WORDS[s.evidence_key] ?? 'Media check'}
                </strong>
                {file && <span className="mc-file">{file}</span>}
              </div>
              <div className="mc-result">
                {r.word}
              </div>
              {/* until the figures are read, the result word stands alone rather than a sentence that changes later */}
              {settled && <p className="mc-why">{why(s, d, acc)}</p>}
            </li>
          )
        })}
      </ul>
      {error !== null && acc === null && <Trouble error={error} what="the detector accuracy figures" onRetry={retry} />}
      <p className="muted small">Unsure is not counted; no signs found never means genuine.</p>
    </section>
  )
}
