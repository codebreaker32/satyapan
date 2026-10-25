import { useEffect, useState } from 'react'
import type { Card } from '../lib/api'

// The engine's Card carries say_next; the shared type does not declare it yet, so widen it here rather than
// edit the shared type. These lines are the officer's and never go in read_aloud or the copied text.
type OfficerCard = Card & { say_next?: string[] }

// What the officer reads to the customer: a stop line, three reasons she can check, and ONE instruction. Everything
// else the officer does sits under the card in its own block, labelled as not read aloud.
export function CustomerCard({ hi, en }: { hi: Card; en: Card }) {
  const [lang, setLang] = useState<'hi' | 'en'>('hi')
  const [speaking, setSpeaking] = useState(false)
  const card: OfficerCard = lang === 'hi' ? hi : en
  const sayNext = card.say_next ?? []
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window

  useEffect(() => () => window.speechSynthesis?.cancel(), [])

  const speak = () => {
    if (!canSpeak) return
    if (speaking) {
      window.speechSynthesis.cancel()
      setSpeaking(false)
      return
    }
    const u = new SpeechSynthesisUtterance(card.read_aloud)
    u.lang = lang === 'hi' ? 'hi-IN' : 'en-IN'
    u.rate = 0.92
    u.onend = () => setSpeaking(false)
    u.onerror = () => setSpeaking(false)
    setSpeaking(true)
    window.speechSynthesis.speak(u)
  }

  return (
    <div className="stack">
      <div className="inline">
        <div className="lang-tabs" role="tablist" aria-label="Card language">
          <button role="tab" aria-selected={lang === 'hi'} className={lang === 'hi' ? 'btn btn-primary btn-sm' : 'btn btn-sm'} onClick={() => setLang('hi')} lang="hi">
            हिन्दी
          </button>
          <button role="tab" aria-selected={lang === 'en'} className={lang === 'en' ? 'btn btn-primary btn-sm' : 'btn btn-sm'} onClick={() => setLang('en')}>
            English
          </button>
        </div>
        <button className="btn btn-sm" onClick={speak} disabled={!canSpeak} title={canSpeak ? '' : 'This browser has no speech synthesis'}>
          {speaking ? 'Stop reading' : 'Read aloud'}
        </button>
        <button className="btn btn-sm" onClick={() => navigator.clipboard?.writeText(card.read_aloud)}>
          Copy text
        </button>
      </div>
      <div className={`card card-${card.outcome}`} lang={lang === 'hi' ? 'hi' : 'en'}>
        <p className="card-stop">{card.stop_line}</p>
        {card.reasons.length > 0 && (
          <ol>
            {card.reasons.map((r) => (
              <li key={r.rule_id}>{r.text}</li>
            ))}
          </ol>
        )}
        <p className="card-do">{card.do_now}</p>
        {card.coaching && <p className="card-coach">{card.coaching}</p>}
      </div>
      {sayNext.length > 0 && (
        <div className="stack">
          <p className="inline small">
            <span className="tag">You say next</span>
            <span className="muted">not read aloud, not on her card</span>
          </p>
          <ul className="stack small muted" lang={lang === 'hi' ? 'hi' : 'en'}>
            {sayNext.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
