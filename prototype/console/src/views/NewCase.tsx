import { useEffect, useRef, useState } from 'react'
import { ApiError, api, type CaseView } from '../lib/api'
import { go } from '../lib/router'
import { Blocked, writeTrouble } from '../ui/trouble'

// Opening a case by hand: the bank's flag, read-aloud consent, then the media or the officer's picklist.
type Mode = 'text' | 'file' | 'picklist'

const ISSUERS = ['ED', 'CBI', 'POLICE', 'COURT', 'RBI', 'SEBI', 'CUSTOMS', 'TRAI_DOT', 'TRANSPORT', 'MUNICIPAL', 'BANK_SELF', 'OTHER']
const INSTRUCTIONS = ['TRANSFER_TO_ACCOUNT', 'MOVE_FD', 'INVEST_FOR_RETURNS', 'RETURN_EXCESS_CREDIT', 'PAY_FEE_TO_VERIFY', 'PAY_CHALLAN', 'PAY_LOCAL_TAX', 'NONE']

// The paused payment's receiver as the transfer screen shows it: a UPI ID has an "@", anything else is an account.
function payeeFields(raw: string): { payee_account?: string; payee_vpa?: string } {
  const v = raw.trim()
  if (!v) return {}
  return v.includes('@') ? { payee_vpa: v } : { payee_account: v.replace(/[\s-]/g, '') }
}
const CHANNELS = ['WHATSAPP', 'VIDEO_CALL', 'PHONE_CALL', 'SMS', 'EMAIL', 'POST', 'IN_APP', 'UNKNOWN']
const OWNERS = ['RBI', 'GOVT', 'COURT', 'AGENCY', 'BANK', 'PRIVATE', 'UNKNOWN']
const CUES: Array<[string, string]> = [
  ['arrest_threat', 'threat of arrest'],
  ['secrecy', 'demand for secrecy'],
  ['urgency', 'urgency'],
  ['isolation', 'keeping her on the call'],
  ['guaranteed_returns', 'guaranteed returns'],
]

const CONSENT_HI = {
  check: 'क्या हम यह संदेश आपके लिए जाँच सकते हैं?',
  report: 'क्या हम इसे रिपोर्ट में शामिल कर सकते हैं?',
  memory: 'क्या हम इसकी पहचान बैंक की स्मृति में जोड़ सकते हैं, ताकि अगली बार किसी और को बचाया जा सके?',
}

const SOUND = /\.(ogg|opus|oga|mp3|wav|m4a|weba|aac|amr|flac|mp4|webm|mov|3gp|mkv)$/i
const VIDEO = /\.(mp4|webm|mov|3gp|mkv)$/i

// One sentence for what is running now. The stages follow the requests this form makes, so the words never claim
// progress the server has not reported; the seconds beside them are the only measure, and they are real.
function progressWords(stage: 'open' | 'read' | 'check', mode: string, file: File | null, hasTranscript: boolean): string {
  const video = mode === 'file' && !!file && (VIDEO.test(file.name) || file.type.startsWith('video/'))
  const sound = mode === 'file' && !!file && (SOUND.test(file.name) || file.type.startsWith('audio/') || file.type.startsWith('video/'))
  if (stage === 'open') return 'Opening the case and recording consent.'
  if (stage === 'read') {
    if (!sound) return 'Reading the words on the notice, on this laptop, usually a few seconds.'
    return hasTranscript
      ? 'Uploading. The face and voice checks start now, on this laptop.'
      : 'Reading the speech with Whisper on this laptop; the face and voice checks start at the same time.'
  }
  if (video) return 'Running the checks. A short video takes about 40-60 s here, a one-minute HD video about 2.5 minutes.'
  if (sound) return 'Running the checks. A voice note takes about 10-30 s here.'
  return "Checking the message against the issuer rules and the bank's records."
}

export function NewCase({ onView }: { onView: (v: CaseView) => void }) {
  const [reason, setReason] = useState('premature FD closure + RTGS to first-time payee')
  const [amount, setAmount] = useState('3800000')
  const [channel, setChannel] = useState<'branch' | 'callback'>('branch')
  const [payingTo, setPayingTo] = useState('')
  const [consent, setConsent] = useState({ check: true, report: true, memory: false })
  const [lang, setLang] = useState<'hi' | 'en'>('hi')
  const [mode, setMode] = useState<Mode>('text')
  const [text, setText] = useState('')
  const [sender, setSender] = useState('')
  const [signed, setSigned] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  // A recording made here is the customer's phone played into this microphone: a replay, which hides a clone's
  // traces. The server is told so, and then never reports "no signs" for it, only "signs" or "unsure".
  const [recorded, setRecorded] = useState(false)
  const [docLang, setDocLang] = useState<'hi' | 'en'>('hi') // how OCR / speech-to-text reads the file; separate from the consent read-aloud language
  const [transcript, setTranscript] = useState('')
  const [needTranscript, setNeedTranscript] = useState(false)
  const [pick, setPick] = useState({ issuer: 'ED', instruction: 'TRANSFER_TO_ACCOUNT', channel: 'VIDEO_CALL', claimed_owner: 'RBI', account: '', ifsc: '', vpa: '' })
  const [cues, setCues] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  // What is running while she waits, and for how long: a short video's face and voice checks take 40-60 s here and
  // a one-minute HD video about 2.5 minutes, and "Checking…" alone for that long reads as a hung screen.
  const [stage, setStage] = useState<'open' | 'read' | 'check'>('open')
  const [startedAt, setStartedAt] = useState(0)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!busy) return
    const t = window.setInterval(() => setTick(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [busy])
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setStage('open')
    setStartedAt(Date.now())
    setTick(Date.now())
    setError(null)
    try {
      let v = await api.openCase({ reason, amount_inr: Number(amount) || 0, customer_ref: 'cust-demo', channel, ...payeeFields(payingTo) })
      const id = v.case.id
      v = await api.consent(id, { ...consent, lang })
      // `Blocked`, not `Error`: these three are sentences this screen wrote about something it checked itself, so
      // they are shown as they are. Everything else that lands in the catch below is a refusal or a dead wire and
      // gets the words for one of those, never the browser's own string.
      if (!consent.check) throw new Blocked('Without consent to check the message, the case stays open and nothing is run.')
      if (mode === 'text') {
        v = await api.addText(id, { text, sender_number: sender || null, signed, kind: 'text', filename: 'message.txt' })
      } else if (mode === 'file') {
        if (!file) throw new Blocked('Choose a file first.')
        setStage('read')
        try {
          v = await api.addMedia(id, file, {
            derived_text: transcript || undefined,
            sender_number: sender || undefined,
            language: docLang,
            channel: recorded ? 'live-replay' : undefined,
          })
        } catch (err) {
          if (err instanceof ApiError && err.status === 422) {
            setNeedTranscript(true)
            throw new Blocked('No speech-to-text or OCR is installed on this laptop. Paste the transcript below and submit again.')
          }
          throw err
        }
      } else {
        v = await api.addPicklist(id, {
          issuer: pick.issuer,
          instruction: pick.instruction,
          channel: pick.channel,
          claimed_owner: pick.claimed_owner,
          account: pick.account || null,
          ifsc: pick.ifsc || null,
          vpa: pick.vpa || null,
          pressure: cues,
        })
      }
      setStage('check')
      v = await api.run(id)
      onView(v)
      go({ name: 'case', id })
    } catch (err) {
      // This form is a write path from its first request onward: `Open a new case` posts a case before anything
      // else happens. So a dead wire here reads "Not recorded", and the retry is the button the officer is already
      // looking at — pressing `Run the check` again re-runs the whole submit, so there is nothing else to offer.
      setError(writeTrouble(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <header className="page-head">
        <div className="stack">
          <h1>Open a case</h1>
          <p>In the bank the flag arrives from transaction monitoring. Here you type it, take consent aloud, and give the check what the customer showed you.</p>
        </div>
      </header>

      <section className="section">
        <h2>The bank's flag</h2>
        <div className="grid-2">
          <label className="field">
            <span>Why the transfer was paused</span>
            <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} required />
          </label>
          <label className="field">
            <span>Amount in rupees</span>
            <input className="input" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="field">
            <span>Paying to, as the transfer shows it (account or UPI ID)</span>
            <input className="input" value={payingTo} onChange={(e) => setPayingTo(e.target.value)} placeholder="optional" />
          </label>
          <label className="field">
            <span>Where the officer is</span>
            <select value={channel} onChange={(e) => setChannel(e.target.value as 'branch' | 'callback')}>
              <option value="branch">At the branch counter, customer present</option>
              <option value="callback">FRMU call-back</option>
            </select>
          </label>
        </div>
      </section>

      <section className="section section-alt">
        <h2>Consent, read aloud</h2>
        <div className="inline">
          <span style={{ fontWeight: 600 }}>Read in</span>
          <div className="lang-tabs">
            <button type="button" className={lang === 'hi' ? 'btn btn-primary btn-sm' : 'btn btn-sm'} onClick={() => setLang('hi')} lang="hi">
              हिन्दी
            </button>
            <button type="button" className={lang === 'en' ? 'btn btn-primary btn-sm' : 'btn btn-sm'} onClick={() => setLang('en')}>
              English
            </button>
          </div>
        </div>
        <div className="stack">
          <ConsentRow
            checked={consent.check}
            onChange={(v) => setConsent({ ...consent, check: v })}
            en="May we check this message for you?"
            hi={CONSENT_HI.check}
            lang={lang}
          />
          <ConsentRow
            checked={consent.report}
            onChange={(v) => setConsent({ ...consent, report: v })}
            en="May we include it in a report to the authorities?"
            hi={CONSENT_HI.report}
            lang={lang}
          />
          <ConsentRow
            checked={consent.memory}
            onChange={(v) => setConsent({ ...consent, memory: v })}
            en="May we add its fingerprint to the bank's memory, so the next person is protected too?"
            hi={CONSENT_HI.memory}
            lang={lang}
          />
        </div>
      </section>

      <section className="section">
        <h2>What the customer showed you</h2>
        <div className="lang-tabs" role="tablist">
          {(['text', 'file', 'picklist'] as Mode[]).map((m) => (
            <button type="button" role="tab" aria-selected={mode === m} key={m} className={mode === m ? 'btn btn-primary' : 'btn'} onClick={() => setMode(m)}>
              {m === 'text' ? 'Paste the text' : m === 'file' ? 'Upload a file' : 'Claim-only: tick what she was told'}
            </button>
          ))}
        </div>

        {mode === 'text' && (
          <div className="grid-2">
            <label className="field">
              <span>The message, transcript or notice text</span>
              <textarea value={text} onChange={(e) => setText(e.target.value)} required lang={lang} />
            </label>
            <div className="stack">
              <label className="field">
                <span>Sender or caller number, if known</span>
                <input className="input" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="+91…" />
              </label>
              <label className="check-row">
                <input type="checkbox" checked={signed} onChange={(e) => setSigned(e.target.checked)} />
                <span>Demo: treat this as a notice the bank itself signed (adds the bank's content signature).</span>
              </label>
            </div>
          </div>
        )}

        {mode === 'file' && (
          <div className="grid-2">
            <div className="stack">
              <label className="field">
                <span>Choose from this device: a voice note, video, photo of a notice, or PDF</span>
                <input className="input" type="file" onChange={(e) => {
                    setFile(e.target.files?.[0] ?? null)
                    setRecorded(false)
                  }} accept="audio/*,video/*,image/*,.pdf,.txt,.opus,.weba,.amr,.aac,.m4a,.3gp,.mkv,.mov" />
              </label>
              <p className="muted small">
                Voice notes and audio (ogg, opus, mp3, wav, m4a, aac, amr), video (mp4, mov, webm, 3gp, mkv), a photo of a notice, a PDF
                or text, up to 100 MB. The file stays on this laptop.
              </p>
              <Recorder
                onDone={(f) => {
                  setFile(f)
                  setRecorded(true)
                }}
              />
              {file && <p className="muted small">Will upload: {file.name}</p>}
              <div className="inline">
                <span style={{ fontWeight: 600 }}>Notice language</span>
                <div className="lang-tabs">
                  <button type="button" className={docLang === 'hi' ? 'btn btn-primary btn-sm' : 'btn btn-sm'} onClick={() => setDocLang('hi')} lang="hi">
                    हिन्दी
                  </button>
                  <button type="button" className={docLang === 'en' ? 'btn btn-primary btn-sm' : 'btn btn-sm'} onClick={() => setDocLang('en')}>
                    English
                  </button>
                </div>
              </div>
              <p className="muted small">The language the document or recording is in, so it is read correctly.</p>
              <label className="field">
                <span>Sender or caller number, if known</span>
                <input className="input" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="+91…" />
              </label>
            </div>
            <label className="field">
              <span>{needTranscript ? 'Transcript (speech-to-text is not installed here)' : 'Transcript, if you already have one'}</span>
              <textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} lang={lang} />
            </label>
          </div>
        )}

        {mode === 'picklist' && (
          <div className="stack" style={{ gap: 16 }}>
            <p className="muted">The media was deleted or never shown. The officer ticks what the customer says she was told; the issuer rulebook and the bank's records still run.</p>
            <div className="grid-2">
              <label className="field">
                <span>Who the caller claimed to be</span>
                <select value={pick.issuer} onChange={(e) => setPick({ ...pick, issuer: e.target.value })}>
                  {ISSUERS.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>What she was told to do</span>
                <select value={pick.instruction} onChange={(e) => setPick({ ...pick, instruction: e.target.value })}>
                  {INSTRUCTIONS.map((x) => (
                    <option key={x} value={x}>
                      {x.replaceAll('_', ' ').toLowerCase()}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Over which channel</span>
                <select value={pick.channel} onChange={(e) => setPick({ ...pick, channel: e.target.value })}>
                  {CHANNELS.map((x) => (
                    <option key={x} value={x}>
                      {x.replaceAll('_', ' ').toLowerCase()}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Who the account is said to belong to</span>
                <select value={pick.claimed_owner} onChange={(e) => setPick({ ...pick, claimed_owner: e.target.value })}>
                  {OWNERS.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Payee account</span>
                <input className="input" value={pick.account} onChange={(e) => setPick({ ...pick, account: e.target.value })} inputMode="numeric" />
              </label>
              <label className="field">
                <span>IFSC</span>
                <input className="input" value={pick.ifsc} onChange={(e) => setPick({ ...pick, ifsc: e.target.value.toUpperCase() })} />
              </label>
              <label className="field">
                <span>UPI ID</span>
                <input className="input" value={pick.vpa} onChange={(e) => setPick({ ...pick, vpa: e.target.value })} />
              </label>
            </div>
            <div className="stack">
              <span style={{ fontWeight: 600 }}>Pressure she describes</span>
              <div className="inline">
                {CUES.map(([k, label]) => (
                  <label key={k} className="check-row" style={{ padding: '8px 12px' }}>
                    <input type="checkbox" checked={cues.includes(k)} onChange={(e) => setCues(e.target.checked ? [...cues, k] : cues.filter((c) => c !== k))} />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        )}
      </section>

      <div className="actions">
        <button className="btn btn-primary" type="submit" disabled={busy}>
          {busy ? 'Checking…' : 'Run the check'}
        </button>
        {busy && (
          <p className="run-progress">
            <span role="status">{progressWords(stage, mode, file, Boolean(transcript.trim()))}</span>
            {/* the seconds tick every second; a screen reader hears the stage changes only */}
            <span className="elapsed" aria-hidden="true">
              {Math.max(0, Math.round((tick - startedAt) / 1000))} s
            </span>
          </p>
        )}
        {error && (
          <p className="notice notice-warn" role="alert">
            {error}
          </p>
        )}
      </div>
    </form>
  )
}

// Recording in the browser, for a voice note or a video the customer plays aloud at the counter or that the officer
// records on a call-back. The recording becomes an ordinary upload: speech-to-text reads it on the server, and its
// soundtrack goes to the audio detector. Browsers allow the microphone and camera on http://127.0.0.1 and localhost.
type RecKind = 'audio' | 'video'

function pickMime(kind: RecKind): string | undefined {
  const options =
    kind === 'video'
      ? ['video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4']
      : ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4']
  if (typeof MediaRecorder === 'undefined') return undefined
  return options.find((m) => MediaRecorder.isTypeSupported(m))
}

// .weba for a voice-only WebM, so the server reads it as audio; .m4a / .mp4 where the browser records MP4 (Safari).
function extensionFor(type: string, kind: RecKind): string {
  if (type.includes('ogg')) return 'ogg'
  if (type.includes('mp4')) return kind === 'video' ? 'mp4' : 'm4a'
  return kind === 'video' ? 'webm' : 'weba'
}

// The peak level (0 to 1) below which no sound is reaching the microphone. A muted laptop microphone gave the
// browser 0.003 at its loudest (the click as it opened) and 0.00003 after it; a voice at arm's length, with the
// browser's own gain control, peaks far above 0.01. Advice only: the server's speech detector decides.
const QUIET = 0.01

// The meter's width: -60 dB is empty and 0 dB is full, so a voice lands in the middle rather than in the first pixel.
const meterPct = (peak: number) => Math.round(Math.max(0, Math.min(1, (20 * Math.log10(Math.max(peak, 1e-4)) + 60) / 60)) * 100)

function Recorder({ onDone }: { onDone: (f: File) => void }) {
  const [kind, setKind] = useState<RecKind | null>(null)
  const [state, setState] = useState<'idle' | 'recording' | 'done'>('idle')
  const [seconds, setSeconds] = useState(0)
  const [playback, setPlayback] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [metering, setMetering] = useState(false)
  const [level, setLevel] = useState(0)
  const [heard, setHeard] = useState(false)
  const [mic, setMic] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const chunks = useRef<Blob[]>([])
  const timer = useRef<number | null>(null)
  const live = useRef<HTMLVideoElement | null>(null)
  const listening = useRef<{ ctx: AudioContext; frame: number } | null>(null)

  const stopListening = () => {
    if (!listening.current) return
    cancelAnimationFrame(listening.current.frame)
    listening.current.ctx.close().catch(() => undefined)
    listening.current = null
  }
  const stopTracks = () => {
    stopListening()
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    if (timer.current) window.clearInterval(timer.current)
  }
  useEffect(() => stopTracks, [])

  // The level meter. A muted or wrong microphone hands the browser silence without any error: on 23 Oct a
  // 23-second recording reached the server holding nothing but the microphone's noise floor, and nobody could tell
  // until the check came back with no text. A bar that moves while she speaks, and a line when it does not, shows
  // it during the recording instead. It reads the same stream the recorder saves.
  const listen = (ctx: AudioContext, s: MediaStream) => {
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 2048
    ctx.createMediaStreamSource(s).connect(analyser)
    const buf = new Float32Array(analyser.fftSize)
    let shown = 0
    const tick = (t: number) => {
      if (!listening.current) return
      analyser.getFloatTimeDomainData(buf)
      let peak = 0
      for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i]))
      if (peak >= QUIET) setHeard(true)
      if (t - shown > 100) {
        setLevel(peak)
        shown = t
      }
      listening.current.frame = requestAnimationFrame(tick)
    }
    listening.current = { ctx, frame: requestAnimationFrame(tick) }
  }

  const start = async (k: RecKind) => {
    setProblem(null)
    setPlayback(null)
    setMetering(false)
    setLevel(0)
    setHeard(false)
    setMic('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setProblem('This browser cannot record here. Choose a file from the device instead.')
      return
    }
    // Made inside the click, before the permission prompt, so the browser lets it run: an audio context that is
    // not running reads all zeros, and a meter reading zeros would say "no sound" about a working microphone.
    const ctx = typeof AudioContext === 'undefined' ? null : new AudioContext()
    try {
      // Raw sound: the browser's echo cancelling, noise removal and automatic volume reshape a voice before the
      // detector hears it, and the detector was calibrated on unprocessed audio.
      const audio = { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
      const s = await navigator.mediaDevices.getUserMedia(k === 'video' ? { audio, video: true } : { audio })
      stream.current = s
      setMic(s.getAudioTracks()[0]?.label ?? '')
      if (ctx) {
        await ctx.resume().catch(() => undefined)
        try {
          if (ctx.state !== 'running') throw new Error('audio context not running')
          listen(ctx, s)
          setMetering(true)
        } catch {
          ctx.close().catch(() => undefined)   // no meter rather than a wrong one; the recording itself is unaffected
        }
      }
      if (k === 'video' && live.current) {
        live.current.srcObject = s
        live.current.muted = true
        void live.current.play()
      }
      const mime = pickMime(k)
      const r = new MediaRecorder(s, mime ? { mimeType: mime } : undefined)
      chunks.current = []
      r.ondataavailable = (e) => {
        if (e.data.size) chunks.current.push(e.data)
      }
      r.onstop = () => {
        const type = (r.mimeType || (k === 'video' ? 'video/webm' : 'audio/webm')).split(';')[0]
        const blob = new Blob(chunks.current, { type })
        const file = new File([blob], `recording-${new Date().toISOString().replace(/[:.]/g, '-')}.${extensionFor(type, k)}`, { type })
        setPlayback(URL.createObjectURL(blob))
        setState('done')
        stopTracks()
        if (live.current) live.current.srcObject = null
        onDone(file)
      }
      recorder.current = r
      r.start()
      setKind(k)
      setSeconds(0)
      setState('recording')
      timer.current = window.setInterval(() => setSeconds((x) => x + 1), 1000)
    } catch {
      stopTracks()
      if (ctx && ctx.state !== 'closed') ctx.close().catch(() => undefined)
      setProblem('The browser was not allowed to use the microphone or camera. Allow it from the address bar and try again.')
    }
  }

  const stop = () => recorder.current?.state === 'recording' && recorder.current.stop()

  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="inline">
        {state !== 'recording' ? (
          <>
            <button type="button" className="btn btn-sm" onClick={() => start('audio')}>
              Record voice
            </button>
            <button type="button" className="btn btn-sm" onClick={() => start('video')}>
              Record video
            </button>
          </>
        ) : (
          <button type="button" className="btn btn-primary btn-sm" onClick={stop}>
            Stop recording ({seconds} s)
          </button>
        )}
      </div>
      {kind === 'video' && <video ref={live} playsInline style={{ width: '100%', maxHeight: 220, display: state === 'recording' ? 'block' : 'none' }} />}
      {state === 'recording' && metering && (
        <div className="stack" style={{ gap: 4 }}>
          <span className="muted small">Microphone{mic ? `: ${mic}` : ''}</span>
          <div className="meter" role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={meterPct(level)}>
            <span style={{ transform: `scaleX(${meterPct(level) / 100})` }} />
          </div>
        </div>
      )}
      {state === 'recording' && metering && seconds >= 3 && !heard && (
        <p className="notice notice-warn" role="status">
          No sound is reaching the microphone. Check that {mic ? `“${mic}”` : 'it'} is the right microphone and is not muted, then stop and record again.
        </p>
      )}
      {state === 'done' && playback && kind === 'audio' && <audio controls src={playback} style={{ width: '100%' }} />}
      {state === 'done' && playback && kind === 'video' && <video controls src={playback} style={{ width: '100%', maxHeight: 220 }} />}
      {state === 'done' && metering && !heard ? (
        <p className="notice notice-warn" role="status">
          Recorded {seconds} s, but almost no sound reached the microphone{mic ? ` (“${mic}”)` : ''}. Check that it is the right microphone and is not muted, then record again.
        </p>
      ) : (
        state === 'done' && <p className="muted small">Recorded {seconds} s. Speech-to-text reads it when you run the check, and its text appears under “What the message claims”.</p>
      )}
      {problem && (
        <p className="notice notice-warn" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}

function ConsentRow({ checked, onChange, en, hi, lang }: { checked: boolean; onChange: (v: boolean) => void; en: string; hi: string; lang: 'hi' | 'en' }) {
  return (
    <label className="check-row">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="stack" style={{ gap: 2 }}>
        <span lang={lang} style={{ fontWeight: 600 }}>
          {lang === 'hi' ? hi : en}
        </span>
        <span className="muted small" lang={lang === 'hi' ? 'en' : 'hi'}>
          {lang === 'hi' ? en : hi}
        </span>
      </span>
    </label>
  )
}
