const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

export function rupees(n: number): string {
  return inr.format(n)
}

export function when(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

export function shortHash(h: string, n = 12): string {
  return h.length > n * 2 ? `${h.slice(0, n)}…${h.slice(-n)}` : h
}

// True when the bank flag's reason already spells the amount (₹, Rs, INR, Rupees, or "45 lakh" / "2 crore" /
// Devanagari रुपये/लाख/करोड़ phrasings), so the amount chip beside it would only duplicate it.
export function spellsAmount(reason: string): boolean {
  // every alternative requires a digit beside the currency word, so "रुपये की मांग" or "2 lace sarees" never hides a real amount
  return /₹|\b(?:rs\.?|inr|rupees?)\s?\d|\d[\d,]*\s*(?:lakh|lac\b|crore|लाख|करोड़|रुपये|रुपए)|(?:रुपये|रुपए)\s*\d/i.test(reason)
}
