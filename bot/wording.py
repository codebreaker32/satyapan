"""Everything the bot says to a citizen, in Hindi and English, and the rules the reply must keep.

The reply is built from the engine's own customer card (`prototype/satyapan/card.py`), with four changes for a
citizen who is not standing at a bank counter (docs/architecture.md, section 3):

- There is no GREEN, and MATCHES is never shown. MATCHES says the *bank's* signature and outbound log agree; a
  citizen bot has no bank behind it, so a MATCHES case gets GREY's wording and none of its reasons.
- No bank records. Reasons resting on the bank's own records (family F2: outbound log, beneficiary look-up, ledger)
  are left out. In this bot they would come from the demo bank's labelled mocks, and "no money was credited to your
  account" would be a claim about an account the bot has never seen.
- No mock shown as a live look-up. The I4C suspect registry and ED's verify-summon page are answered from labelled
  mocks in the prototype (prototype/satyapan/adapters.py), so "we checked, and this account is on the government's
  suspect list" is left out too. The officer console shows those labels; a citizen's chat has nowhere to show them.
- A slot freed that way may go to a detector's own reason (family F3: voice, face, document), worded exactly as the
  card words it (`card.ground_reason` uses the rulebook sentence for these), so a voice note's reply can still say
  what the voice check found. Never a simulated result.
- No scores, and never the words safe, fake, fraud or genuine (nor their Hindi equivalents). A reason that still
  carries one is dropped rather than reworded on the fly.
- Every reply to a check ends with the official-channel and 1930 line.
"""
from __future__ import annotations

import re

LANGS = ("hi", "en")

# The card's own FORBIDDEN list (prototype/satyapan/card.py) plus "safe" and its Hindi word: the citizen reply must
# never tell anyone a message is safe. Prefix match on "safe" catches safely / safety too.
FORBIDDEN = {
    "en": [r"\bsafe", r"\bfake", r"\bgenuine", r"\bfraud", r"\bscam", r"\bcriminal", r"\bliar"],
    "hi": [r"सुरक्षित", r"नकली", r"असली", r"धोख", r"फ़र्ज़ी", r"फर्जी", r"जाली", r"ठग",
           r"सही", r"सच(?!ेत)", r"प्रामाणिक", r"वैध(?!ानिक)"],
}
ALL_FORBIDDEN = [re.compile(p, re.I) for p in FORBIDDEN["en"] + FORBIDDEN["hi"]]
# What a score looks like on screen. The bot never prints one; this is the lint that says so.
SCORE_LIKE = re.compile(r"\d\s*%|\bscore|स्कोर|\b0\.\d+\b")


def forbidden_in(text: str) -> list[str]:
    """The forbidden patterns that occur in `text` (empty when it is clean)."""
    return [p.pattern for p in ALL_FORBIDDEN if p.search(text)]


def lint(text: str) -> str:
    """Raise if bot copy carries a forbidden word or anything that looks like a score; return it unchanged."""
    bad = forbidden_in(text)
    if bad or SCORE_LIKE.search(text):
        raise ValueError(f"bot copy breaks the wording rules ({bad or 'score'}): {text!r}")
    return text


def pick(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en


# ---------------------------------------------------------------- fixed copy

CONSENT_EN = ("Satyapan checks a message you received: a voice note, a video, a photo of a notice, a PDF or text. "
              "It reads what the message asks you to do and, where it can, looks at the voice and face for signs "
              "of manipulation.\n"
              "- The file is deleted after the check.\n"
              "- Only a fingerprint of it (a hash) and the result are kept.\n"
              "- You get RED, AMBER or GREY with reasons, never a score.\n"
              "Satyapan is a hackathon prototype: use its answer as a warning, not as proof.\n"
              "Do you agree to have the messages you send here checked?")
CONSENT_HI = ("सत्यापन आपको मिला संदेश जाँचता है: वॉइस नोट, वीडियो, नोटिस की फ़ोटो, PDF या टेक्स्ट। यह पढ़ता है "
              "कि संदेश आपसे क्या करने को कहता है, और जहाँ हो सके, आवाज़ और चेहरे में बदलाव के संकेत देखता है।\n"
              "- जाँच के बाद फ़ाइल मिटा दी जाती है।\n"
              "- केवल उसका फ़िंगरप्रिंट (हैश) और नतीजा रखा जाता है।\n"
              "- आपको RED, AMBER या GREY और उसके कारण मिलते हैं, कोई स्कोर नहीं।\n"
              "सत्यापन एक हैकाथॉन प्रोटोटाइप है: इसके जवाब को चेतावनी समझें, सबूत नहीं।\n"
              "क्या आप सहमत हैं कि यहाँ भेजे गए संदेश जाँचे जाएँ?")
# The consent text names "score" to say there is none; it is the one place the word may appear.
CONSENT_BUTTONS = {"inline_keyboard": [[{"text": "हाँ / Yes", "callback_data": "consent:yes"},
                                        {"text": "नहीं / No", "callback_data": "consent:no"}]]}


def consent_text(lang: str) -> str:
    """Both languages, the citizen's own first."""
    first, second = (CONSENT_HI, CONSENT_EN) if lang == "hi" else (CONSENT_EN, CONSENT_HI)
    return f"{first}\n\n{second}"


CONSENT_CHOSEN = {"yes": "हाँ / Yes", "no": "नहीं / No"}
CONSENT_YES = ("Thank you. Forward the voice note, video, photo, PDF or text you want checked. "
               "If you sent something before agreeing, please send it again: it was not checked.",
               "धन्यवाद। जो वॉइस नोट, वीडियो, फ़ोटो, PDF या टेक्स्ट जाँचना है, उसे यहाँ फ़ॉरवर्ड करें। "
               "अगर आपने सहमति से पहले कुछ भेजा था, तो उसे दोबारा भेजें: उसकी जाँच नहीं हुई।")
CONSENT_NO = ("Okay. Nothing will be checked. Send /start if you change your mind.",
              "ठीक है। कुछ भी जाँचा नहीं जाएगा। अगर आप मन बदलें तो /start भेजें।")
CONSENT_WITHDRAWN = ("Your consent is withdrawn and nothing more will be checked. Send /start to agree again.",
                     "आपकी सहमति वापस ले ली गई है, अब कुछ भी जाँचा नहीं जाएगा। दोबारा सहमति के लिए /start भेजें।")
ALREADY_AGREED = ("You have already agreed. Forward a message to check it. /hindi or /english changes the language; "
                  "/stop withdraws your consent.",
                  "आप पहले ही सहमति दे चुके हैं। जाँच के लिए कोई संदेश फ़ॉरवर्ड करें। /hindi या /english से भाषा "
                  "बदलें; /stop से सहमति वापस लें।")
LANG_SET = {"hi": "अब से जवाब हिंदी में आएँगे। वॉइस नोट हिंदी में पढ़े जाएँगे।",
            "en": "Replies will be in English from now on. Voice notes will be read as English."}
PRIVATE_ONLY = ("Please message me directly: I check messages only in a private chat.",
                "कृपया मुझे सीधे संदेश भेजें: मैं केवल निजी चैट में संदेश जाँचता हूँ।")

WAITING = ("Checking… a video can take up to a minute.", "जाँच हो रही है… वीडियो में एक मिनट तक लग सकता है।")

WHAT_WORKS = ("I can check a voice note or audio file, a video, a photo of a notice (jpg, png or webp), a PDF, "
              "or text you paste or forward. Stickers, GIFs, contacts, locations and other files cannot be checked.",
              "मैं ये जाँच सकता हूँ: वॉइस नोट या ऑडियो फ़ाइल, वीडियो, नोटिस की फ़ोटो (jpg, png या webp), PDF, या "
              "आपका चिपकाया या फ़ॉरवर्ड किया टेक्स्ट। स्टिकर, GIF, संपर्क, लोकेशन और दूसरी फ़ाइलें नहीं जाँची जा सकतीं।")
HELP = ("Forward me a suspicious voice note, video, photo of a notice, PDF or text and I will check it. "
        "Commands: /hindi, /english (reply language), /stop (withdraw consent), /start (consent).",
        "कोई संदिग्ध वॉइस नोट, वीडियो, नोटिस की फ़ोटो, PDF या टेक्स्ट मुझे फ़ॉरवर्ड करें, मैं उसकी जाँच करूँगा। "
        "कमांड: /hindi, /english (जवाब की भाषा), /stop (सहमति वापस), /start (सहमति)।")

# Always at the end of a check's reply, whatever happened.
OFFICIAL = ("Verify only through the official channel. If money has already been sent, call 1930 or report at "
            "cybercrime.gov.in.",
            "केवल आधिकारिक माध्यम से ही पुष्टि करें। अगर पैसे भेजे जा चुके हैं, तो 1930 पर कॉल करें या "
            "cybercrime.gov.in पर शिकायत करें।")


def with_official(lang: str, text: str) -> str:
    return f"{text}\n\n{pick(lang, *OFFICIAL)}"


def too_big(lang: str, mb: int) -> str:
    return with_official(lang, pick(lang,
        f"That file is larger than {mb} MB, the most a Telegram bot can download. Please send a shorter clip, or a "
        "screenshot of the notice.",
        f"यह फ़ाइल {mb} MB से बड़ी है, जो Telegram बॉट के डाउनलोड की सीमा है। कृपया छोटी क्लिप, या नोटिस का "
        "स्क्रीनशॉट भेजें।"))


def too_long(lang: str, minutes: int) -> str:
    return with_official(lang, pick(lang,
        f"That recording is longer than {minutes} minutes. Please send the part that gives the instruction.",
        f"यह रिकॉर्डिंग {minutes} मिनट से लंबी है। कृपया वह हिस्सा भेजें जिसमें निर्देश दिया गया है।"))


def unsupported(lang: str) -> str:
    return pick(lang, *WHAT_WORKS)


def rate_limited(lang: str, limit: int, minutes: int) -> str:
    minutes = max(minutes, 1)
    return with_official(lang, pick(lang,
        f"You have sent {limit} messages for checking in the last hour, which is the limit. Please try again in "
        f"about {minutes} minutes. Thank you for your patience.",
        f"आपने पिछले एक घंटे में {limit} संदेश जाँच के लिए भेजे हैं, जो इसकी सीमा है। कृपया लगभग {minutes} मिनट "
        "बाद फिर कोशिश करें। धैर्य के लिए धन्यवाद।"))


def unreadable(lang: str) -> str:
    return with_official(lang, pick(lang, "I could not read that file. ", "मैं यह फ़ाइल नहीं पढ़ सका। ")
                         + pick(lang, *WHAT_WORKS))


def failed(lang: str) -> str:
    return with_official(lang, pick(lang, "Sorry, the check could not be completed right now. Please try again in a "
                                          "few minutes.",
                                    "माफ़ कीजिए, अभी जाँच पूरी नहीं हो सकी। कृपया कुछ मिनट बाद फिर कोशिश करें।"))


def stopped(lang: str) -> str:
    return with_official(lang, pick(lang, "The checking service was stopped before this message was checked. Please "
                                          "send it again later.",
                                    "इस संदेश की जाँच से पहले सेवा बंद हो गई। कृपया इसे बाद में दोबारा भेजें।"))


# ---------------------------------------------------------------- the verdict reply

LABEL = {"RED": ("RED", "RED (लाल)"), "AMBER": ("AMBER", "AMBER (पीला)"), "GREY": ("GREY", "GREY (धूसर)")}
# GREY's headline, as `fusion.HEADLINES[GREY]` words it; used for MATCHES, which the card would head "Matches our
# records". Kept here so a MATCHES case never borrows a single word from its own card.
GREY_HEADLINE = ("Could not confirm. Check via the official channel", "पुष्टि नहीं हो सकी। आधिकारिक माध्यम से जाँच करें")
GREY_NOTE = ("We could not confirm this message either way. That is not a confirmation that it can be trusted.",
             "हम इस संदेश की पुष्टि नहीं कर सके। इसका मतलब यह नहीं है कि इस पर भरोसा किया जा सकता है।")
WHY = ("Why:", "कारण:")
# A RED or AMBER whose every card reason rested on the bank's records still needs a sentence under it.
NO_SHOWN_REASON = ("The checks found warning signs in this message.", "जाँच में इस संदेश में चेतावनी के संकेत मिले।")
BANK_RECORD_FAMILY = "F2"
BANK_RECORD_RULES = ("R-BANK-SELF", "R-BANK-RM-PHONE", "R-PAYEE-NAME", "R-PAYEE-NOT-SENDER", "R-RECEIVER-NAME",
                     "R-LEDGER", "R-OWN-SIGNATURE")
# Rules whose finding is a look-up the prototype answers from a labelled mock (adapters.MockSuspectRegistry, the ED
# verify-summon mock). R-ED-NO-PASSCODE and R-ED-CHANNEL read the notice itself and stay.
MOCK_LOOKUP_RULES = ("R-SUSPECT", "R-ED-SUMMONS-NOTFOUND", "R-ED-WINDOW", "R-ED-FOUND")
DETECTOR_FAMILY = "F3"


def shown_outcome(outcome: str) -> str:
    """What a citizen sees: RED and AMBER as they are, everything else (GREY, MATCHES, anything new) as GREY."""
    return outcome if outcome in ("RED", "AMBER") else "GREY"


def _signal_index(view: dict) -> dict[str, dict]:
    verdict = (view.get("case") or {}).get("verdict") or {}
    return {s.get("rule_id"): s for s in verdict.get("signals") or [] if isinstance(s, dict)}


def _shown(text: str) -> bool:
    return bool(text) and not forbidden_in(text) and not SCORE_LIKE.search(text) and "SIMULATED" not in text


def citizen_reasons(view: dict, lang: str, outcome: str) -> list[str]:
    """The card's reasons a citizen may be shown, at most three, in the citizen's language; then, if a slot is free,
    what a detector found."""
    if outcome == "MATCHES":
        return []
    card = ((view.get("card") or {}).get(lang)) or {}
    signals = _signal_index(view)
    out: list[str] = []
    used: set[str] = set()
    for r in card.get("reasons") or []:
        text = (r.get("text") or "").strip()
        rule = r.get("rule_id") or ""
        sig = signals.get(rule, {})
        if sig.get("family") == BANK_RECORD_FAMILY or rule in BANK_RECORD_RULES or sig.get("severity") == "match":
            continue
        if rule in MOCK_LOOKUP_RULES or not _shown(text):
            continue
        out.append(text)
        used.add(rule)
        if len(out) == 3:
            return out
    for rule, sig in signals.items():
        if sig.get("family") != DETECTOR_FAMILY or sig.get("severity") not in ("hard", "soft") or rule in used:
            continue
        if (sig.get("detail") or {}).get("simulated"):
            continue
        text = str(sig.get("reason_hi" if lang == "hi" else "reason_en") or "").strip()
        if _shown(text):
            out.append(text)
            if len(out) == 3:
                break
    return out


def verdict_reply(view: dict, lang: str) -> str:
    """The reply to a finished check: the colour, the headline, up to three reasons, and the 1930 line."""
    verdict = (view.get("case") or {}).get("verdict") or {}
    outcome = str(verdict.get("outcome") or "GREY")
    shown = shown_outcome(outcome)
    card = ((view.get("card") or {}).get(lang)) or {}
    if shown == "GREY":
        headline = pick(lang, *GREY_HEADLINE)
    else:
        headline = (card.get("headline") or verdict.get("headline_hi" if lang == "hi" else "headline_en") or "").strip()
        if not headline or forbidden_in(headline):
            headline = pick(lang, "Stop and verify through the official channel", "रुकिए। आधिकारिक माध्यम से जाँच करें") \
                if shown == "RED" else pick(lang, "Verify before acting on this", "इस पर कुछ करने से पहले पुष्टि करें")
    reasons = citizen_reasons(view, lang, outcome)
    parts = [pick(lang, *LABEL[shown]), headline]
    if shown == "GREY":
        parts.append(pick(lang, *GREY_NOTE))
    if reasons:
        parts.append("\n" + pick(lang, *WHY) + "\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(reasons, 1)))
    elif shown != "GREY":
        parts.append("\n" + pick(lang, *NO_SHOWN_REASON))
    return with_official(lang, "\n".join(parts))


# Every fixed string is linted once at import, so a wording slip fails the first test (and the bot's start-up).
for _text in (CONSENT_YES + CONSENT_NO + CONSENT_WITHDRAWN + ALREADY_AGREED + PRIVATE_ONLY + WAITING + WHAT_WORKS
              + HELP + OFFICIAL + GREY_HEADLINE + GREY_NOTE + WHY + NO_SHOWN_REASON + tuple(LANG_SET.values())):
    lint(_text)
for _text in (CONSENT_EN, CONSENT_HI):
    if forbidden_in(_text):
        raise ValueError(f"consent copy carries a forbidden word: {_text!r}")
