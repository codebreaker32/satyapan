import { ApiError, OfflineError } from '../lib/api'

// What the officer reads when a request did not work, and the one place the console decides those words.
//
// The action path makes the distinction and decisions.md records it: an unreachable service reads "Not
// recorded: ... nothing was recorded", never "Refused: Failed to fetch", because "refused" is what a policy
// refusal says and she has to be able to tell a dead wire from a rule saying no. The read paths used to lack it:
// with the wire cut `#/cases` rendered its heading, its lede and nothing else, and the failure showed up only
// as an unhandled page error in devtools, which reads as a blank screen.
//
// Two prefixes across the whole console, and only two:
//   "Refused: …"      the service answered and said no — a policy refusal, a 403, a 422, a 404.
//   "Not recorded: …" the request never arrived, nothing changed behind her, press the button again.
//   "Not loaded: …"   the same dead wire on a path that was reading, where nothing was being recorded at all.
// The third is the second with the verb the path was actually doing; inventing a different vocabulary for reads
// would have given the officer two things to learn for one fact about the wire.

// A condition the screen checked itself, in the console's own sentence: "Choose a file first." It is neither a
// refusal nor a dead wire and must not be dressed as either. Carrying it as its own type is what lets everything
// else fall back to a console sentence instead of to a raw browser string.
export class Blocked extends Error {}

// Nothing the browser threw ever reaches the officer: "Failed to fetch", "NetworkError" and "TypeError" are not
// sentences about her case. An unexpected throw lands on the same advice as a dead wire, because from where she
// stands the two are the same thing — the screen did not do what she asked.
const UNEXPLAINED_WRITE =
  'Not recorded: this screen could not send the request, so nothing was recorded. Press the button again; if it keeps failing, restart the Satyapan service.'

export function writeTrouble(e: unknown): string {
  if (e instanceof Blocked) return e.message
  if (e instanceof OfflineError)
    return 'Not recorded: the Satyapan service did not answer, so nothing was recorded. Check that it is running and press the button again.'
  if (e instanceof ApiError) return `Refused: ${e.message}`
  return UNEXPLAINED_WRITE
}

// `what` names the thing that did not arrive, in the officer's words: "the case list", "campaign memory",
// "case SP-1042". The middle clause is the one requirement an empty screen cannot meet on its own: "No cases
// yet" is true about an empty session and a lie when the request failed, and the two must never look the same.
export function readTrouble(e: unknown, what: string): string {
  if (e instanceof Blocked) return e.message
  if (e instanceof OfflineError)
    return `Not loaded: the Satyapan service did not answer, so ${what} could not be read. Nothing is shown below because nothing was read, not because there is nothing there. Check that the service is running, then press Retry.`
  if (e instanceof ApiError)
    return `Refused: ${e.message}. The service answered and would not give us ${what}, so nothing below it is shown.`
  return `Not loaded: this screen could not read ${what}. Press Retry; if it keeps failing, restart the Satyapan service.`
}

// The sentence sits where the data should have been, and the way to try again sits under it. Retry re-runs the
// fetch in place: a page reload would also work on a hash route, but it would throw away every case the officer
// had already opened in this session, and the wire coming back is not a reason to lose them.
export function Trouble({ error, what, onRetry }: { error: unknown; what: string; onRetry: () => void }) {
  return (
    <div className="stack" style={{ gap: 12, justifyItems: 'start', maxWidth: '80ch' }}>
      <p className="notice notice-warn" role="alert">
        {readTrouble(error, what)}
      </p>
      <button className="btn btn-sm" onClick={onRetry}>
        Retry
      </button>
    </div>
  )
}
