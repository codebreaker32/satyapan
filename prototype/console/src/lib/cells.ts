// Plain words for the detectors' calibration cells and model ids, shared by the case screen's media checks and the
// Evaluation page, so the two never name the same kind of input differently.

export const CELL_WORDS: Record<string, string> = {
  'video/hd': 'HD video',
  'video/sd': 'WhatsApp-size video',
  'video/live-replay': 'video re-filmed at the counter',
  'hi/clean': 'a clean Hindi recording',
  'hi/whatsapp-opus': 'a Hindi WhatsApp voice note',
  'hi/phone-8k': 'a Hindi phone call (8 kHz)',
  'hi/live-replay': 'Hindi replayed through a speaker',
  'en/clean': 'a clean English recording',
  'en/whatsapp-opus': 'an English WhatsApp voice note',
  'en/phone-8k': 'an English phone call (8 kHz)',
  'en/live-replay': 'English replayed through a speaker',
}

// The Evaluation table's row names, which stand alone rather than finishing a sentence.
export const CELL_TITLES: Record<string, string> = {
  'video/hd': 'HD video',
  'video/sd': 'WhatsApp-size video',
  'hi/clean': 'Hindi, clean recording',
  'hi/whatsapp-opus': 'Hindi, WhatsApp voice note',
  'hi/phone-8k': 'Hindi, phone call (8 kHz)',
  'en/clean': 'English, clean recording',
  'en/whatsapp-opus': 'English, WhatsApp voice note',
  'en/phone-8k': 'English, phone call (8 kHz)',
}

// "GenD_CLIP_L_14@891ce01" -> "GenD CLIP-L/14"; anything unknown is shown as it came.
export function modelWords(model: string | null | undefined): string {
  const m = model ?? ''
  if (m.startsWith('GenD_CLIP_L_14')) return 'GenD CLIP-L/14'
  if (m.startsWith('DF_Arena_500M')) return 'DF Arena 500M'
  if (m.startsWith('AASIST')) return 'AASIST-L'
  return m.split('@')[0] || 'the detector'
}

// A score and its line with the same number of decimals, enough to tell them apart: the Hindi voice lines sit at
// 0.9999 and above, where three decimals would print the score and the line as the same number.
export function sameDecimals(score: number, line: number): [string, string] {
  let digits = 3
  while (digits < 7 && score.toFixed(digits) === line.toFixed(digits)) digits++
  if (line > 0.999) digits = Math.max(digits, 5)
  return [score.toFixed(digits), line.toFixed(digits)]
}
