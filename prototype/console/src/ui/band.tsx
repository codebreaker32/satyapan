import type { CaseView } from '../lib/api'
import { FAMILY_WORD, OUTCOME_WORD, restsOn } from '../lib/spans'
import { VerdictMark } from './marks'

interface Props {
  view: CaseView
  titles: Record<string, string>
}

// The engine's explanation names rules by id (R-ED-WINDOW). On the band it is set in the largest type on screen, so
// the id is swapped for the rule's own title; the id itself still appears verbatim in the case record and the pack.
// "Instruction checks 90%, deepfake check 70%, half each: combined 80%, at or above the 40% line for RED." -> "At or
// above the 40% line for RED." The score panel shows the three numbers; the rest of the sentence still says why.
function withoutScoreOpening(text: string): string {
  return text.replace(/^Instruction checks \d+%, deepfake check \d+%, half each: combined [\d.]+%, (\w)/, (_m, c: string) => c.toUpperCase())
}

export function humanise(text: string, titles: Record<string, string>): string {
  return text.replace(/R-[A-Z0-9-]+/g, (id) => titles[id] ?? id)
}

export function VerdictBand({ view, titles }: Props) {
  const v = view.case.verdict
  if (!v) return null
  const { anchor, second } = restsOn(view)
  const word = OUTCOME_WORD[v.outcome]
  const sc = v.scores
  return (
    <section className={`band band-${v.outcome}`} aria-live="polite">
      <div className="band-verdict">
        <VerdictMark outcome={v.outcome} size={84} />
        <div className="band-words">
          <span className="band-word">{word.en}</span>
          <span className="band-word-hi" lang="hi">
            {word.hi}
          </span>
        </div>
      </div>
      <div className="band-head">
        <p className="hi" lang="hi">
          {v.headline_hi}
        </p>
        <p className="en">{v.headline_en}</p>
      </div>
      <div className="band-rests">
        {/* Media was judged, so the combined score decided: the rule-ladder headings below would
            say "one rule alone never gives RED", which is no longer what decided this case. Officer only; the
            customer card never shows a score. */}
        {sc && (
          <>
            <h3>Instruction and deepfake checks, half each</h3>
            <ul>
              <li>
                <b>Instruction checks</b>
                <span>{sc.instruction_pct}%</span>
              </li>
              <li>
                <b>Deepfake check</b>
                <span>
                  {sc.deepfake_pct}%
                </span>
              </li>
              <li>
                <b>Combined</b>
                <span>{sc.combined_pct}%</span>
              </li>
            </ul>
            {/* What it rests on, compactly when there is a pair (the rules' RED pair, or a rule plus the media check):
                the panel above already carries the numbers, and a full paragraph here pushed the customer card below
                the fold at 1280x720. Otherwise the engine's sentence, minus the opening that repeats the numbers. */}
            {anchor && second ? (
              <>
                <h3>Rests on two independent checks</h3>
                <ul>
                  <li>
                    <b>{FAMILY_WORD[anchor.family]}</b>
                    <span>{titles[anchor.rule_id] ?? anchor.rule_id}</span>
                  </li>
                  <li>
                    <b>{FAMILY_WORD[second.family]}</b>
                    <span>{titles[second.rule_id] ?? second.rule_id}</span>
                  </li>
                </ul>
              </>
            ) : (
              <p>{humanise(withoutScoreOpening(v.explanation), titles)}</p>
            )}
          </>
        )}
        {!sc && v.outcome === 'RED' && anchor && second && (
          <>
            <h3>Rests on two independent checks</h3>
            <ul>
              <li>
                <b>{FAMILY_WORD[anchor.family]}</b>
                <span>{titles[anchor.rule_id] ?? anchor.rule_id}</span>
              </li>
              <li>
                <b>{FAMILY_WORD[second.family]}</b>
                <span>{titles[second.rule_id] ?? second.rule_id}</span>
              </li>
            </ul>
          </>
        )}
        {/* A capped AMBER: two independent checks agreed, but no money demand was read, so the engine stopped at
            AMBER. The lone-rule heading below would be wrong here; the engine's own sentence says what happened. */}
        {!sc && v.outcome === 'AMBER' && anchor && v.no_money_cap && (
          <>
            <h3>Two independent checks agree, and nothing here asked for money</h3>
            <p>{humanise(v.explanation, titles)}</p>
          </>
        )}
        {!sc && v.outcome === 'AMBER' && anchor && !v.no_money_cap && (
          <>
            <ul>
              <li>
                <b>{FAMILY_WORD[anchor.family]}</b>
                <span>{titles[anchor.rule_id] ?? anchor.rule_id}</span>
              </li>
            </ul>
          </>
        )}
        {!sc && v.outcome === 'AMBER' && !anchor && (
          <>
            <h3>Why this is AMBER and not RED</h3>
            <p>
              {humanise(v.explanation, titles)} No hard rule fired, so this can never be RED.
            </p>
          </>
        )}
        {/* The band used to assert "No warning signs found" on every GREY. That is false whenever the extractor read
            an authority, an instruction, a payee or a pressure cue and nothing could check it — the same screen then
            lists those cues under "Also noted, never counted". The band now says what the engine said. */}
        {/* "Nothing here could be checked" was itself an overclaim: a GREY can carry an informational match, such
            as ED's own system recognising the summons. The heading is true of both branches; the engine's sentence
            says which one this is. */}
        {!sc && v.outcome === 'GREY' && (
          <>
            <h3>What we could and could not check</h3>
            <p>{humanise(v.explanation, titles)}</p>
          </>
        )}
        {!sc && v.outcome === 'MATCHES' && (
          <>
            <h3>Signature and outbound log agree</h3>
            <p>The bank signed this message and has it on record. We still never ask anyone to move money to a “safe account”.</p>
          </>
        )}
      </div>
    </section>
  )
}
