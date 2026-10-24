import type { Outcome } from '../lib/api'

// The four verdict marks. Colour never carries the verdict alone: the word and one of these always ride with it.
export function VerdictMark({ outcome, size = 56 }: { outcome: Outcome; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 48 48',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 3,
    strokeLinejoin: 'round' as const,
    strokeLinecap: 'round' as const,
    'aria-hidden': true,
    focusable: false,
  }
  switch (outcome) {
    case 'RED':
      return (
        <svg {...common}>
          <path d="M16 4h16l12 12v16L32 44H16L4 32V16z" />
          <path d="M15 24h18" />
        </svg>
      )
    case 'AMBER':
      return (
        <svg {...common}>
          <path d="M24 6 44 40H4z" />
          <path d="M24 18v10" />
          <path d="M24 33.5v.5" />
        </svg>
      )
    case 'GREY':
      return (
        <svg {...common}>
          <circle cx="24" cy="24" r="19" />
          <path d="M18 19.5c0-3.5 2.7-6 6-6s6 2.3 6 5.5c0 4-6 4.5-6 9" />
          <path d="M24 34.5v.5" />
        </svg>
      )
    case 'MATCHES':
      return (
        <svg {...common}>
          <circle cx="24" cy="24" r="19" />
          <path d="m14 25 7 7 13-15" />
        </svg>
      )
  }
}
