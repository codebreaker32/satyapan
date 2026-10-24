import { rupees } from '../lib/format'

// Amounts are set in the display face wherever they appear, the way the banknote's own numerals stand apart.
export function Rupee({ n, className = '' }: { n: number; className?: string }) {
  return <span className={`num ${className}`.trim()}>{rupees(n)}</span>
}
