import { useCallback, useEffect, useState } from 'react'
import { api, type EvidencePack, type Label } from '../lib/api'
import { rupees, when } from '../lib/format'

// The signed evidence pack, with its tamper check: flip one byte, watch it fail, restore it, watch it pass.
export function EvidencePanel({ caseId, signer, version }: { caseId: string; signer: Label | null; version: string | number }) {
  const [original, setOriginal] = useState<EvidencePack | null>(null)
  const [shown, setShown] = useState<EvidencePack | null>(null)
  const [tampered, setTampered] = useState<string | null>(null)
  const [result, setResult] = useState<{ ok: boolean; reason: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const pack = await api.evidence(caseId)
      setOriginal(pack)
      setShown(pack)
      setTampered(null)
      setResult(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [caseId])

  useEffect(() => {
    load()
  }, [load, version])

  // The download is the pack on screen, byte for byte the one just verified. It used to fetch a fresh one, and every
  // fetch signs again with a new time, so the hash on screen never matched the file the officer handed over.
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!original) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(original, null, 2)], { type: 'application/json' }))
    setDownloadUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [original])

  const verify = async () => {
    if (!shown) return
    setBusy(true)
    try {
      setResult(await api.verify(shown))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const flip = () => {
    if (!original) return
    const clone = structuredClone(original)
    const manifest = clone.manifest as { case?: { flag?: { amount_inr?: number } } }
    const flag = manifest.case?.flag
    if (flag && typeof flag.amount_inr === 'number') {
      const before = flag.amount_inr
      flag.amount_inr = before + 1
      setTampered(`amount ${rupees(before)} changed to ${rupees(before + 1)} inside the signed manifest`)
    } else {
      clone.manifest_sha256 = clone.manifest_sha256.replace(/[0-9a-f]$/, (c) => (c === 'a' ? 'b' : 'a'))
      setTampered('one character of the manifest hash changed')
    }
    setShown(clone)
    setResult(null)
  }

  const restore = () => {
    setShown(original)
    setTampered(null)
    setResult(null)
  }

  if (error) return <p className="notice notice-warn">{error}</p>
  if (!shown) return <p className="muted">Signing the evidence pack…</p>

  return (
    <div className="stack" style={{ gap: 16 }}>
      {signer?.mock && (
        <p className="notice">
          <span className="tag tag-sim">Mock signer</span> A local Ed25519 key; production would use{' '}
          {signer.production_source.split(';')[0]}.
        </p>
      )}
      <div className="pack">
        <b>Format</b>
        <span>{shown.format}</span>
        <b>Signed at</b>
        <span>{when(shown.signed_at)}</span>
        <b>Manifest hash</b>
        <span className="hash">{shown.manifest_sha256}</span>
        <b>Signature</b>
        <span className="hash">
          {shown.signature.alg} · {String(shown.signature.value).slice(0, 44)}…
        </span>
        <b>Signer</b>
        <span>
          {signer ? (
            <>
              {signer.route}
            </>
          ) : (
            'local Ed25519 key'
          )}
        </span>
        <b>Inside</b>
        <span>media hashes, the claim with its quoted spans, every signal, the verdict, rulebook and policy versions, consent, decisions, review triggers</span>
      </div>
      {tampered && <p className="notice notice-warn">Tampered copy: {tampered}. Verify it.</p>}
      {result && (
        <p className={result.ok ? 'verify verify-ok' : 'verify verify-bad'} role="status">
          {result.ok ? 'Verifies. ' : 'Does not verify. '}
          {result.reason}
        </p>
      )}
      <div className="inline">
        <button className="btn btn-primary" onClick={verify} disabled={busy}>
          Verify this pack
        </button>
        {tampered ? (
          <button className="btn" onClick={restore}>
            Restore the original
          </button>
        ) : (
          <button className="btn" onClick={flip}>
            Flip a byte
          </button>
        )}
        <a className="btn" href={downloadUrl ?? api.evidenceDownloadUrl(caseId)} download={`${caseId}.evidence.json`}>
          Download JSON
        </a>
      </div>
    </div>
  )
}
