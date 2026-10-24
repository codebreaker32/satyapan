"""Claim extraction: turn a transcript / OCR text / officer picklist into a grounded Claim.

The one extractor that exists:
- RulesExtractor: regex + keyword lists for Hindi, English and Hinglish. Deterministic, offline, explainable.
A Bedrock-backed extractor is specified against the same schema but not built (model access NOT_AUTHORIZED,
16 Oct 2026). ground() enforces the schema's rule either way: a field whose quoted span is not found verbatim
in the text is dropped, and no extractor ever sets the verdict.

Whatever the extractor, the text inside a notice is untrusted data. Nothing here interprets it as an instruction.

Matching runs on a normalised copy of the message (`normalize.normalise`: zero-width characters dropped,
confusables and leetspeak folded), never on the raw string, because a homoglyph message is the same message.
Spans are mapped straight back to the original text, so every quote the officer sees is the characters that are
really in the message. Nothing in this module may store a span in normalised coordinates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

from .models import (LAW_ENFORCEMENT, Channel, Claim, ClaimedOwner, DocumentIds, Grounded, Instruction, Issuer,
                     Payee, Span)
from .normalize import Normalised, normalise

# ---- a bank role is not a bank self-claim ------------------------------------------------------------------
# "branch manager" and "head office" used to sit bare in the BANK_SELF list. A CBI digital-arrest script that
# ends "do not inform the branch manager of the reason" therefore set claimed_issuer = BANK_SELF off that span,
# and the customer card for a CBI impersonation said "Demo Bank never asks you to break an FD" and named the
# bank three times as the claimed sender. Telling the customer to keep a bank officer out of it is the opposite
# of claiming to BE one.
#
# So a role or an office counts only inside a frame that says the message IS that person or comes FROM them,
# which is the test the rest of the BANK_SELF list already applies to "your bank" (a bare possessive, "your bank
# account", is how any routine message refers to the customer's own account and has never been a claim). The
# frames are the same shapes as the authority frames below, kept literal here because BANK_SELF is not anchored
# through `anchor_tier`: its patterns carry their own frame.
_BANK_ROLE = (r"(?:branch manager|bank manager|branch head|head office|regional office|zonal office"
              r"|shakha prabandhak|शाखा प्रबंधक|बैंक प्रबंधक|प्रधान कार्यालय)")
_BANK_ROLE_SELF = [
    rf"\b(?:this|that|it) is (?:the |your |our )?{_BANK_ROLE}\b",
    rf"\b(?:i ?am|i'?m|we are|we'?re) (?:the |your |our |from the |from your )?{_BANK_ROLE}\b",
    rf"\b(?:from|frm) (?:the |your |our )?{_BANK_ROLE}\b",
    rf"\b(?:main|mai|hum) (?:the |your |our )?{_BANK_ROLE}\b",
    rf"{_BANK_ROLE}\s*(?:here|speaking|calling|this side)\b",
    rf"{_BANK_ROLE}\s+(?:se|से)\s+[^.?!।\n]{{0,24}}?(?:bol|baat|call|बोल|बात|कॉल)",
]

# Keyword tables. Hindi in Devanagari and romanised Hinglish side by side. Order matters only where noted.
ISSUER_KEYWORDS: list[tuple[Issuer, list[str]]] = [
    (Issuer.ED, [r"enforcement directorate", r"directorate of enforcement", r"\bE\.?D\.?\b(?!\w)", r"प्रवर्तन निदेशालय", r"pravartan nideshalay"]),
    (Issuer.CBI, [r"\bC\.?B\.?I\.?\b", r"central bureau of investigation", r"सीबीआई", r"सी\.?बी\.?आई"]),
    (Issuer.RBI, [r"reserve bank of india", r"reserve bank", r"\bR\.?B\.?I\.?\b", r"रिज़र्व बैंक", r"रिजर्व बैंक", r"आरबीआई", r"\bgovernor\b"]),
    (Issuer.SEBI, [r"\bSEBI\b", r"सेबी"]),
    (Issuer.COURT, [r"supreme court", r"high court", r"सुप्रीम कोर्ट", r"उच्च न्यायालय", r"सर्वोच्च न्यायालय", r"\bcourt order\b", r"\bjudge\b", r"न्यायाधीश", r"\bcourt\b"]),
    (Issuer.CUSTOMS, [r"\bcustoms?\b", r"कस्टम", r"\bparcel\b.*\b(seized|contraband|drugs)\b"]),
    (Issuer.TRAI_DOT, [r"\bTRAI\b", r"\bDoT\b", r"department of telecom", r"ट्राई", r"telecom (department|authority)", r"\bsim\b.{0,20}\b(block|band|deactivat)"]),
    # The two bodies that send real money demands by message (a traffic challan, a property-tax bill). They sit IN
    # FRONT of POLICE on purpose: "Traffic Police" contains the POLICE token, and when both anchor at the same tier
    # in one phrase the earlier start wins (`select_issuer`), so the challan is read as the transport side's and
    # never as a police demand, which would put R-AGENCY-PAY's "no agency demands money" on a real challan. The
    # one POLICE form claimed here directly is "<city> Police e-Challan", the e-challan masthead.
    (Issuer.TRANSPORT, [r"traffic police", r"\btraffic (?:department|cell|branch|wing|control room)\b",
                        r"regional transport (?:office|authority)", r"transport (?:department|commissioner\w*)",
                        r"\bR\.?T\.?O\.?\b(?!\w)", r"\bparivahan\b", r"\bpolice\b(?=[^.;!?।\n]{0,24}\be-?\s?challan)",
                        r"यातायात पुलिस", r"ट्रैफ़?िक पुलिस", r"परिवहन (?:विभाग|कार्यालय)", r"आरटीओ"]),
    (Issuer.MUNICIPAL, [r"municipal corporation", r"\bmunicipal (?:council|committee|board)\b", r"\bmunicipality\b",
                        r"\bnagar (?:nigam|palika|parishad|panchayat)\b", r"नगर (?:निगम|पालिका|परिषद|पंचायत)",
                        r"\b(?:MCD|BBMP|GHMC|BMC)\b"]),
    (Issuer.POLICE, [r"\bpolice\b", r"पुलिस", r"cyber ?cell", r"crime branch", r"\binspector\b", r"\bइंस्पेक्टर\b", r"\bthana\b", r"\bFIR\b"]),
    # BANK_SELF only when the sender claims to BE the bank or its staff. A bare possessive ("your bank account",
    # "aapke bank statement") is how any routine message refers to the customer's own account, so it is not a claim,
    # and a stray "RM" token needs bank/branch/call context in the same sentence before it counts.
    (Issuer.BANK_SELF, [r"relationship manager", r"\bRM\b(?!\s+[A-Z][a-z])(?=[^.?!।\n]{0,60}\b(?:bank|branch|bol|call|phone)\w*)",
                        r"\b(?:bank|branch)\w*\b[^.?!।\n]{0,60}\bRM\b", r"\byour RM\b", r"from your bank",
                        r"this is your bank\b", r"your bank (?:se bol|bol (?:raha|rahi)|is calling|calling|speaking)",
                        r"aapk[ae] bank se (?:bol|baat|call|hain)", r"aapk[ae] bank (?:ki taraf|ki or)",
                        r"आपक[ाे] बैंक से (?:बोल|बात|कॉल)", r"आपक[ाे] बैंक (?:की ओर|की तरफ)",
                        r"\bbank (ki|se) (taraf|or)", r"bank ki taraf se", r"account.{0,30}(compromis|hack|block|freeze)",
                        r"खाता.{0,30}(बंद|ब्लॉक|हैक)", *_BANK_ROLE_SELF]),
]

# ---- the euphemism family for TRANSFER_TO_ACCOUNT ----------------------------------------------------------
# A digital-arrest script rarely says "transfer". It says "park your entire liquid holdings in the designated
# verification account". One euphemism used to zero the whole chain, so the verb list is wide. Every verb is
# bounded two ways, because this repo has twice shipped a pattern that matched inside an unrelated word ("kr"
# inside "shukriya", "invest" inside "investigation") and a false positive here puts money wording on a benign
# customer card:
#   1. no letter may touch the verb on either side, so "remove" is not "move" and "workplace" is not "place";
#   2. the verb only counts when a money word AND a destination word sit beside it in the same sentence, within
#      _GAP on each hop. "Park the car in the visitor bay" has neither, so it is not read as an instruction.
# Past tense is deliberately out of the list: "your salary was deposited in your account" is a report of a
# credit, not an instruction, and it carries both context words.
# Same sentence, and across a line break only on the repo's existing OCR-wrap condition: the next line must start
# lowercase or with a digit (_WS_BRIDGE's rule), so a header line ("Account: ...") still cannot pair up with an
# unrelated verb below it. Excluding \n outright made the whole euphemism family die on a wrapped paste — a PDF, an
# OCR'd notice and a WhatsApp forward all arrive wrapped, which is most of what the officer actually sees.
_GAP_CH = r"[^.;!?।\n\r  ]"
_GAP = rf"(?:{_GAP_CH}|\n(?:[\x20\t]*\n)?[\x20\t]*(?=(?-i:[a-z0-9])))" + r"{0,60}?"
_MONEY = (r"(?:₹|(?<![a-z])(?:rs\.?|inr|rupees?|lakhs?|lac|crores?|cr|amount|funds?|money|cash|balance"
          r"|holdings?|savings?|pais[ae]|poora|pura|sara|entire|liquid|rupa?y[ae]?|rupaiye|rupiya|hazaa?r)(?![a-z])"
          r"|पैस[ेा]|राशि|रकम|रुपय|पूरा|सारा|हज़?ार|लाख)")
# "akount" / "acount": the variant corpus is deliberately misspelt, because a WhatsApp forward is.
_DEST = (r"(?:(?<![a-z])(?:a[ckq]{1,2}[ao]?u?nts?|a/?c|acct|wallet|khaat[aey]|khat[aey]|upi|vpa|beneficiary|payee|ifsc)(?![a-z])"
         r"|खात|वॉलेट|यूपीआई)")
# "wire" is the one verb in this family that is also a common NOUN, and the noun runs the other way: "the
# incoming wire of Rs 4,20,000 has been credited to this account" is an inward-remittance advice carrying a money
# word, a pointed destination and the word itself. A determiner or an arrival adjective in front of it makes it a
# noun, so those occurrences are not the verb. ("wire transfer" is unaffected either way: bare `transfer` already
# reads as TRANSFER_TO_ACCOUNT in English and is not part of this family.)
_WIRE = (r"(?<!\bthe )(?<!\ba )(?<!\ban )(?<!\bone )(?<!\bthis )(?<!\bthat )(?<!incoming )(?<!inward )"
         r"(?<!outward )(?<!loose )(?<!same )wires?")
# "push" was in this list for one pass and came out again on 19 Oct; see _DROPPED_ORDER_FORMS below.
_PUSH_VERB = r"(?:pushe?s?|pushing|push kar\w{0,3})"
_MOVE_VERB = (r"(?<![\w])(?:park|parks|parking|place|places|placing|move|moves|moving|shifts?|shifting"
              r"|deposits?|depositing|remits?|remitting|route|routes|routing|consolidates?|consolidating"
              rf"|{_WIRE}|wire kar\w{{0,3}}"
              r"|tra?nsfe?rs?|tra?nsfe?rring|tra?nsfe?r kar\w{0,3}|bhej\w{0,3}|daal\w{0,2}|dalo|jama ?kar\w{0,3}"
              # "pay Rs 2,00,000 to account ...", "payment karo is account me", "bharo", "भुगतान करें": the plainest
              # demand an agency script makes, and it was not in the family, so CBI and customs demands worded
              # with "pay" came out GREY. Still behind the money + pointed-destination gate like every verb here.
              r"|pay|pays|paying|make\s+(?:a\s+|the\s+)?payment|payment\s+kar\w{0,3}|bhar(?:o|na|en|ein|iye|do|dein)?"
              r"|भुगतान\s?कर\w{0,3}|भर(?:ें|ो|िए|\s?दें|\s?दो)(?![ऀ-ॿ])"
              r"|भेज\w{0,3}|डाल\w{0,3}|जमा ?कर\w{0,3}|ट्रांसफ़?र\w{0,3})(?![a-z])")
# The euphemism family needs the destination to be POINTED AT, not merely mentioned. "You can move funds between
# your own accounts in the app" and "please move the balance out first" carry a money word and the word "account"
# and are ordinary bank sentences; a scam names the account it wants the money in — this one, that one, the
# designated / verification / escrow one, or a literal account number. Bare "transfer" is unaffected: in English it
# is a banking verb on its own, and it is not part of this family.
# Two ways a scam points at the account it wants: a determiner ("this", "the designated"), or the authority it
# claims the account belongs to ("the RBI account", "court registry akount", "आरबीआई के खाते"). The second is the
# dominant Indian phrasing and the variant corpus is full of it. A benign bank sentence names neither: it says
# "your own accounts", "my account", "the new account at our branch".
_POINTER = (r"(?:(?<![a-z])(?:this|that|these|those|designated|verification|clearance|settlement|nodal|custody"
            r"|monitoring|supervision|escrow|following|above|below|mentioned|given|is"
            r"|rbi|reserve bank|court|registry|govt|government|treasury|ed|cbi|customs|agency|official)(?![a-z])"
            r"|इस|उस|नीचे|दिए|आरबीआई|रिज़र्व|कोर्ट|न्यायालय|रजिस्ट्री|सरकार|एजेंसी|आधिकारिक)")
_ACCT_DIGITS = r"\d[\d\s-]{8,}"
_NEAR = r"[^.;!?।\n\r]{0,24}?"
_DEST_POINTED = rf"(?:{_POINTER}{_NEAR}{_DEST}|{_DEST}{_NEAR}{_ACCT_DIGITS})"
_BOTH_CTX = rf"(?:{_MONEY}{_GAP}{_DEST_POINTED}|{_DEST_POINTED}{_GAP}{_MONEY})"

# ---- one phrase verb that carries its own destination -------------------------------------------------------
# "Credit this account with Rs 6,50,000" and "arrange the settlement of Rs 6,50,000 in the clearance account" are
# both ways a forged notice words a demand without using a verb this family holds. Neither can join _MOVE_VERB:
#   - the bare verb "credit" is unusable, because "we will credit the balance to this account on Monday" is an
#     ordinary bank sentence with a money word, a pointed destination and the verb. Pass 5 paid for exactly this
#     mistake one register up, so "credit" only reads as the PHRASE, where the money arrives on "with", which is
#     how an order is worded; a credit TO the customer is worded "credit <X> to your account".
#   - "arrange" bare is broader still ("please arrange for the funds to be available in this account by Friday"),
#     so it only reads in front of "settlement of".
# Both also need the clause to be an ORDER rather than a report. "We will arrange the settlement of Rs 4,20,000
# of your matured deposit into this account" carries every other gate; what separates it from "Arrange the
# settlement of Rs 6,50,000 in the clearance account today" is that the second has no subject in front of the
# verb. So these two read only at the head of a clause, or behind a second-person obligation frame. That gate was
# not enough for the credit phrase and it came out again the same day; only the settlement phrase is live.
_ORDER_HEAD = (r"(?:(?:^|(?<=[.;!?।\n\r]))[\x20\t]*"
               r"|\b(?:please|kindly|must|immediately|now|today|then|hereby|aapko|आपको|कृपया"
               r"|you\s+(?:must|should|shall|have\s+to|need\s+to"
               r"|are\s+(?:hereby\s+)?(?:required|directed|instructed|advised|requested)\s+to))\s+)")
_CREDIT_DEMAND = rf"(?<![\w])credits?(?![a-z])\s+{_POINTER}{_NEAR}{_DEST}{_NEAR}\bwith\b"
_SETTLE_DEMAND = (r"(?<![\w])arrange(?:s|d)?(?![a-z])\s+(?:the\s+|for\s+the\s+)?"
                  r"(?:immediate\s+|full\s+|complete\s+|final\s+){0,2}settlement\s+of\b")

# ---- the two forms this pass added and then withdrew -------------------------------------------------------
# `_ORDER_HEAD` discriminates "order" from "report", which is what its two probes were written against ("we will
# credit this account with...", "the app will push a notification..."). It does not discriminate scam from
# benign, and a bank's own recovery letter is a polite ORDER:
#     "Demo Bank Loan Recovery Cell: Kindly credit this account with Rs 2,50,000 before 30 November."
#     "Demo Bank: You must push Rs 12,000 into the designated EMI collection account 50100234567891."
# Both read as TRANSFER_TO_ACCOUNT, and on a message that claims to be the bank that is RED by construction
# (R-BANK-NEVER-MOVE-FD is BANK_SELF + TRANSFER_TO_ACCOUNT with no further condition, and R-BANK-SELF is hard on
# every outbound-log miss), so the card said "Please stop. Do not send this money now" on a bank's own letter.
#
# Neither form is separable from its benign twin BY FORM: "Credit this account with Rs 6,50,000 before 4 pm" and
# the recovery letter above are the same sentence with a different sender. So both came out again, and the
# demands they used to read now fall back on whatever else the message says. This is a narrower engine on
# purpose, and `tests/test_euphemism_bounds.py::DROPPED_19_OCT` pins the trade in both directions so a later
# pass cannot re-add either form without meeting the benign twin.
#
# Not a general fix, and this comment is the honest statement of that: the pre-existing verbs do the same thing
# on the same letter ("Kindly deposit Rs 2,50,000 in this loan account", "Kindly transfer ... to account
# 3001122334455" were RED before this pass and are RED today). What closes the class is the structure named
# above, not the verb list; `tests/test_bank_order_is_not_a_demand.py` holds that as a strict xfail.
# The two family members as they were written, kept only so the test can show each one matching the benign bank
# order that took it out. Nothing in the engine reads them; `MOVE_EUPHEMISM` below is the family.
_DROPPED_ORDER_FORMS = (
    rf"(?<![\w]){_PUSH_VERB}(?![a-z]){_GAP}{_BOTH_CTX}",
    rf"{_ORDER_HEAD}{_CREDIT_DEMAND}{_GAP}{_MONEY}",
)

MOVE_EUPHEMISM = [
    rf"{_MOVE_VERB}{_GAP}{_BOTH_CTX}",                      # "park your Rs 38,00,000 in the verification account"
    rf"{_BOTH_CTX}{_GAP}{_MOVE_VERB}",                      # "10 lakh court registry akount me deposit karo"
    # these two take the pointed destination as well, or "To close your account, please move the balance out
    # first" reads as an instruction to pay someone
    rf"{_MONEY}{_GAP}{_MOVE_VERB}{_GAP}{_DEST_POINTED}",    # "poora paisa daal do is account me"
    rf"{_DEST_POINTED}{_GAP}{_MOVE_VERB}{_GAP}{_MONEY}",    # "is account me bhej dein pura paisa"
    # "You are directed to arrange the settlement of Rs 6,50,000 in the designated clearance account."
    rf"{_ORDER_HEAD}{_SETTLE_DEMAND}{_GAP}{_BOTH_CTX}",
]

# ---- the same family in the passive and obligation register ------------------------------------------------
# A forged legal notice is not written in the imperative. It says "The sum of Rs 38,00,000 is required to be
# remitted to the account specified herein", never "you must transfer Rs 38,00,000". The ACTIVE control of that
# exact sentence already reads as TRANSFER_TO_ACCOUNT, so the register was the only thing between the two, and a
# judge got a GREY out of that gap on 18 Oct. This block is the same family read in the passive: same verbs,
# same money word, same POINTED destination, same gap rule. Nothing here loosens any of those three gates.
#
# The frame must carry OBLIGATION or compulsion, never a completed or merely announced action. "Your salary was
# deposited in your account", "Rs 2,000 has been credited to the account mentioned above" and "the amount will be
# transferred on Monday" all carry a money word, a destination and a past participle, and all three are a bank
# telling a customer about money that is arriving. So a bare passive ("was / has been / will be <verb>ed") is
# deliberately NOT a frame here; only "is/are (hereby) required|directed|... to be", "is/are/stands/has/needs to
# be" and "shall|must|should|ought to be" are. "may be" is out for the same reason: it offers, it does not compel.
_OBLIG = (r"(?:(?:is|are|was|were)\s+(?:hereby\s+)?"
          r"(?:required|directed|instructed|advised|requested|mandated|obliged|obligated|liable|bound"
          r"|called\s+upon)\s+to\s+be"
          r"|(?:is|are|stands?|has|have|needs?)\s+to\s+be"
          r"|(?:shall|must|should|ought\s+to|will\s+have\s+to)\s+be)\s+")
# The past participles of the verbs the active family already carries, and only those: the point is parity with
# the active control, not a wider verb list. "credited", "paid" and "made" are the three a reader would expect
# here and all three are deliberately out, because "the sum is to be credited to the account mentioned above" is
# a bank saying money is coming TO the customer and "payment may be made at any branch counter" is a counter
# notice. Both carry the money word, the destination and the frame, and both must stay silent.
_MOVED = (r"(?<![\w])(?:tra?nsfe?rred|remitted|remmitted|deposited|moved|shifted|placed|parked|routed"
          r"|consolidated)(?![a-z])")
# Hindi and Hinglish do not inflect the verb for obligation: "jama karna hoga", "भेजनी होगी" and "transfer karna
# padega" all keep the stem, and _MOVE_VERB already reads every one of them (checked, not assumed). The one form
# it cannot read is the true passive participle, where कर becomes किया: "राशि इस खाते में जमा की जानी है",
# "paisa is account me jama kiya jana hai". The "जाना / jana" auxiliary is required, which is what keeps this off
# a plain "jama kiya" (a deposit that has already happened).
_MOVED_HI = (r"(?:जमा|ट्रांसफ़?र|jama|tra?nsfe?r)\s*(?:क(?:ि(?:या|ये|ए)|ी|े)|k[iy](?:ya|ye|e)?)\s*"
             r"(?:जान[ाीे]|jaa?n[aiey])\w{0,3}")
_PASSIVE_VERB = rf"(?:{_OBLIG}{_MOVED}|{_MOVED_HI})"
# A notice points at the account from the other side as well, in the register a notice is written in: "remitted
# to the account specified herein", "deposited in the account mentioned below". Three things are required
# together, and each one was put there by a false positive this pass produced and measured:
#   - the participle AND a word that points at THIS document. "The account specified in your application" and
#     "the account given at onboarding" are the customer's own account;
#   - a destination preposition in front of it. Without that, "the balance is required to be moved OUT OF the
#     account mentioned above" and "funds BETWEEN the accounts mentioned above" read as demands - the same
#     words, the opposite direction, and ordinary bank wording;
#   - and it is used only here, in the passive family. Folded into the shared _DEST_POINTED it re-opened the
#     exact hole the pass-3 gate closed: "To close the account mentioned above, please move the balance out
#     first" came back as an instruction to pay. The active family does not need it and does not get it.
_POINTER_POST = (r"(?:specified|mentioned|indicated|stated|noted|detailed|shown|furnished|set out)\s+"
                 r"(?:here\s?in|hereunder|hereinbelow|below|above)(?![a-z])")
_DEST_NOTICE = rf"(?:{_DEST_POINTED}|(?:to|into|in)\s+(?:the\s+)?{_DEST}{_NEAR}{_POINTER_POST})"
# Two orders, not the four the active family needs. A passive clause puts its subject in front of its verb in
# English ("the sum ... is required to be remitted to the account specified herein") and its verb at the end in
# Hindi ("इस खाते में पूरी रकम जमा की जानी है"), so those are the two orders that occur. The other two were
# written, measured and deleted: no probe in this repo reached them, they cost 4 ms each on an 11 kB message,
# and an unused alternative is false-positive surface with nothing on the other side of the trade.
# The passive is blind to direction, and the benign half of this register is money moving TO the customer: a
# matured FD, a refund, salary, interest, a reversal. The pass-5 gate paid the bill for that — "the maturity
# amount of Rs 4,20,000 is required to be remitted to the account specified herein" came back as an instruction
# to pay, the bank's own letter reached RED, and the customer card told her to stop her own money. The verb
# lexeme cannot separate direction ("credited" is excluded, "remitted" is not, and both run both ways), so the
# gate is the money itself: when the sentence names the money as something arriving, the passive does not read.
# This is a suppressor on the passive family only; the active family is untouched and so are the scenarios.
_CREDIT_TO_CUSTOMER = (r"(?<![a-z])(?:matur\w*|refunds?|refunded|proceeds|salary|wages|pension|interest|dividend"
                       r"|reversal|reversed|cashback|claim settlement|settlement amount|disburs\w*|credited to you)"
                       r"(?![a-z])"
                       r"|परिपक्व\w*|रिफ़?ंड|वापसी|वेतन|पेंशन|ब्याज|लाभांश")
RE_CREDIT_TO_CUSTOMER = re.compile(_CREDIT_TO_CUSTOMER, re.I)

MOVE_PASSIVE = [
    # "The sum of Rs 38,00,000 is required to be remitted to the account specified herein"
    rf"{_MONEY}{_GAP}{_PASSIVE_VERB}{_GAP}{_DEST_NOTICE}",
    # "इस खाते में पूरी रकम जमा की जानी है" / "pura paisa is account me jama kiya jana hai"
    rf"{_BOTH_CTX}{_GAP}{_PASSIVE_VERB}",
]

# ---- a government due: a traffic challan or a local tax ------------------------------------------------------
# Both are demands the body really does send by message, so they are read as what they are and never folded into
# "a transfer to an account". A copied challan or tax notice is a real message with only its payment details
# swapped, and the rules that read these instructions (R-CHALLAN-OFFICIAL, R-PAYEE-NOT-SENDER, R-DOMAIN-GOVIN,
# R-RECEIVER-NAME) are all about WHERE the payment is made, which is the one thing the copy changes.
#
# They sit in front of PAY_FEE_TO_VERIFY, whose "pay ... to clear" form would otherwise read "pay Rs 500 to clear
# your pending challan" as a release fee. Every form needs the due word AND a payment or a due-state word in the
# same sentence; the one cross-sentence form needs a specific challan (a number, or "issued"/"generated") and a
# "pay" within 300 characters, which is how a challan SMS is written ("Challan No. DL123 issued ... Pay within 7
# days") and not how an awareness message is ("beware of e-challan messages; pay only on the official site").
# Bare "challan" is also a bank deposit slip and an income-tax form, so PAY_CHALLAN additionally needs a vehicle or
# traffic word somewhere in the message (RE_VEHICLE, applied in `extract`).
#
# A traffic FINE is the same demand without the word "challan" ("pay your vehicle driving fine, you passed a red
# light"), and two of Bhawna's test messages on 23 Oct were read as nothing at all for that reason. The fine forms
# need a pay word in the same sentence and sit behind the same vehicle gate, so "pay a fine to avoid arrest" with no
# vehicle in it is read exactly as before; a police fine that does threaten arrest keeps R-AGENCY-PAY (rules.py).
# Never inside a web address: "pay only on echallan.parivahan.gov.in" is an awareness line naming the official
# site, and reading "echallan" out of the domain turned it into a demand to pay.
_CHALLAN = r"(?<![\w./-])(?:e-?\s?challans?|challans?|ई-?\s?चालान|चालान)(?!\.[a-z]|/)"
_LOCAL_TAX = (r"(?:(?:property|house|home|water|municipal|holding)\s?tax(?:es)?"
              r"|(?:संपत्ति|गृह|हाउस|प्रॉपर्टी|प्रोपर्टी|जल)\s?(?:कर|टैक्स)|(?:ghar|makaan|makan)\s?(?:ka\s)?tax)")
_DUE_PAY = r"(?:pay|paying|clear|settle|deposit)"
_DUE_STATE = r"(?:pending|unpaid|overdue|outstanding|due|payable)"
_DUE_PAY_HI = r"(?:भर|जमा|भुगतान|बकाया|लंबित|bhar\w{0,3}|bharo|jama)"
_SAME_SENT = r"[^.;!?।\n]"
# Singular only. "Pay traffic fines only on echallan.parivahan.gov.in" is advice about fines in general (a bank's
# awareness SMS says exactly that) and the plural read it as a demand; a demand names ONE fine ("pay your fine", "a
# fine for 500000"). "fine print" is not a fine. The Devanagari word sits outside the \b pair, because a word that
# ends in a vowel sign has no \b after it.
_FINE = r"(?:\b(?:fine(?!\s+print)|penalty|jurmana)\b|जुर्माना)"
PAY_CHALLAN_PATTERNS = [
    rf"\b{_DUE_PAY}\b{_SAME_SENT}{{0,40}}?{_CHALLAN}",              # "pay your pending e-challan"
    rf"{_CHALLAN}{_SAME_SENT}{{0,60}}?\b{_DUE_STATE}\b",              # "your challan of Rs 500 is pending"
    rf"\b{_DUE_STATE}\b{_SAME_SENT}{{0,30}}?{_CHALLAN}",              # "an unpaid traffic challan"
    rf"{_CHALLAN}{_SAME_SENT}{{0,40}}?{_DUE_PAY_HI}",                 # "चालान ... भरें" / "challan jama karein"
    rf"(?:भर|जमा|भुगतान){_SAME_SENT}{{0,40}}?{_CHALLAN}",              # "भुगतान ... चालान"
    rf"{_CHALLAN}\s*(?:no\.?|number|#|id)(?![a-z])(?=[\s\S]{{0,300}}?\bpay(?:ment)?\b)",   # "Challan No. DL123 ... Pay"
    rf"{_CHALLAN}{_SAME_SENT}{{0,30}}?\b(?:issued|generated|raised)\b(?=[\s\S]{{0,300}}?\bpay(?:ment)?\b)",
    rf"\b{_DUE_PAY}\b{_SAME_SENT}{{0,40}}?{_FINE}",                 # "pay your vehicle driving fine"
    rf"{_FINE}{_SAME_SENT}{{0,60}}?\bpay(?:ment)?\b",               # "charged a fine for 500000, pay at ..."
    rf"जुर्माना{_SAME_SENT}{{0,40}}?(?:भर|जमा|भुगतान)",              # "जुर्माना ... भरें"
    rf"(?:भर|जमा|भुगतान){_SAME_SENT}{{0,40}}?जुर्माना",
]
PAY_LOCAL_TAX_PATTERNS = [
    rf"\b{_DUE_PAY}\b{_SAME_SENT}{{0,40}}?{_LOCAL_TAX}",            # "Pay your house tax of Rs 12,500"
    rf"{_LOCAL_TAX}{_SAME_SENT}{{0,60}}?\b{_DUE_STATE}\b",            # "property tax for 2026-27 is overdue"
    rf"\b{_DUE_STATE}\b{_SAME_SENT}{{0,30}}?{_LOCAL_TAX}",            # "outstanding property tax"
    rf"{_LOCAL_TAX}{_SAME_SENT}{{0,40}}?{_DUE_PAY_HI}",               # "संपत्ति कर ... जमा करें"
    rf"(?:भर|जमा|भुगतान){_SAME_SENT}{{0,40}}?{_LOCAL_TAX}",
]
# A traffic word, anywhere in the message. Gates PAY_CHALLAN only (see above).
RE_VEHICLE = re.compile(r"\b(?:vehicles?|car|bike|scooter|two-?wheeler|motorcycle|gaadi|gadi|traffic|rto|parivahan"
                        r"|e-?\s?challan|overspeed\w*|helmet|red light|signal jump\w*|parking|driving licen[cs]e"
                        r"|registration (?:no|number))\b|वाहन|गाड़ी|गाडी|यातायात|ट्रैफ़?िक|परिवहन|ई-?\s?चालान", re.I)

INSTRUCTION_KEYWORDS: list[tuple[Instruction, list[str]]] = [
    (Instruction.RETURN_EXCESS_CREDIT, [r"(credited|transferred|sen[dt]|bheja?).{0,40}(by mistake|mistakenly|galti se|accidentally)", r"accidentally (sent|transferred|credited)", r"galti se.{0,40}(credit|bhej|transfer)", r"गलती से.{0,40}(जमा|भेज|क्रेडिट)", r"return the (excess|extra|amount)", r"(refund|wapas|वापस).{0,30}(bhej|\bkar\w{0,3}\b|\bkr\b|करें|भेज)", r"paise wapas"]),
    (Instruction.PAY_CHALLAN, PAY_CHALLAN_PATTERNS),
    (Instruction.PAY_LOCAL_TAX, PAY_LOCAL_TAX_PATTERNS),
    # "invest" needs its ending: unbounded, it read "the investigation is confidential" as an investment pitch
    # and the customer card then told a frightened customer, in Hindi, that she was being asked to invest.
    (Instruction.INVEST_FOR_RETURNS, [r"\binvest(?:s|ed|ing|ment|ments)?\b", r"निवेश", r"\breturns?\b", r"रिटर्न", r"\bprofit\b", r"मुनाफ़?ा", r"\b\d+\s?x\b", r"guaranteed", r"गारंटी", r"double (your|the) money", r"trading (account|platform|desk)"]),
    # "tod" (break) must be its own word: unbounded it matched "today", so "your fixed deposit matures today"
    # read as an instruction to break the FD.
    (Instruction.MOVE_FD, [r"(break|close|\btod(?:o|na|kar|wa|wao)?\b|तोड़|तुड़वा|liquidate|premature(ly)?).{0,25}(FDs?|fixed deposits?|deposits?|एफ\.?डी)", r"(FDs?|fixed deposits?|एफ\.?डी).{0,25}(\btod(?:o|na|kar|wa|wao)?\b|break|close|liquidat|तोड़|तुड़वा|\bband\b)", r"safe account", r"सुरक्षित खात", r"suraksh?it (khat|account)", r"(your (savings?|money|funds?)|poora paisa|sara paisa|paisa|पैसा|राशि|savings).{0,25}(move|shift|transfer|भेज|bhej)"]),
    (Instruction.PAY_FEE_TO_VERIFY, [r"(verification|processing|clearance|release|security) (fee|charge|deposit)", r"(fee|shulk|शुल्क).{0,30}(verify|verification|सत्यापन)", r"pay.{0,30}to (verify|release|clear)", r"सत्यापन शुल्क"]),
    # The bare verbs here are the ones that mean money on their own. "deposit", "जमा कर", "bhej do" and
    # "ट्रांसफर" used to sit in this list bare, which read "collect your deposit slip", "फॉर्म जमा करें",
    # "फोटो भेज दो" and "फ़ाइल दूसरी शाखा में ट्रांसफ़र हो गई" as payment instructions; they now live in
    # MOVE_EUPHEMISM, which needs the money and the destination too. English "transfer" stays bare because in
    # English it is a banking word; the Devanagari loanword is used for a job or a file just as often.
    (Instruction.TRANSFER_TO_ACCOUNT, [r"\btra?nsfe?r\b", r"\bRTGS\b", r"\bNEFT\b", r"\bIMPS\b", r"\bUPI\b.{0,20}(pay|send|bhej)", r"\bsend\b.{0,30}(amount|money|rs|₹|paise)", r"(amount|money|paise|राशि).{0,30}(send|bhej|भेज)", *MOVE_EUPHEMISM, *MOVE_PASSIVE]),
]

# A phrase may continue past a line break only when the next line starts lowercase (or a digit): that is how OCR
# wraps a phrase mid-sentence ("RBI\nsupervision account"; tesseract sometimes emits a blank line, so up to two
# newlines). A new line starting uppercase is a header or a new sentence ("Reserve Bank of India\nAccount holder
# notice"), and bridging it manufactured a claimed_owner the customer was never told about. (?-i:...) keeps the
# guard case-sensitive under the re.I search.
_WS_BRIDGE = r"(?:[\x20\t]+|[\x20\t]*\n(?:[\x20\t]*\n)?[\x20\t]*(?=(?-i:[a-z0-9])))"   # \x20 = space, kept out of _ws()'s replace


def _ws(pattern: str) -> str:
    """OCR output breaks lines mid-phrase, so in a phrase pattern a literal space matches same-line whitespace or
    one guarded newline (see _WS_BRIDGE). The match runs on the original text, so the stored span quotes it
    verbatim, newline included, and ground() keeps the field. Only safe where no space sits in a char class."""
    return pattern.replace(" ?", _WS_BRIDGE + "?").replace(" ", _WS_BRIDGE)


# Owner phrases are the one table whose match REQUIRES a multi-word phrase to hold together, and OCR'd notices flow
# through it, so its spaces are whitespace-tolerant. Issuer/instruction tables keep plain spaces: their multi-word
# phrases have single-token fallbacks (ED, RBI, \btransfer\b), and widening them would only add false positives.
#
# The filler between the institution and "account" is an allow-list, not ( \w+): only words that actually appear in
# scam phrasings ("RBI supervision account", "RBI ke account") plus the ('s) possessive may bridge. A bare ( \w+)
# window once read "RBI guidelines on account closure" as an RBI-owned account; prepositions (on/of/for/about) and
# other generic words never qualify, so a non-possessive, non-attributive mention stays UNKNOWN.
_OWNER_FILLER = (r"(?:ke|ka|ki|supervision|verification|investment|investigation|monitoring|safe|secure|nodal|suspense"
                 r"|special|escrow|settlement|registry|custody|refund|deposit|holding|seizure|clearance|probe|audit"
                 r"|relief|suraksha)")
OWNER_KEYWORDS: list[tuple[ClaimedOwner, list[str]]] = [
    (owner, [_ws(p) for p in pats]) for owner, pats in [
        (ClaimedOwner.RBI, [rf"\bRBI('s)?( {_OWNER_FILLER}){{0,2}} account", rf"reserve bank('s)?( {_OWNER_FILLER}){{0,3}} account", r"आरबीआई.{0,15}खात", r"RBI (ke |ka )?khat"]),
        (ClaimedOwner.COURT, [rf"court('s)?( {_OWNER_FILLER}){{0,2}} account", r"न्यायालय.{0,15}खात", r"registry account"]),
        (ClaimedOwner.AGENCY, [rf"\b(CBI|ED|police|customs|enforcement directorate|cyber ?cell)\b('s)?( {_OWNER_FILLER}){{0,2}} account", r"(सीबीआई|पुलिस).{0,15}खात", r"escrow account"]),
        (ClaimedOwner.GOVT, [rf"(government|govt|sarkari)('s)?( {_OWNER_FILLER}){{0,2}} account", r"सरकारी खात", r"treasury account", r"national (security |verification )?account"]),
        # BANK keeps ( \w+): its window ends at a mandatory specific noun (suspense/nodal/...), not at bare "account".
        (ClaimedOwner.BANK, [r"bank('s)?( \w+){0,2} (suspense|nodal|safe|secure|own) account", r"बैंक.{0,10}(सुरक्षित|नोडल) खात"]),
    ]
]

# ---- anchoring: when does NAMING an authority amount to CLAIMING to be it? ---------------------------------
# A hackathon judge downgraded a textbook digital-arrest script by prefixing a fake tool-output blob that merely
# contained the word "RBI". claimed_issuer used to be whichever authority token matched FIRST, so the claim
# became RBI, R-AGENCY-PAY (law enforcement demanding money) never fired, and a RED-class CBI script scored
# GREY. Worse, the officer's band then said the message "claims to be from RBI" when it claims to be from CBI.
# Every span was verbatim and real, which is exactly what made it dangerous: the attacker chose the span.
#
# So a bare mention is no longer a claim of identity. An authority token counts only when the text around it is
# a frame that claims that identity, attributes the message to it, or names it as the owner of the payee
# account, in three tiers:
#
#   TIER_CLAIM   (3) the message says it IS or SPEAKS FOR the body: "from X", "This is X", "I am an officer of
#                    X", "on behalf of X", "X Cyber Cell", "X, Government of India", "by order of X",
#                    "X ka order", "X ki nayi scheme", "X notice", "X se bol raha hoon", "X says".
#   TIER_NAME    (2) the body's full institutional name stands on its own ("DIRECTORATE OF ENFORCEMENT.",
#                    "The Reserve Bank of India cautions the public"). Spelling a body's name out in full is how
#                    a letterhead works; an acronym on its own never reaches this tier.
#   TIER_ACCOUNT (1) the body is named beside the payee account ("the RBI supervision account", "RBI acct",
#                    "आरबीआई की विशेष निगरानी में आपका खाता"). This is a claim about the MONEY, not about the
#                    sender, so it ranks below both of the above: in S3 the notice is from ED and the account is
#                    said to be RBI's, and the issuer is ED.
#
# None of this is unforgeable - the attacker owns the text. The point is that forging it now requires the
# message to state, in words a reader can see, that it is from RBI. At that point "claims to be from RBI" is a
# TRUE sentence about the message, and if the message also claims to be CBI we say so instead of picking one
# silently (see select_issuer).
TIER_NONE, TIER_ACCOUNT, TIER_NAME, TIER_CLAIM = 0, 1, 2, 3

AUTHORITY_ISSUERS = (Issuer.ED, Issuer.CBI, Issuer.POLICE, Issuer.COURT, Issuer.RBI, Issuer.SEBI,
                     Issuer.CUSTOMS, Issuer.TRAI_DOT, Issuer.TRANSPORT, Issuer.MUNICIPAL)
# BANK_SELF is not an authority persona and is not anchored here: its own patterns already carry the frame
# ("from your bank", "this is your bank", "aapke bank se bol"), which is why a bare possessive never matched.
BANK_SELF_PATTERNS = next(pats for issuer, pats in ISSUER_KEYWORDS if issuer is Issuer.BANK_SELF)

_THE = r"(?:the\s+)?"
_POSS = r"(?:(?:ka|ke|ki|का|के|की)\s+)?"
# Up to two filler words may sit between the body and the noun that attributes the message to it ("RBI ki NAYI
# GOLD scheme", "Court REGISTRY instruction"). Function words may not: without this guard, "RBI " prefixed to
# "By order of the Supreme Court" read "By order" as RBI's order, which is the same hole one layer down.
_STOPWORD = (r"by|for|under|as|per|to|of|on|in|at|with|from|and|or|the|a|an|is|are|was|were|will|shall|please"
             r"|kindly|your|our|this|that|if|then")
_FILL = rf"(?:(?!(?:{_STOPWORD})\b)[\w'-]+\s+){{0,2}}"
# Separators a letterhead uses between the body and the next word. Sentence-ending punctuation is deliberately
# excluded: "verified by RBI. Notice: ..." must not read as an RBI notice.
_SEP = r"(?:'s)?[\s,:;–—-]{0,3}"

# Reported speech is not the message's own claim. A bank's genuine anti-fraud SMS says "fraudsters claiming to be
# from CBI are calling customers"; without this the "from" frame anchored CBI and the customer card told her the
# bank's own warning claimed to be the CBI. Python needs one fixed-width lookbehind per phrase.
_NOT_REPORTED = (r"(?<!claiming to be )(?<!pretending to be )(?<!posing as )(?<!impersonating )"
                 r"(?<!purporting to be )(?<!pose as )(?<!claim to be )(?<!said to be )")

# ---- a rank and a personal name may sit between the opener and the body -------------------------------------
# "This is Inspector R. Mehra, CBI Cyber Crime Branch, New Delhi" is how a digital-arrest call actually opens,
# and the self-claim frames could not see past the rank and the name: `(?:this|that|it) is (?:the )?$` has to end
# exactly where the token begins, so the CBI in that sentence reached a self-claim frame only by accident of its
# unit name. "This is Inspector R. Mehra, CBI." — the same opener with no unit noun — anchored nothing at all.
#
# The bridge is deliberately narrow, because its loose form ("this is <anything> the $") would read "This is a
# copy of the letter my cousin sent, who said the CBI visited him" as a CBI claim. Three things are required:
#   - a RANK word straight after the opener. A rank is how a caller introduces himself; it is not prose.
#   - a personal name, at most four tokens, each starting with a capital letter (so lowercase prose cannot pass).
#     It is optional: "This is the Inspector, CBI Cyber Cell" is the same claim with the name left out.
#   - a comma, colon or dash in front of the body. A letterhead and a spoken opener both use one, and requiring
#     it is what stops the bridge crossing a clause or a sentence boundary.
_RANK = (r"(?:inspector|sub-?inspector|dy\.?\s?inspector|insp\.?|asi|a\.s\.i\.?|si|s\.i\.?|sho|s\.h\.o\.?"
         r"|investigating\s+officer|io|officer|official|agent|constable|head\s+constable|superintendent"
         r"|commissioner|dy\.?\s?sp|dsp|sp|acp|dcp|ig|dig|adg|dgp"
         r"|deputy\s+director|joint\s+director|assistant\s+director|director|advocate|adhikari"
         r"|इंस्पेक्टर|निरीक्षक|अधिकारी|अफ़?सर|उपनिरीक्षक|आयुक्त)")
_PERSON = r"(?:(?-i:[A-Z])[\w'’]*\.?[\x20\t]*){1,4}"
_RANK_NAME = rf"{_RANK}\b\.?[\x20\t]*(?:{_PERSON})?[,:—–-][\x20\t]*"

_PLACE = r"(?:(?-i:[A-Z])[a-z]+[\x20\t]+){1,2}"

# Each left frame is matched so that it ENDS where the authority token begins.
ANCHOR_LEFT = [
    # "This is Inspector R. Mehra, CBI Cyber Crime Branch" / "I am Officer Khan, Narcotics Control Bureau"
    rf"{_NOT_REPORTED}\b(?:this|that|it)\s+is\s+{_THE}{_RANK_NAME}{_THE}$",
    rf"\b(?:i\s?am|i'?m|we\s+are|we'?re)\s+(?:an?\s+|the\s+)?{_RANK_NAME}{_THE}$",
    rf"\b(?:main|mai|hum)\s+{_THE}{_RANK_NAME}{_THE}$",
    rf"(?:मैं|हम)\s+{_RANK_NAME}$",
    # A city or state in front of the body ("This is Delhi Police", "calling from Mumbai Police"): up to two
    # capitalised words, and only after the self-claim openers. Before this, each opener had to end exactly at the
    # token, so "This is Delhi Police. Transfer Rs 2 lakh ..." read no authority and came out GREY.
    rf"{_NOT_REPORTED}\b(?:this|that|it)\s+is\s+{_THE}{_PLACE}$",
    rf"\b(?:speaking|calling|writing)\s+(?:from|on behalf of)\s+{_THE}{_PLACE}$",
    rf"\b(?:i\s?am|i'?m|we\s+are|we'?re)\s+(?:from\s+)?{_THE}{_PLACE}$",
    rf"{_NOT_REPORTED}\b(?:from|frm)\s+{_THE}$",                           # "a notice from the CBI"
    rf"{_NOT_REPORTED}\b(?:this|that|it)\s+is\s+{_THE}$",                  # "This is the CBI cyber cell"
    r"\b(?:i\s?am|i'?m|we\s+are|we'?re)\s+(?:an?\s+|the\s+)?$",            # "I am RBI"
    rf"\b(?:main|mai|hum)\s+{_THE}$",                                      # "Main CBI se bol raha hu"
    r"(?:मैं|हम)\s+$",
    rf"\b(?:officer|official|inspector|agent|representative|director|governor|team|desk)\s+(?:of|from|at|with)\s+{_THE}$",
    rf"\bon\s+behalf\s+of\s+{_THE}$",
    rf"\b(?:by\s+|under\s+|vide\s+)?orders?\s+of\s+{_THE}(?:hon'?(?:ble|ourable)\s+)?$",
    rf"\b(?:issued|sent|signed|authorised|authorized)\s+by\s+{_THE}$",     # "issued by RBI", never "verified by RBI"
    rf"\b(?:speaking|calling|writing)\s+(?:from|on behalf of)\s+{_THE}$",
    rf"\b(?:office|o/o)\s+of\s+{_THE}$",
]

# ---- the body's own unit name --------------------------------------------------------------------------------
# "CBI Cyber Cell", "Cyber Crime Police Station, Chennai", "ED Zonal Office": naming a unit of a body is how a
# letterhead and a scam opener both claim to BE that body, so it is a TIER_CLAIM frame.
#
# It used to be matched only AFTER the token, and that made one issuer unreachable. POLICE is the one authority
# whose own name is the PREFIX of its unit noun: `\bpolice\b` consumes the word "Police" in "Cyber Crime Police
# Station", and the frame then looked for a SECOND "police station" starting after it. Same for `\bthana\b` and
# `पुलिस`. A plain-English digital-arrest script ("I am calling from the Cyber Crime Police Station, Chennai. You
# must transfer ten lakh rupees to this verification account ...") therefore came back GREY with
# claimed_issuer NONE, and the band said "no authority was read out of it" about a message whose transfer
# instruction, payee and arrest threat had all been read. A judge found it on 18 Oct.
#
# So the unit is matched as a PHRASE and the token counts two ways: when the phrase FOLLOWS the token, and when
# the phrase CONTAINS it. Containment, not overlap: the phrase has to cover the whole token, so "...the police.
# Station staff will call you" cannot anchor on a phrase that merely touches the word.
#
# The unit nouns themselves are the generic ones a real unit is named with, not a list of the units that exist:
# "Economic Offences Wing" is a CBI unit and nothing in the table may have to know that. Filler is allowed
# between the body and the noun (`_FILL`, at most two non-function words), which is what reads "CBI Economic
# Offences Wing" and "Delhi Police Crime Branch".
# The Devanagari half of the list mirrors the English one noun for noun, because a Devanagari masthead has to
# anchor at the SAME tier as its English equivalent: `सीबीआई साइबर अपराध शाखा, नई दिल्ली` is the same letterhead
# line as `CBI Cyber Crime Branch, New Delhi` and used to anchor nothing, so the Hindi half of a judge's probe
# set read as a message that named no sender at all. Bare `शाखा` is deliberately NOT in the list: on its own it
# is a bank branch ("आपकी शाखा"), so only the qualified crime-branch phrasing counts, exactly as the English side
# carries "crime branch" and not "branch".
_UNIT_NOUN = (r"(?:cyber ?cell|cyber ?crime[\w ]{0,24}?cell|crime branch|police station|police thana|thana"
              r"|chowki|zonal office|regional office|head ?quarters|\bhq\b|commissionerate"
              r"|wing|division|squad|task ?force"
              r"|साइबर ?सेल|साइबर ?कक्ष|पुलिस थाना|पुलिस चौकी|प्रकोष्ठ"
              r"|(?:साइबर |आर्थिक )?अपराध ?शाखा"
              r"|क्षेत्रीय कार्यालय|आंचलिक कार्यालय|मुख्यालय|प्रभाग|दस्ता|इकाई)")
# `\b` cannot close a Devanagari noun. A vowel sign is a nonspacing mark and `'ा'.isalnum()` is False, so `शाखा\b`
# and `थाना\b` never match anything: `पुलिस थाना` and `पुलिस चौकी` have been in this table since it was written
# and both were dead. The closer is "no letter, digit, matra or Devanagari digit follows", which is what `\b`
# means for the English half and what was intended for the Hindi half. U+0964/U+0965 (। and ॥) are deliberately
# out of the range: the danda is the full stop, so it CLOSES a noun rather than continuing it.
_DEVA_CONT = r"ऀ-ॣ०-ॿ"
_UNIT_END = rf"(?!\w|[{_DEVA_CONT}])"

# Telling the reader to GO to a body is the opposite of claiming to be it. Without this, a bank's own awareness
# SMS ("if you get such a call, report it at your nearest police station") read as a police message the moment
# the containment rule above went in, and the officer's band would have said the bank's SMS claims to be the
# police. Deliberately narrow: only verbs that send the reader somewhere, and only with a destination
# preposition and its determiners sitting immediately in front of the body's name. "An FIR has been registered
# at the Cyber Crime Police Station" is scam phrasing and is NOT suppressed, which is exactly why "register",
# "file" and "lodge" are not in this list.
_REFERRAL_VERB = (r"(?:report(?:s|ed|ing)?|complain(?:s|ed|ing|t|ts)?|contact(?:s|ed|ing)?|approach(?:es|ed|ing)?"
                  r"|visit(?:s|ed|ing)?|inform(?:s|ed|ing)?|notif(?:y|ies|ied|ying)|dial(?:s|led|ling)?"
                  r"|forward(?:s|ed|ing)?|escalate(?:s|d)?|refer(?:s|red|ring)?)")
_REFERRAL_DET = (r"(?:the|your|our|any|a|an|its|their|nearest|local|concerned|jurisdictional|relevant"
                 r"|respective|appropriate)")
RE_REFERRAL = re.compile(rf"\b{_REFERRAL_VERB}\b[^.;!?।\n]{{0,40}}?\b(?:to|at|with|before|near)\s+"
                         rf"(?:{_REFERRAL_DET}\s+){{0,3}}$", re.I)
# Some of those verbs take the body as a DIRECT object and need no preposition at all: "Visit the Regional
# Transport Authority to renew your licence", "contact the Grievance Redressal Cell". With only the
# prepositional form above, the open-set net read both of those as a message claiming to BE the body, and the
# officer's band would have said so. Only the verbs that really take a direct object are here: "report" and
# "lodge" are not, because "an FIR has been registered at the Cyber Crime Police Station" is scam phrasing.
RE_REFERRAL_DIRECT = re.compile(r"\b(?:contact(?:s|ed|ing)?|approach(?:es|ed|ing)?|visit(?:s|ed|ing)?"
                                r"|inform(?:s|ed|ing)?|notif(?:y|ies|ied|ying)|dial(?:s|led|ling)?"
                                rf"|email(?:s|ed|ing)?|write\s+to|writes\s+to)\s+(?:{_REFERRAL_DET}\s+){{0,3}}$",
                                re.I)
_REFERRAL_LOOKBACK = 100

# Each right frame is matched starting where the authority token ends.
ANCHOR_RIGHT = [
    # NOTE: the body's own unit ("CBI Cyber Cell", "Cyber Crime Police Station") is NOT here. It needs to match
    # a phrase that can CONTAIN the authority token as well as follow it, which a frame anchored at the token's
    # end cannot do. See `_unit_name`.
    # the letterhead line of a government notice
    _SEP + r"(?:government of india|govt\.? of india|ministry of|भारत सरकार)",
    # NOTE: the document frame ("an ED notice", "a SEBI directive") lives in ANCHOR_CITED, below, not here. It
    # names the body a document is attributed to, which a message can do about someone else; a self-claim must
    # outrank it or one cited authority silences the one the message says it is.
    # the body's own officer is speaking. Closed with _UNIT_END, not \b: "अधिकारी" ends in a vowel sign, after
    # which \b never matches, so "सीबीआई अधिकारी बोल रहा हूँ" anchored nothing until the 23 Oct evaluation found it.
    _SEP + _POSS + _FILL + (r"(?:officers?|official|adhikari|अधिकारी|governor|गवर्नर|inspector|इंस्पेक्टर"
                            r"|director|team|desk|विभाग)" + _UNIT_END),
    _SEP + r"(?:here|speaking|calling|this side)\b",                       # "CBI cyber cell here"
    _SEP + r"(?:se|से)\s+[^.?!।\n]{0,24}?(?:bol|baat|call|बोल|बात|कॉल)",   # "सीबीआई से बोल रहा हूँ"
    # "ED office se bol raha hoon": the body's own office word may sit between the name and "se"
    _SEP + r"(?:office|offices|daftar|headquarters|hq|department|vibhag|विभाग|कार्यालय|दफ़?्तर)\s+(?:se|से)\s+"
           r"[^.?!।\n]{0,24}?(?:bol|baat|call|बोल|बात|कॉल)",
    # speech attributed to the body: "RBI cautions the public", "सीबीआई ने कहा"
    _SEP + (r"(?:ne\s+|ने\s+)?(?:says?|said|cautions?|warns?|states?|informs?|directs?|directed"
            r"|has\s+(?:issued|directed|ordered)|kaha|bola|कहा|बोला)\b"),
    # a court letterhead: "IN THE COURT OF THE DISTRICT JUDGE"
    _SEP + rf"(?:of\s+{_THE})?{_FILL}(?:judge|magistrate|न्यायाधीश)\b",
]

# A document attributed to the body. "This is the CBI. An ED notice also applies in this matter" is one message
# claiming to be the CBI and citing the ED; giving both TIER_CLAIM made them tie, collapsed the issuer to NONE
# and silenced every issuer rule — the same downgrade the anchoring was built to stop. A citation sits at
# TIER_NAME, below a self-claim and above a bare mention, so the self-claim wins and the citation is still read
# when it is the only thing in the message (a forged "ED summons" with no "this is" sentence).
ANCHOR_CITED = [
    _SEP + _POSS + _FILL + (r"(?:summons?|समन|notice|नोटिस|orders?|आदेश|aadesh|advisory|instructions?|निर्देश"
                            r"|directive|directions?|scheme|yojana|योजना|memo)\b"),
]

# TIER_NAME: the body's name spelled out in full. An acronym ("RBI", "ED", "CBI") never qualifies - typing three
# letters is what the injection did, and it must not be enough.
# The civic bodies' names are as generic as "high court", and spelled out they are a letterhead the same way;
# their acronyms (RTO, MCD) stay out, as every acronym does.
ANCHOR_FULL_NAME = (r"(?:directorate of enforcement|enforcement directorate|central bureau of investigation"
                    r"|reserve bank(?: of india)?|supreme court(?: of india)?|high court"
                    r"|department of telecom\w*|प्रवर्तन निदेशालय|भारतीय रिज़?र्व बैंक|रिज़?र्व बैंक"
                    r"|सुप्रीम कोर्ट|उच्च न्यायालय|सर्वोच्च न्यायालय"
                    r"|traffic police|regional transport (?:office|authority)|transport department"
                    r"|municipal corporation|municipal council|nagar (?:nigam|palika|parishad)"
                    r"|यातायात पुलिस|ट्रैफ़?िक पुलिस|परिवहन विभाग|नगर (?:निगम|पालिका|परिषद))")

# TIER_ACCOUNT: the body named beside the payee account, either side of it. The window stops at a comma as well
# as at sentence punctuation, because it has to hold a noun phrase and not a clause: "RBI Dear Customer, your
# Demo Bank savings account ..." (a regulator's name pasted in front of a real bank SMS) used to clear a 40-
# character window and read as an RBI-owned account.
# The window is the same bounded filler the owner table uses, not a free 40 characters: "as per RBI guidelines on
# account closure" cleared a free window and told the officer a routine KYC SMS claimed to be from RBI, which is
# the very hole _OWNER_FILLER was built to close, re-opened one layer up.
# A bounded window, but it may not cross an English connector: "RBI guidelines ON account closure" cleared a free
# window and told the officer a routine KYC SMS claimed to be from RBI, which is the hole _OWNER_FILLER was built
# to close, re-opened one layer up. A character window rather than a token one, because the Devanagari phrasing
# ("आरबीआई की विशेष निगरानी में आपका खाता") runs to four or five words and a token count tuned on English breaks it.
_ANCHOR_ACCT_RIGHT = rf"(?:(?!\s(?:on|for|under|as|per|regarding|about|in|of)\s)[^.;!?।,\n]){{0,40}}?{_DEST}"
_ANCHOR_ACCT_LEFT = rf"{_DEST}[^.;!?।,\n]{{0,16}}$"

# ---- open-set authorities: the bodies the Issuer enum does not hold ----------------------------------------
# The enum holds eight bodies. India has hundreds, and a scam picks whichever one fits its story: "IRDAI
# Enforcement Cell, Mumbai", "Narcotics Control Bureau", "Cyber Crime Coordination Cell". Every one of those used
# to anchor nothing, so a textbook digital-arrest script built on a body we do not enumerate read as a message
# that named no sender at all, and the whole class landed on GREY with the officer's band saying "no authority
# was read out of it" about a letterhead that spells one out.
#
# What is read, and nothing wider: a MULTI-WORD name whose head noun is one a state body is actually named with.
# The name is matched case-sensitively, so only a title-cased or all-caps name qualifies; a lowercase mention
# ("report it to the enforcement cell") does not, for the same reason an acronym never reaches TIER_NAME. The
# claim lands on `Issuer.OTHER`, whose verbatim span IS the body's name, so the record says what the message
# said even though the enum has no row for it.
#
# The name reaches TIER_NAME on its FORM, exactly as a spelled-out enumerated name does ("DIRECTORATE OF
# ENFORCEMENT." / "The Reserve Bank of India cautions the public"), and TIER_CLAIM through the ordinary frames.
# A masthead is the form, so writing the masthead position in as a separate condition was the first attempt and
# it was wrong: prefixing one word to the message moves the name off the start of the line, so "RBI " pasted in
# front of a notice silently dropped its issuer to NONE. That is the injection hole in a new hat, and
# tests/test_injection_steering.py caught it. A referral and a reported claim suppress the anchor, as for any
# enumerated body.
#
# THREE GATES do the discriminating, because the net is wide (the third was added on 19 Oct by this pass's own
# adversarial gate, and is written out beside _CORP_SUFFIX below):
#   1. the name is capitalised and multi-word, matched case-sensitively, so a lowercase mention ("report it to
#      the enforcement cell") never qualifies - the same rule that keeps an acronym out of TIER_NAME.
#   2. the head noun has to place the body in the STATE. Bureau, Directorate, Commission and Authority are
#      statutory words in India and carry themselves. Department, Board, Cell and Unit do not: a bank's own
#      letterhead says "Demo Bank Loan Recovery Cell, Head Office" - the judge's benign-letter probe is written
#      on one, and reading it as a government body silenced the bank's own outbound-log rule and took that
#      probe from AMBER to GREY. For those four the name must also carry a word from the state vocabulary.
#   3. the run the name sits in must not say the body is a registered COMPANY (_CORP_SUFFIX).
# A name that contains the bank's own name is handled one layer up, in `extract`: the bank's unit is the bank.
_OPEN_HEAD_STATE = r"(?:bureau|directorate|commission|authority)"
_OPEN_HEAD_SHARED = r"(?:department|board|cell|unit)"
_OPEN_HEAD = rf"(?:{_OPEN_HEAD_STATE}|{_OPEN_HEAD_SHARED})"
_OPEN_STATE_MARK = (r"(?:government|govt|ministry|national|central|state|union|enforcement|investigation"
                    r"|intelligence|crime|criminal|narcotics|revenue|income[- ]?tax|customs|excise|vigilance"
                    r"|anti[- ]?corruption|judicial|prosecution|magistrate|commissionerate|directorate|bureau"
                    r"|police|CBI|ED|NCB|NIA|CID|IRDAI|SEBI|RBI|TRAI|GST|PMLA|IT)")
_OPEN_TOKEN = r"[A-Z][A-Za-z'’.&-]*"
# the head noun itself must be capitalised too, so "Delhi police cell" does not qualify
RE_OPEN_BODY = re.compile(rf"\b(?:{_OPEN_TOKEN}[\x20\t-]+){{1,4}}(?=[A-Z])(?i:{_OPEN_HEAD})\b")
RE_OPEN_STATE = re.compile(rf"(?:{_OPEN_HEAD_STATE})\s*$", re.I)
RE_OPEN_MARK = re.compile(rf"\b{_OPEN_STATE_MARK}\b", re.I)
# Devanagari, head for head and marker for marker with the English list. A Devanagari masthead has to anchor at
# the same tier as its English equivalent; Devanagari has no case, so the capitalisation gate has no analogue and
# the multi-word and head-noun gates are what carry it.
_OPEN_HEAD_STATE_HI = r"(?:ब्यूरो|निदेशालय|आयोग|प्राधिकरण|अधिकरण)"
_OPEN_HEAD_SHARED_HI = r"(?:विभाग|बोर्ड|प्रकोष्ठ|कक्ष|इकाई)"
_OPEN_MARK_HI = (r"(?:सरकार\w*|राष्ट्रीय|केंद्रीय|केन्द्रीय|राज्य|मंत्रालय|प्रवर्तन|जाँच|जांच|अपराध\w*|आपराधिक"
                 r"|स्वापक|राजस्व|आयकर|सीमा|शुल्क|सतर्कता|न्यायिक|अभियोजन|पुलिस|सीबीआई|ईडी|एनसीबी|आरबीआई|सेबी)")
RE_OPEN_BODY_HI = re.compile(rf"(?:[{_DEVA_CONT}]+[\x20\t-]+){{1,4}}"
                             rf"(?:{_OPEN_HEAD_STATE_HI}|{_OPEN_HEAD_SHARED_HI})(?![{_DEVA_CONT}])")
RE_OPEN_STATE_HI = re.compile(rf"{_OPEN_HEAD_STATE_HI}\s*$")
RE_OPEN_MARK_HI = re.compile(_OPEN_MARK_HI)

# GATE 3, added 19 Oct after the pass's own adversarial gate: a body that names itself a COMPANY is not the
# state. The two gates above read form, and form cannot tell "Narcotics Control Bureau" from "Credit Information
# Bureau (India) Limited", or "Cyber Crime Investigation Cell" from "Claims Investigation Department, Acme
# General Insurance Company Limited". Both are multi-word, title-cased, headed by a state head noun and carrying
# a state-vocabulary marker ("crime", "investigation", "intelligence"), and ordinary corporate department names
# cleared all of it. What the second of each pair also carries is a registered-company suffix, which is a fact
# about the sender that it put there itself, so it is cheap and principled to read.
#
# This does NOT close the class on its own ("Acme Recovery and Fraud Investigation Unit" has no suffix), which
# is why the customer-facing sentence changed as well (R-STATE-NAME-PAY). It is here because the cost of being
# wrong runs one way only: a disqualified body reads as no authority, the message lands on GREY, and GREY says
# in words what could not be checked. The cost is paid by a state body that happens to say "Corporation" in its
# own masthead ("Municipal Corporation of Greater Mumbai Vigilance Cell"), which drops to GREY. Recorded, and
# the right side to err on for a net this wide.
#
# Matched case-sensitively, for the same reason the name itself is: "a limited number of days" and "the company
# you keep" are prose, and a masthead is title-cased or all-caps. Both forms are spelled out because a
# case-insensitive match would take the prose with it.
_CORP_SUFFIX = (r"(?:Private\s+Limited|Pvt\.?\s*Ltd\.?|Limited|Ltd\.?|LLP|Incorporated|Inc\.?"
                r"|Corporation|Corp\.?|Company|Co\.?"
                r"|PRIVATE\s+LIMITED|PVT\.?\s*LTD\.?|LIMITED|LTD\.?|INCORPORATED|CORPORATION|COMPANY"
                r"|प्राइवेट\s+लिमिटेड|लिमिटेड|कंपनी|कम्पनी|कॉरपोरेशन|कॉर्पोरेशन)")
RE_CORP_SUFFIX = re.compile(rf"(?<![A-Za-z])(?:{_CORP_SUFFIX})(?![A-Za-z])")
# Where the suffix has to sit for it to be this body's own: the masthead or self-claim run the name sits in.
# A company name in a LATER sentence says nothing about the body named here, or "Narcotics Control Bureau. Remit
# the amount to our collection account at HDFC Bank Limited" would disqualify a real letterhead. A single
# newline does not break the run, because a masthead wraps ("Business Intelligence Department\nAcme Retail
# Private Limited" is one masthead); a blank line does.
RE_SEGMENT_BREAK = re.compile(r"[.;!?।]|\n[\x20\t]*\n")


def _names_a_state_body(name: str) -> bool:
    """Does this open-set name place the body in the state? See gate 2 above."""
    if RE_OPEN_STATE.search(name) or RE_OPEN_STATE_HI.search(name):
        return True
    return bool(RE_OPEN_MARK.search(name) or RE_OPEN_MARK_HI.search(name))


def _masthead_run(text: str, start: int, end: int) -> str:
    """The masthead or self-claim run a name sits in: the text between the sentence breaks either side of it."""
    left = 0
    for b in RE_SEGMENT_BREAK.finditer(text, 0, start):
        left = b.end()
    b = RE_SEGMENT_BREAK.search(text, end)
    return text[left:b.start() if b else len(text)]


def _names_a_company(text: str, m: re.Match) -> bool:
    """Does the run this name sits in say the body is a registered company? See gate 3 above."""
    return bool(RE_CORP_SUFFIX.search(_masthead_run(text, m.start(), m.end())))


def _open_set_names(rx: re.Pattern, text: str, enum_spans: list[tuple[int, int]]) -> list[re.Match]:
    """Every open-set body name in the text, trimmed clear of the bodies the enum already holds.

    Trimming rather than skipping, because the greedy name swallows an injected prefix: "RBI Income Tax
    Department" is not an unnamed bureau called RBI-something, it is RBI pasted in front of the Income Tax
    Department, and dropping the whole match let one word move the issuer. Leading qualifier tokens come off
    until the name is free of every enumerated token, and what is left still has to pass all three gates.
    """
    out: list[re.Match] = []
    pos = 0
    while True:
        m = rx.search(text, pos)
        if m is None:
            return out
        best: Optional[re.Match] = m
        while best is not None and any(s < best.end() and best.start() < e for s, e in enum_spans):
            nxt = rx.search(text, best.start() + 1)
            best = nxt if nxt is not None and nxt.end() == best.end() else None
        if best is not None and _names_a_state_body(best.group(0)) and not _names_a_company(text, best):
            out.append(best)
        pos = m.end()


RE_ANCHOR_LEFT = [re.compile(p, re.I) for p in ANCHOR_LEFT]
RE_ANCHOR_RIGHT = [re.compile(p, re.I) for p in ANCHOR_RIGHT]
RE_UNIT_AFTER = re.compile(_SEP + _POSS + _FILL + _UNIT_NOUN + _UNIT_END, re.I)
# "<Body> Department" with nothing in between: "Customs Department, Mumbai Airport" anchored nothing in English until
# the 23 Oct evaluation found it, while the Hindi विभाग already did. No filler is allowed, unlike the unit nouns
# above: with it, "CBI " pasted in front of "Income Tax Department" read as the CBI's own department and moved the
# issuer, which tests/test_injection_steering.py caught the same day.
RE_DEPARTMENT_AFTER = re.compile(_SEP + r"department" + _UNIT_END, re.I)
RE_UNIT_PHRASE = re.compile(rf"\b{_UNIT_NOUN}{_UNIT_END}", re.I)
# How far a unit phrase may start before, or end after, the authority token it contains. "Police Station" is the
# longest overhang that matters (8 characters); 24 leaves room for the Devanagari and the spaced forms.
_UNIT_WINDOW = 24
RE_ANCHOR_CITED = [re.compile(p, re.I) for p in ANCHOR_CITED]
RE_ANCHOR_FULL_NAME = re.compile(rf"^{ANCHOR_FULL_NAME}$", re.I)
RE_ANCHOR_ACCT_RIGHT = re.compile(_ANCHOR_ACCT_RIGHT, re.I)
RE_ANCHOR_ACCT_LEFT = re.compile(_ANCHOR_ACCT_LEFT, re.I)
_ANCHOR_LOOKBACK = 64      # how far left of the token a frame may start ("by order of the Hon'ble ")

# Two authority tokens inside one noun phrase name ONE body: "CBI Cyber Cell" is the CBI, not the CBI plus a
# police cyber cell, and "Hon'ble Supreme Court of India" is one court. Only separators and a few joining words
# may sit between them.
RE_ANCHOR_SAME_PHRASE = re.compile(r"[\s,/&–—-]*(?:(?:of|the|ki|ka|ke|का|के|की)[\s-]+)*")

# ---- a rank is not a body ----------------------------------------------------------------------------------
# Some issuer tokens name a RANK, a ROLE or a DOCUMENT rather than a body: "Inspector", "Governor", "Judge",
# "FIR". They are worth matching, because a digital-arrest script opens with a rank far more often than with a
# body, but they identify the body only by implication, and the body they imply is the broadest one in the
# family. "This is Inspector <name>, CBI Economic Offences Wing, Delhi ... place a refundable judicial security
# deposit of Rs 12,00,000 ..." anchored POLICE on "Inspector" at offset 8, demoted the CBI to other_issuers,
# and the Hindi customer card then told a frightened customer the message "claims to be the police". It claims
# to be the CBI, and the message says so in words.
#
# So at EQUAL anchor tier a named body outranks a generic rank word. This can only ever break a tie: when a
# rank word is the only authority the message names ("Inspector here from the control room"), it still wins,
# because `select_issuer` falls back to the full tied set. Written as the pattern strings themselves, and
# `tests/test_rank_is_not_a_body.py` asserts every one of them is still live in ISSUER_KEYWORDS, so a renamed
# pattern fails loudly instead of quietly promoting a rank word again.
GENERIC_ISSUER_TOKENS = frozenset({
    r"\binspector\b", r"\bइंस्पेक्टर\b", r"\bFIR\b",                 # POLICE: a rank, and a document
    r"\bgovernor\b",                                                 # RBI: a post
    r"\bjudge\b", r"न्यायाधीश",                                       # COURT: a person
    r"\bparcel\b.*\b(seized|contraband|drugs)\b",                    # CUSTOMS: a situation, not a body
    r"\bsim\b.{0,20}\b(block|band|deactivat)",                       # TRAI_DOT: a situation, not a body
})


def _is_generic(m: re.Match) -> bool:
    """Did this occurrence come from a token that names a rank, a role or a document rather than a body?"""
    return m.re.pattern in GENERIC_ISSUER_TOKENS


@dataclass
class IssuerHit:
    """One authority the message names, the best-anchored occurrence of it, and how it is anchored."""
    issuer: Issuer
    match: re.Match          # the token occurrence that earned `tier`; its span is what the officer is shown
    tier: int
    on_account: bool         # somewhere in the message this body is named beside the payee account
    first: re.Match          # the EARLIEST occurrence, which is all select_issuer_first_match looks at
    generic: bool = False    # the occurrence names a rank/role/document, not the body itself

    @property
    def anchored(self) -> bool:
        return self.tier >= TIER_ACCOUNT


# A clause that reports somebody else's claim is not this message's claim. The lookbehinds on the left frames
# only catch the phrasing directly in front of the token; a bank's genuine warning lists several bodies after one
# "claiming to be" ("fraudsters claiming to be from CBI or the Reserve Bank of India"), and the second one reached
# TIER_NAME on its full institutional name. This guard covers every tier.
RE_REPORTED_CLAIM = re.compile(r"\b(?:claim(?:ing|s|ed)?|pretend(?:ing|s|ed)?|pos(?:ing|es|ed)|purport(?:ing|s|ed)?"
                               r"|impersonat(?:ing|es|ed)?|masquerad(?:ing|es|ed))\s+(?:to\s+be\s+|as\s+)?"
                               r"[^.;!?।\n]{0,80}$", re.I)


def _in_reported_claim(text: str, m: re.Match) -> bool:
    """Is this occurrence inside a clause that reports somebody else's claim rather than making one?"""
    clause = text.rfind(".", 0, m.start()) + 1
    return bool(RE_REPORTED_CLAIM.search(text, max(clause, m.start() - 120), m.start()))


def _is_referral(text: str, at: int) -> bool:
    """Does the clause in front of position `at` send the READER to this body ("report it at the ...")?"""
    lo = max(0, at - _REFERRAL_LOOKBACK)
    return bool(RE_REFERRAL.search(text, lo, at) or RE_REFERRAL_DIRECT.search(text, lo, at))


def _unit_name(text: str, m: re.Match) -> bool:
    """Does this authority token sit in the body's own unit name? Two shapes, see `_UNIT_NOUN`.

    FOLLOWS the token: "CBI Cyber Cell", "ED Zonal Office", "CBI Economic Offences Wing".
    CONTAINS the token: "Cyber Crime Police Station", "पुलिस थाना", "thana" - the cases where the body's own
    name is a prefix of its unit noun and matching only after the token made the whole frame unreachable.
    """
    if (RE_UNIT_AFTER.match(text, m.end()) or RE_DEPARTMENT_AFTER.match(text, m.end())) and not _is_referral(text, m.start()):
        return True
    for u in RE_UNIT_PHRASE.finditer(text, max(0, m.start() - _UNIT_WINDOW), m.end() + _UNIT_WINDOW):
        if u.start() <= m.start() and u.end() >= m.end() and not _is_referral(text, u.start()):
            return True
    return False


def anchor_tier(text: str, m: re.Match) -> int:
    """How strongly this occurrence of an authority token claims to be the sender. See the tier table above."""
    if _in_reported_claim(text, m):
        return TIER_NONE
    for pat in RE_ANCHOR_LEFT:
        if pat.search(text, max(0, m.start() - _ANCHOR_LOOKBACK), m.start()):
            return TIER_CLAIM
    if _is_masthead(text, m):
        return TIER_CLAIM
    if _unit_name(text, m):
        return TIER_CLAIM
    for pat in RE_ANCHOR_RIGHT:
        if pat.match(text, m.end()):
            return TIER_CLAIM
    for pat in RE_ANCHOR_CITED:
        if pat.match(text, m.end()):
            return TIER_NAME
    if RE_ANCHOR_FULL_NAME.match(m.group(0)):
        return TIER_NAME
    if _anchored_on_account(text, m):
        return TIER_ACCOUNT
    return TIER_NONE


# A masthead: the body's name opens the message or a line and a colon follows it ("CBI: Transfer ...", "Mumbai
# Police: ...", "सीबीआई: ...", "दिल्ली पुलिस: ..."). That is how an SMS sender line reads, and it anchored nothing:
# a law-enforcement money demand with the body as its first word came out GREY with "no authority was read".
# Up to two capitalised place words (one Devanagari word) may stand before the name; nothing else may.
RE_MASTHEAD_LEFT = re.compile(r"(?:^|\n)[\x20\t\"'“‘*]*(?:(?:(?-i:[A-Z])[a-z]+[\x20\t]+){0,2}|[ऀ-ॿ]+[\x20\t]+)$")
RE_MASTHEAD_RIGHT = re.compile(r"[\x20\t]*[:：]")


def _is_masthead(text: str, m: re.Match) -> bool:
    return bool(RE_MASTHEAD_RIGHT.match(text, _unit_name_end(text, m))
                and RE_MASTHEAD_LEFT.search(text, max(0, m.start() - 40), m.start()))


def _anchored_on_account(text: str, m: re.Match) -> bool:
    return bool(RE_ANCHOR_ACCT_RIGHT.match(text, m.end())
                or RE_ANCHOR_ACCT_LEFT.search(text, max(0, m.start() - _ANCHOR_LOOKBACK), m.start()))


def _unit_name_end(text: str, m: re.Match) -> int:
    """Where the body's own unit name ends, if the token is followed by one. `m.end()` otherwise.

    "CBI Cyber Crime Branch" names one body, and the characters that anchor the CBI are the same characters that
    anchor POLICE (`crime branch` is a POLICE token). Before this the two tied at TIER_CLAIM, `select_issuer`
    found two law-enforcement personas and returned None, and a judge's digital-arrest script fell through to
    BANK_SELF on the words "branch manager" at the end of it. RE_ANCHOR_SAME_PHRASE cannot see this on its own:
    it allows only separators and joining words between two tokens, and "Cyber" is neither.
    """
    u = RE_UNIT_AFTER.match(text, m.end())
    return u.end() if u else m.end()


def _same_phrase(text: str, a: re.Match, b: re.Match) -> bool:
    lo, hi = sorted((a, b), key=lambda x: x.start())
    if hi.start() <= lo.end():
        return True
    # the second token sits inside the first one's own unit name: "CBI Cyber Crime Branch" is the CBI
    if hi.end() <= _unit_name_end(text, lo) and not _is_referral(text, lo.start()):
        return True
    return bool(RE_ANCHOR_SAME_PHRASE.fullmatch(text[lo.end():hi.start()]))


def _open_set_tier(text: str, m: re.Match) -> int:
    """How strongly an open-set body name claims to be the sender. See the RE_OPEN_BODY block above."""
    if _in_reported_claim(text, m) or _is_referral(text, m.start()):
        return TIER_NONE
    return TIER_CLAIM if anchor_tier(text, m) >= TIER_CLAIM else TIER_NAME


def authority_hits(text: str) -> list[IssuerHit]:
    """Every authority the message names, with its best-anchored occurrence. Order: first mention first."""
    hits: list[IssuerHit] = []
    enum_spans: list[tuple[int, int]] = []
    for issuer, pats in ISSUER_KEYWORDS:
        if issuer not in AUTHORITY_ISSUERS:
            continue
        found = [(anchor_tier(text, m), m) for p in pats for m in re.finditer(p, text, re.I)]
        if not found:
            continue
        enum_spans += [(mm.start(), _unit_name_end(text, mm)) for _, mm in found]
        # the occurrence shown to the officer is the best-anchored one; a token that names the body beats a rank
        # word at the same tier, and the earliest wins after that
        tier, m = max(found, key=lambda tm: (tm[0], not _is_generic(tm[1]), -tm[1].start()))
        hits.append(IssuerHit(issuer=issuer, match=m, tier=tier, generic=_is_generic(m),
                              on_account=any(_anchored_on_account(text, mm) for _, mm in found),
                              first=min((mm for _, mm in found), key=lambda mm: mm.start())))
    # The open-set bodies, appended last so that a tie in start offset keeps the enumerated body in front: the
    # sort below is stable, and "Central Bureau of Investigation" is the CBI, not an unnamed bureau.
    found = [(_open_set_tier(text, m), m)
             for rx in (RE_OPEN_BODY, RE_OPEN_BODY_HI) for m in _open_set_names(rx, text, enum_spans)]
    found = [(t, m) for t, m in found if t > TIER_NONE]
    if found:
        tier, m = max(found, key=lambda tm: (tm[0], -tm[1].start()))
        hits.append(IssuerHit(issuer=Issuer.OTHER, match=m, tier=tier,
                              on_account=any(_anchored_on_account(text, mm) for _, mm in found),
                              first=min((mm for _, mm in found), key=lambda mm: mm.start())))
    hits.sort(key=lambda h: h.match.start())
    return hits


def select_issuer(text: str, hits: list[IssuerHit]) -> Optional[IssuerHit]:
    """Which named authority, if any, the message claims to be.

    Anchor strength decides, never position: that is what closes the prefix-injection hole, because a bare
    mention anywhere in the text now loses to the body the message actually claims to be.

    Zero anchored: None, so claimed_issuer stays NONE. The band already says in words when it could not read an
    authority out of the message, and "we could not tell" is the honest answer when nothing in the text claims
    an identity. The mentions are not thrown away - they go to `claim.other_issuers`.

    Two anchored, equally strongly, and one of them earned its anchor on a rank word rather than on the body's
    own name: the named body wins. "This is Inspector <name>, CBI Economic Offences Wing" claims to be the CBI,
    and before this the rank word won on position alone and the card said "the police". A rank word still wins
    when it is the only thing tied, so this never loses an issuer, only ever makes one more specific.

    Two anchored, equally strongly, and genuinely two bodies: prefer the one the payee account is attributed to,
    because that is the body the money is being demanded in the name of and the one every money rule is about.
    If the account points at neither or at both, None: a message that claims to be two different authorities
    does not let us say which, and saying one of them in the officer's band would be the original bug wearing a
    different hat. Both still land in `claim.other_issuers`.
    """
    anchored = [h for h in hits if h.anchored]
    if not anchored:
        return None
    top = max(h.tier for h in anchored)
    tied = [c for c in anchored if c.tier == top]
    tied = [h for h in tied if not h.generic] or tied      # a named body outranks a rank word; never empties
    kept: list[IssuerHit] = []
    for h in tied:
        if not any(_same_phrase(text, k.match, h.match) for k in kept):
            kept.append(h)
    if len(kept) == 1:
        return kept[0]
    on_money = [h for h in kept if h.on_account]
    if len(on_money) == 1:
        return on_money[0]
    # Two bodies claimed and the money points at neither. Returning None here was the injection hole wearing a
    # different hat: an attacker only had to anchor a second, harmless-looking authority ("A notice from the
    # Reserve Bank of India. This is CBI Cyber Cell. ...") to make the issuer NONE and silence every issuer rule.
    # A silent downgrade is the attack; an upgrade is not, because a lone hard rule is still only AMBER. So when
    # exactly one of the tied bodies is a law-enforcement persona, that is the one the money rules are about and
    # the one we name. The others are still recorded in `claim.other_issuers`, and the band can say both were
    # named. Only when the tie is between two bodies of the same kind do we admit we cannot tell.
    enforcement = [h for h in kept if h.issuer in LAW_ENFORCEMENT]
    return enforcement[0] if len(enforcement) == 1 else None


def select_issuer_first_match(text: str, hits: list[IssuerHit]) -> Optional[IssuerHit]:
    """The rule that shipped before anchoring: the EARLIEST authority token wins, anchored or not.

    Kept only as the control for `tests/test_injection_steering.py`, which swaps it back in to show the
    injection probe really does come back RBI and GREY without anchoring. Nothing in the engine calls it.
    """
    if not hits:
        return None
    h = min(hits, key=lambda x: x.first.start())
    return replace(h, match=h.first, tier=TIER_CLAIM)


PRESSURE_KEYWORDS: dict[str, list[str]] = {
    "arrest_threat": [r"\barr?est(?:s|ed|ing|ee)?\b", r"गिरफ़?्तार", r"अरेस्ट", r"digita?l (arr?est|custody)", r"डिजिटल (अरेस्ट|गिरफ़?्तारी|हिरासत)", r"\bcustody\b", r"\bwarrant\b", r"\bjail\b", r"जेल", r"non[- ]bailable", r"हिरासत"],
    "secrecy": [r"do not (tell|share|inform|disclose)", r"don'?t (tell|share|inform)", r"kisi ko (mat|na) bata", r"किसी को (मत|न) बता", r"\bconfidential\b", r"national (secret|security)", r"गोपनीय", r"\bsecret\b", r"\btop secret\b"],
    "urgency": [r"\bimmediately\b", r"\bturant\b", r"तुरंत", r"within \d+ ?(hours?|minutes?|hrs?)", r"\babhi\b", r"अभी", r"last (chance|warning)", r"\burgent", r"\bright now\b", r"आज ही"],
    "isolation": [r"stay on (the )?(camera|call|line)", r"(do not|don'?t|mat) (disconnect|cut|hang up|band)", r"camera (par|on) rah", r"कैमर", r"video (par|on) (rahe|raho|बने)", r"keep (the )?(video|call) on"],
    "guaranteed_returns": [r"guaranteed", r"गारंटी", r"\b\d+\s?x\b", r"\bdouble\b", r"\brisk[- ]free\b", r"assured return", r"fixed (daily|weekly|monthly) (profit|return)"],
}

CHANNEL_KEYWORDS: list[tuple[Channel, list[str]]] = [
    (Channel.VIDEO_CALL, [r"video call", r"वीडियो कॉल", r"\bskype\b", r"\bzoom\b", r"\bon camera\b", r"कैमरे पर"]),
    (Channel.WHATSAPP, [r"whats ?app", r"व्हाट्सऐप", r"व्हाट्सएप", r"\bwa\b", r"voice note"]),
    (Channel.SMS, [r"\bSMS\b", r"text message", r"एसएमएस"]),
    (Channel.EMAIL, [r"\be-?mail\b", r"ईमेल"]),
    (Channel.POST, [r"\b(speed )?post\b", r"\bcourier\b(?!.{0,30}parcel)", r"डाक"]),
    (Channel.PHONE_CALL, [r"\bcall\b", r"\bphone\b", r"कॉल", r"\bIVR\b"]),
]

# ---- the de-spacing lexicon --------------------------------------------------------------------------------
# "You must t r a n s f e r Rs 38,00,000 to the verification account 30011223344556" came back with instruction
# NONE and scored GREY. Pass 3 closed homoglyphs, zero-widths and leetspeak; spacing has no character to fold,
# so it walked through all of it. `normalize` closes up a spaced run only when the run reconstitutes a word in
# THIS lexicon, and the lexicon lives here because the only words it can ever be safe to close up are the words
# the extractor's own tables look for. Closing a run into anything else would be inventing text.
#
# So the lexicon is not a hand-written word list: it is a candidate list FILTERED through the tables below. A
# candidate survives only if some pattern in this module matches it on its own, which is the operational meaning
# of "a word the extractor already knows". `tests/test_spaced_letters.py` asserts the filter keeps every
# candidate, so a typo or a renamed pattern shows up as a failure rather than as a silently dead fold.
_DESPACE_CANDIDATES = (
    # the instruction verbs and the destination
    "transfer", "transferred", "remit", "remitted", "deposit", "deposited", "account", "akount", "acount",
    "khata", "khaata", "wallet", "beneficiary", "payee", "shift", "shifted", "parked", "moved",
    # the money words
    "amount", "funds", "money", "balance", "holdings", "savings", "rupees", "paise", "paisa",
    # the pressure cues a card is allowed to quote
    "arrest", "custody", "warrant", "urgent", "immediately", "confidential", "secret",
    # the authorities whose names are long enough to clear the floor (an acronym never is)
    "police", "customs", "court", "judge", "governor", "inspector",
    # the words that point at the account
    "designated", "verification", "clearance", "settlement", "escrow", "mentioned",
)


def _table_patterns() -> list[str]:
    """Every pattern string this module matches a message against, flattened."""
    out = [p for _, pats in ISSUER_KEYWORDS for p in pats]
    out += [p for _, pats in INSTRUCTION_KEYWORDS for p in pats]
    out += [p for _, pats in OWNER_KEYWORDS for p in pats]
    out += [p for _, pats in CHANNEL_KEYWORDS for p in pats]
    out += [p for pats in PRESSURE_KEYWORDS.values() for p in pats]
    out += [_MONEY, _DEST, _MOVE_VERB, _MOVED, _POINTER]
    return out


DESPACE_LEXICON = frozenset(
    w for w in _DESPACE_CANDIDATES if any(re.fullmatch(p, w, re.I) for p in _table_patterns())
)

# The digit group is bounded by DIGIT count, not by character count. With a character window, spaced digits ate
# the budget: the pass-5 gate wrote "a c c o u n t  No 3 0 0 1 1 2 2 3 3 4 4 5 5 6" and the 22-character window
# truncated a 14-digit account to 12, which is the number that would have gone to the beneficiary name look-up,
# to the I4C registry and into the signed evidence pack. A wrong identifier is worse than no identifier.
RE_ACCOUNT = re.compile(r"(?:a/?c(?:count)?|acct|account|खात[ाे]|khata)\s*(?:no\.?|number|नंबर|#|:)?\s*[:\-]?\s*"
                        r"((?:\d[\s-]{0,2}){9,19}\d)", re.I)
RE_ACCOUNT_BARE = re.compile(r"\b(\d{11,18})\b")
# ---- the customer's own account is not a payee --------------------------------------------------------------
# A benign Demo Bank re-KYC letter ("your account 3001122334455 will be restricted if the KYC is not updated")
# came back with the customer's own savings account as the payee. That is an assertion about where money is being
# sent, and it is the number that would have gone to the beneficiary-name look-up, to the I4C suspect registry
# and into the signed evidence pack, and the number the card calls "the account you were told to pay".
#
# Whose account it is, is something the message says in words: a first- or second-person possessive in front of
# the account keyword. A third-party possessive ("his account") is left alone, because the message is then
# naming somebody else's account and that may well be the payee. Only accounts are guarded, not UPI ids: "please
# return the amount to MY UPI rahul.k@okicici" is a payee, and the possessive is the whole point of it.
_SELF_POSS = (r"(?:your|yours|ur|aapk[aeio]|apk[aeio]|tumch[ayi]|tumhar[ae]|my|mine|mera|meri|mere|hamar[ae]"
              r"|आपक[ाेी]|तुम्हार[ेा]|मेर[ाेी]|हमार[ेा]|अपन[ेा])")
# Up to three attributive words may sit between the possessive and the account keyword ("your Demo Bank savings
# account"). A preposition or a conjunction may not: without that guard "pay your dues TO THE account 409..."
# reads as the customer's own account and the payee the message does name is thrown away. Same shape as _FILL.
_OWN_FILL = r"(?:(?!(?:to|into|in|at|for|of|on|from|and|or|the|a|an|is|will)\b)[\w.'-]+\s+){0,3}"
RE_OWN_ACCOUNT = re.compile(rf"(?<![a-z]){_SELF_POSS}\s*{_OWN_FILL}$", re.I)
_OWN_LOOKBACK = 48
RE_IFSC = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
RE_VPA = re.compile(r"\b([a-z0-9][a-z0-9._-]{1,}@[a-z][a-z0-9]{1,})\b", re.I)
RE_AMOUNT = re.compile(r"(?:₹|rs\.?|inr|rupees?)\s?([\d,]+(?:\.\d+)?)(\s?(?:lakh|lac|crore|cr|k))?|([\d,]+(?:\.\d+)?)\s?(lakh|lac|crore|cr)\b", re.I)
# a summons id has letters/digits joined by "/" or "-" (ED/DLZO/2026/4471); plain words like "under" are not ids
RE_SUMMONS_NO = re.compile(r"summons?\s*(?:no\.?|number|#|नंबर)?\s*[:\-]?\s*([A-Z]{1,4}[/\-][A-Z0-9/\-]{3,}|\d[A-Z0-9/\-]{3,})", re.I)
# A case, document or passcode number contains a digit. Without that bound, "case" and "crime" swallowed the
# next word: the judge's probes stored case_no = "under" (from "under NDPS Act"), "COORDINATION" (from "CYBER
# CRIME COORDINATION CELL") and "helpline", and the console then drew a "Case number" mark on nonsense.
# The lookahead is only a minimum-length guard; the capture is what requires the digit.
RE_PASSCODE = re.compile(r"pass ?code\s*(?:is\s*)?[:\-]?\s*(?=[A-Z0-9]{4,12}\b)([A-Z0-9]*\d[A-Z0-9]*)\b", re.I)
RE_CASE_NO = re.compile(r"(?:case|FIR|crime)\s*(?:no\.?|number|#)?\s*[:\-]?\s*(?=[A-Z0-9/\-]{3,})([A-Z0-9/\-]*\d[A-Z0-9/\-]*)", re.I)
RE_DATE = re.compile(r"\b(\d{1,2}[\-/.]\d{1,2}[\-/.]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4})\b", re.I)
RE_PHONE = re.compile(r"(?<!\d)(?:\+91[\s-]?)?(1600\d{5,7}|[6-9]\d{9})(?!\d)")
# ---- an instruction that the message is telling you NOT to follow ------------------------------------------
# Public-awareness text is written out of the same words as the scam it warns about, so the extractor reads it
# as the scam unless something tells the two apart. This is the third pass running that a judge has read an
# instruction out of a negated warning, and the mechanism, not the example, is what was wrong both times.
#
# WHY THE OLD GUARD MISSED. It was `RE_NEGATION.search(t[m.start()-60 : m.start()])`: a flat 60-character slice
# of text ending at the match, with the pattern's own `[^.;!?,]{0,60}` refusing to cross a comma. On RBI's own
# awareness text it worked on the first sentence and was never even the right question on the second:
#   "Reserve Bank of India never asks anyone to transfer money to any account."   <- caught, "never" is close
#   "If a caller claims to be from RBI, the police or a court and demands that you move your money to a safe
#    account, it is a fraud."                                                      <- read as MOVE_FD
# The second sentence carries NO negation at all. What makes it not an instruction is that the demand in it is
# somebody ELSE's, reported so that the reader can recognise it. Pass 4 built exactly that guard for the ISSUER
# side ("fraudsters claiming to be from CBI" is not a CBI claim) and never extended it to the instruction side.
# So there are two defects, and both are fixed:
#   1. the negation window is the SENTENCE the match sits in, not 60 characters that stop at a comma. "We will
#      never, under any circumstances, ask you to transfer funds" is the same sentence and now reads as one.
#   2. a clause that reports somebody else's demand does not yield an instruction, with the same vocabulary the
#      issuer guard already uses.
# The cost of (1) is a wider false negative: a threat phrased as a negation in the same sentence ("if you do
# not transfer Rs 10 lakh an arrest warrant will be issued") is suppressed. The 60-character window already
# suppressed that exact sentence, so this is not a new loss, and a false positive here puts money wording on a
# benign customer card while a false negative only leaves the verdict where it was.
RE_NEGATION = re.compile(r"\b(?:never|kabhi nahi|kabhi na|कभी नहीं)\b|\bwill not\b|\bwon'?t\b|\bdoes not\b"
                         r"|\bdoesn'?t\b|\bdo not\b|\bdon'?t\b|\bनहीं\b", re.I)
# Reported speech, instruction side. Same family as RE_REPORTED_CLAIM above; `\b` in front of the stems because
# without it `pos(?:e|ed)` matches inside "imposed" and "disposed" and would silence a real demand in a
# sentence about a penalty.
RE_REPORTED_DEMAND = re.compile(r"\b(?:claim|claims|claiming|claimed|pretend\w*|pos(?:e|es|ing|ed)|purport\w*"
                                r"|impersonat\w*|masquerad\w*|fraudster\w*|scamster\w*|jaalsaaz\w*|ठग\w*)\b", re.I)
_SENTENCE_ENDS = ".;!?।\n"


def _sentence_start(text: str, at: int) -> int:
    """Where the sentence holding offset `at` begins. The window both guards below run in."""
    return max((text.rfind(c, 0, at) for c in _SENTENCE_ENDS), default=-1) + 1


def _not_this_message_asking(text: str, m: re.Match) -> bool:
    """Is this instruction match inside a clause that negates it, or reports somebody else's demand?"""
    before = text[_sentence_start(text, m.start()):m.start()]
    return bool(RE_NEGATION.search(before) or RE_REPORTED_DEMAND.search(before))


# ---------------------------------------------------------------- "you are under digital arrest" (24 Oct)
#
# There is no "digital arrest" in Indian law (I4C advisory TAU/ADV/003), so a message that tells the customer she is
# under one is not from any authority, whoever it names. The arrest_threat cue above fires on any arrest word and
# never counts. This reading is narrower on purpose: the phrase must be ADDRESSED TO HER ("you are under digital
# arrest", "aap digital arrest mein hain", "आप डिजिटल अरेस्ट में हैं"), because bank and I4C awareness messages use the
# same words to say the opposite ("there is no such thing as digital arrest", "if anyone says you are under digital
# arrest, hang up"). R-DIGITAL-ARREST-PAY reads it. A judge's "You are digitally arrested. Transfer all your money
# to me. I am Prime Minister of India" came out GREY before it: no law-enforcement body was named, so no rule fired.
DA_PHRASE = r"digita?l(?:ly)?[\s-]*(?:arr?est(?:ed)?|custody|giraft?ar\w*)"
DA_PHRASE_HI = r"डिजिटल\s*(?:अरेस्ट|गिरफ़?्तार\w*|हिरासत)"
RE_DA_PHRASE = re.compile(rf"{DA_PHRASE}|{DA_PHRASE_HI}", re.I)
RE_DIGITAL_ARREST_TO_YOU = [re.compile(p, re.I) for p in (
    # "you are (now) (placed) under digital arrest", "you have been digitally arrested", "u r under digital arrest"
    rf"\b(?:you|u)(?:'re|re)?\b(?:\s+(?:are|r|have|has|had|been|will|be|being|stand|now|already|hereby|officially))*"
    rf"\s+(?:placed\s+|put\s+|kept\s+|taken\s+)?(?:under\s+|in(?:to)?\s+)?(?:a\s+|the\s+)?{DA_PHRASE}",
    # "we have placed you under digital arrest"
    rf"\b(?:plac\w*|put\w*|kept|keep\w*|tak\w*)\s+(?:you|u)\s+(?:under|in(?:to)?)\s+(?:a\s+|the\s+)?{DA_PHRASE}",
    # "your digital arrest will continue"
    rf"\byour\s+{DA_PHRASE}",
    # "aap digital arrest mein hain", "aapko digitally arrest kiya gaya hai"
    rf"\b(?:aap|aapko|apko|aapka|apka|aap\s+ko|tum|tumhe|tumhein|tumko|tumhara|tujhe)\b[^.!?।\n]{{0,40}}?{DA_PHRASE}",
    # "आप डिजिटल अरेस्ट में हैं", "आपको डिजिटल गिरफ़्तार किया गया है"
    rf"(?:आप|आपको|आपका|तुम|तुम्हें|तुमको|तुम्हारा)[^।.!?\n]{{0,40}}?{DA_PHRASE_HI}",
)]
# What turns the same words into a warning: a condition or a denial before the phrase in its sentence ("if anyone
# says you are ...", "no agency will put you under ..."), or a denial after it ("... is a scam", "... does not exist").
RE_DA_WARNING_BEFORE = re.compile(
    r"\b(?:if|whenever|agar|yadi|jab\s+bhi|beware|aware|awareness|alert|caution|savdhan|saavdhan|nobody|no\s?one"
    r"|no\s+(?:agency|officer|police|government|authority|bank|such|real)|there\s+is\s+no|there'?s\s+no"
    r"|never|will\s+not|won'?t|does\s*n[o']?t|did\s*n[o']?t|koi\s+bhi|kabhi\s+bhi|kabhi\s+nahi)\b"
    r"|अगर|यदि|सावधान|कोई\s*भी|नहीं", re.I)
RE_DA_DENIAL_AFTER = re.compile(
    r"\b(?:is|are|was)\s+(?:a\s+|an\s+|just\s+a\s+)?(?:scam|fraud|fake|hoax|myth|lie|not\s+real)\b|\bdoes\s*n[o']?t\s+exist"
    r"|\bno\s+such\s+thing\b|\bno\s+real\b|\bnever\s+(?:say|says|said|ask|asks)\b|\bnahi\s+hota\b|\bnahin\s+hota\b"
    r"|\bjaisa\s+kuch\s+nahi|जैसा\s*कुछ\s*नहीं|नहीं\s*होता|नहीं\s*है|नहीं\s*कर", re.I)
QUOTE_MARKS = "\"'“‘«"


def _sentence_end(text: str, at: int) -> int:
    ends = [i for i in (text.find(c, at) for c in _SENTENCE_ENDS) if i != -1]
    return min(ends) if ends else len(text)


def is_warning_about(text: str, start: int, end: int) -> bool:
    """Does the sentence around text[start:end] warn about, deny or quote what it names, rather than assert it?

    Not the instruction guard's RE_NEGATION: "do not" and "don't" are how a digital-arrest script talks ("do not tell
    anyone, you are under digital arrest"), so only the negations that deny the arrest itself count here."""
    before = text[_sentence_start(text, start):start]
    after = text[end:_sentence_end(text, end)]
    quoted = start > 0 and text[start - 1] in QUOTE_MARKS          # '"You are under digital arrest" is a scam line'
    return bool(quoted or RE_DA_WARNING_BEFORE.search(before) or RE_REPORTED_DEMAND.search(before)
                or RE_DA_DENIAL_AFTER.search(after))


def digital_arrest_to_you(text: str) -> Optional[re.Match]:
    """The earliest place the message tells the customer she is under "digital arrest", or None."""
    best = None
    for rx in RE_DIGITAL_ARREST_TO_YOU:
        for m in rx.finditer(text):
            if not is_warning_about(text, m.start(), m.end()):
                if best is None or m.start() < best.start():
                    best = m
                break
    return best
RE_URL = re.compile(r"\b(?:https?://)?(?:[a-z0-9-]+\.)+(?:bank\.in|gov\.in|nic\.in|in|com|org|net|co|xyz|online|site|info|link)\b(?:/\S*)?", re.I)
RE_SUMMONS_WORD = re.compile(r"\bsummons?\b|समन", re.I)
RE_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _first(patterns: list[str], text: str) -> Optional[re.Match]:
    best = None
    for p in patterns:
        m = re.search(p, text, re.I)
        if m and (best is None or m.start() < best.start()):
            best = m
    return best


def _is_own_account(text: str, m: re.Match) -> bool:
    """Does the message call this account the customer's (or the sender's) own, in its own words?"""
    return bool(RE_OWN_ACCOUNT.search(text, max(0, m.start() - _OWN_LOOKBACK), m.start()))


def _payee_account(text: str) -> Optional[re.Match]:
    """The first account number in the text that the message does NOT call the customer's own.

    Keyword-led matches first, bare 11-18 digit runs second, which is the order that shipped. A bare run that
    sits inside a possessive keyword match is the same number read a second way, so it is skipped too.

    The cost is real and is the right side to err on: a "safe account" script that says "move your money to YOUR
    new safe account 40900..." loses its payee here. The officer still sees the number in the message, the band
    still says no payee was read, and no rule in the book asserts anything about an account the message
    attributes to the customer herself. Naming her own savings account as the fraudster's is the worse failure.
    """
    own: list[tuple[int, int]] = []
    for m in RE_ACCOUNT.finditer(text):
        if _is_own_account(text, m):
            own.append((m.start(), m.end()))
            continue
        return m
    for m in RE_ACCOUNT_BARE.finditer(text):
        if _is_own_account(text, m) or any(s <= m.start() and m.end() <= e for s, e in own):
            continue
        return m
    return None


_PASSIVE_SET = frozenset(MOVE_PASSIVE)


def _matched_passive(m: re.Match) -> bool:
    """Did this match come from the passive family? Used to scope the credit-direction suppressor to it."""
    return m.re.pattern in _PASSIVE_SET


# A bank's own transaction SMS reports money that already moved, or a setting that already changed: "Rs 5,000
# credited to your A/c by NEFT", "Rs 10,000 debited via IMPS", "Your fund transfer ... is successful", "Your FD
# has been closed prematurely", "Your IMPS limit has been increased". The payment-rail word (NEFT/IMPS/RTGS) or
# the euphemism verb in such a sentence is DESCRIBING a completed transaction, not instructing one. Read as an
# instruction, a genuine Demo Bank SMS reached RED (R-BANK-NEVER-MOVE-FD plus R-BANK-SELF) and the card told the
# customer to stop her own money. This is the active-family twin of RE_CREDIT_TO_CUSTOMER: when a
# completed-transaction marker sits in the same clause as a TRANSFER/MOVE_FD span, that span is a report.
# The markers are past/perfect completions and "is successful" only; the imperative a demand uses ("transfer",
# "close the FD", "move the balance") is deliberately not here, so a two-clause scam ("Rs X debited; now
# transfer to this account 123") keeps its demand, which sits in its own clause with no completion marker.
RE_COMPLETED_TXN = re.compile(
    r"\b(?:credited|debited|is\s+successful|was\s+successful|successful(?:ly)?"
    r"|(?:has|have|had|been)\s+(?:closed|increased|decreased|reduced|processed|reversed|deducted|withdrawn"
    r"|disbursed|settled|liquidated|completed))\b"
    r"|क्रेडिट|डेबिट|सफल\w*", re.I)


# A completion marker does not make a clause a report when the same clause also demands something: "your FD has
# been closed and the amount must be moved to the safe account today" is a demand that opens with a report.
RE_DEMAND_IN_CLAUSE = re.compile(
    r"\b(?:must|should|need\s+to|needs\s+to|have\s+to|has\s+to|please|kindly|immediately|urgently|now|today"
    r"|karein|karen|karo|kijiye|kariye|turant|abhi|jaldi)\b|safe\s+account|सुरक्षित|तुरंत|करें|करो|कीजिए", re.I)


def _reports_completed_txn(text: str, m: re.Match) -> bool:
    """Is this TRANSFER/MOVE_FD match part of the clause that reports a completed transaction, not a demand?

    Scoped to the one clause the match sits in (the sentence bounded by . ; ! ? । or a newline), so a report in
    one clause never silences a demand in another."""
    clause = text[_sentence_start(text, m.start()):_sentence_end(text, m.end())]
    return bool(RE_COMPLETED_TXN.search(clause)) and not RE_DEMAND_IN_CLAUSE.search(clause)


def _first_demand(patterns: list[str], text: str) -> Optional[re.Match]:
    """The earliest match of `patterns` that is not part of a completed-transaction report (see RE_COMPLETED_TXN).

    Same as _first when nothing is a report, so every message without a report clause reads exactly as before."""
    found = sorted((m for p in patterns for m in re.finditer(p, text, re.I)), key=lambda m: m.start())
    return next((m for m in found if not _reports_completed_txn(text, m)), None)


# The bank's bare name is a claim to BE the bank only when it is not somebody's account. "Please transfer 5000 to my
# Demo Bank account" (a mother), "your salary ... to your Demo Bank account" (an employer) and "maine aapke Demo
# Bank account me ... bhej diye" (a relative) name the customer's or the sender's own account, the same bare
# possessive the BANK_SELF table above already refuses for "your bank account". Read as BANK_SELF they gave RED and
# the card told the customer that Demo Bank had sent them. Both halves are required, a possessive before the name and
# an account word after it: the bank itself writes "your Demo Bank debit card ... has been despatched", and that
# signed message must stay MATCHES. A masthead, a sign-off, "from Demo Bank" and "Demo Bank se bol raha hoon" still
# count.
RE_POSSESSIVE_BEFORE = re.compile(
    r"(?:\b(?:your|ur|yr|my|his|her|their|aapk[aei]|apk[aei]|aapk|mer[aei]|tumhar[aei]|tumhe|ter[aei]|apn[aei])"
    r"|आपके|आपका|आपकी|मेरे|मेरा|मेरी|अपने|अपना|अपनी|तुम्हारे|तुम्हारा|तुम्हारी)\s+$", re.I)


RE_ACCOUNT_AFTER = re.compile(r"\s*(?:savings\s+|current\s+|salary\s+)?(?:a/?c\b|acc(?:ou)?n?t\b|accounts?\b|khat[aei]\b"
                              r"|खात[ाे])", re.I)


def _bank_name_claim(patterns: list[str], text: str) -> Optional[re.Match]:
    """The earliest mention of the bank's own name that is not somebody's account ("my Demo Bank account")."""
    found = sorted((m for p in patterns for m in re.finditer(p, text, re.I)), key=lambda m: m.start())
    return next((m for m in found if not (RE_POSSESSIVE_BEFORE.search(text, max(0, m.start() - 24), m.start())
                                          and RE_ACCOUNT_AFTER.match(text, m.end()))), None)


def _span(norm: Normalised, m: re.Match, group: int = 0) -> Span:
    """A span in ORIGINAL coordinates, quoting the original characters. The match ran on the normalised copy;
    storing its offsets directly would point every leader line in the console at the wrong characters."""
    s, e = norm.map_span(m.start(group), m.end(group))
    return Span(text=norm.original[s:e], start=s, end=e)


def _grounded(norm: Normalised, m: re.Match, group: int = 0, value: Optional[str] = None) -> Grounded:
    # The VALUE comes from the normalised text (a folded account number is the number a registry can look up);
    # the SPAN quotes the original.
    return Grounded(value=value if value is not None else m.group(group), span=_span(norm, m, group))


class RulesExtractor:
    """Deterministic extractor. Each field it fills carries the exact substring it came from."""
    name = "rules-1.0"

    def __init__(self, bank_names: tuple[str, ...] = ("Demo Bank",)):
        # The bank's own name counts as a BANK_SELF claim.
        self.bank_patterns = [re.escape(n) for n in bank_names]

    def extract(self, text: str, source: str = "text") -> Claim:
        claim = Claim(source=source, text=text, extractor=self.name)
        # Match on the normalised copy; `claim.text` and every span stay in the original text's coordinates.
        norm = normalise(text, DESPACE_LEXICON)
        t = norm.text
        claim.language_hint = "hi" if RE_DEVANAGARI.search(t) else "en"

        # Issuer: the best-ANCHORED authority wins, not the earliest-mentioned one (see the anchoring block
        # above). A bank-name or RM mention counts as BANK_SELF, and an authority persona outranks it:
        # "CBI says tell your bank it's for a flat" is a CBI claim.
        hits = authority_hits(t)
        m_bank = _first(BANK_SELF_PATTERNS, t)
        m_name = _bank_name_claim(self.bank_patterns, t)
        if m_name is not None and (m_bank is None or m_name.start() < m_bank.start()):
            m_bank = m_name
        chosen = select_issuer(t, hits)
        # An open-set body name that contains the bank's own name is the bank's own unit, and the bank has a
        # better reading of its own name than "a government body": "Demo Bank Loan Recovery Cell, Head Office"
        # is BANK_SELF, which is what lets the outbound-log rule be asked about it at all. Only the open-set net
        # can be overruled this way; an enumerated authority outranks BANK_SELF and still does.
        if (chosen is not None and chosen.issuer is Issuer.OTHER and m_bank is not None
                and chosen.match.start() <= m_bank.start() and m_bank.end() <= chosen.match.end()):
            chosen = None
        if chosen is not None:
            claim.claimed_issuer, claim.issuer_span = chosen.issuer, _span(norm, chosen.match)
        elif m_bank is not None:
            claim.claimed_issuer, claim.issuer_span = Issuer.BANK_SELF, _span(norm, m_bank)
        # Every OTHER authority the message names, with its span. A genuine official communication almost never
        # speaks for two bodies at once; a scam script often does, and an injected prefix always does. Tokens
        # that sit inside the chosen body's own name ("CBI Cyber Cell") are one body, not two.
        for h in hits:
            if chosen is not None and (h.issuer == chosen.issuer or _same_phrase(t, h.match, chosen.match)):
                continue
            claim.other_issuers.append(Grounded(value=h.issuer.value, span=_span(norm, h.match)))
        if m_bank is not None and claim.claimed_issuer != Issuer.BANK_SELF:
            claim.other_issuers.append(Grounded(value=Issuer.BANK_SELF.value, span=_span(norm, m_bank)))
        claim.other_issuers.sort(key=lambda g: g.span.start)

        # Instruction: most specific first (order of INSTRUCTION_KEYWORDS), so "return the excess" beats "transfer".
        for instr, pats in INSTRUCTION_KEYWORDS:
            if instr is Instruction.PAY_CHALLAN and not RE_VEHICLE.search(t):
                continue       # a "challan" with no vehicle or traffic word is a deposit slip or a tax form
            m = _first(pats, t)
            if m and instr in (Instruction.TRANSFER_TO_ACCOUNT, Instruction.MOVE_FD) and _reports_completed_txn(t, m):
                m = _first_demand(pats, t)
            if m and not _not_this_message_asking(t, m):
                # The passive register is blind to direction, so a matured FD, a refund or a salary "required to
                # be remitted to the account specified herein" read as a demand to pay. When the matched clause
                # names the money as something arriving for the customer, the passive does not read. Scoped to
                # the passive family: the active family says "transfer Rs X", which is not how a credit is
                # announced, and widening this to everything would silence real demands that mention a refund.
                if _matched_passive(m) and RE_CREDIT_TO_CUSTOMER.search(t[max(0, m.start() - 40):m.end()]):
                    continue
                claim.instruction, claim.instruction_span = instr, _span(norm, m)
                break

        for ch, pats in CHANNEL_KEYWORDS:
            m = _first(pats, t)
            if m:
                claim.channel, claim.channel_span = ch, _span(norm, m)
                break

        payee = Payee()
        m = _payee_account(t)
        if m:
            payee.account = _grounded(norm, m, 1, re.sub(r"[\s-]", "", m.group(1)))
        m = RE_IFSC.search(t)
        if m:
            payee.ifsc = _grounded(norm, m, 1)
        for m in RE_VPA.finditer(t):
            if re.match(r"\.[a-z]", t[m.end():m.end() + 2], re.I):   # "name@host.com" is an e-mail address, not a UPI ID
                continue
            payee.vpa = _grounded(norm, m, 1, m.group(1).lower())
            break
        for owner, pats in OWNER_KEYWORDS:
            m = _first(pats, t)
            if m:
                payee.claimed_owner, payee.claimed_owner_span = owner, _span(norm, m)
                break
        claim.payee = payee

        ids = DocumentIds()
        claim.mentions_summons = bool(RE_SUMMONS_WORD.search(t))
        m = RE_SUMMONS_NO.search(t)
        if m:
            ids.summons_no = _grounded(norm, m, 1)
        m = RE_PASSCODE.search(t)
        if m:
            ids.passcode = _grounded(norm, m, 1)
        m = RE_CASE_NO.search(t)
        if m and (ids.summons_no is None or m.group(1) != ids.summons_no.value):
            ids.case_no = _grounded(norm, m, 1)
        m = RE_DATE.search(t)
        if m:
            ids.issue_date = _grounded(norm, m, 1)
        claim.document_ids = ids

        for m in RE_AMOUNT.finditer(t):
            claim.amounts.append(_grounded(norm, m))

        for cue, pats in PRESSURE_KEYWORDS.items():
            m = _first(pats, t)
            if m:
                claim.pressure_cues[cue] = _span(norm, m)
        m = digital_arrest_to_you(t)
        if m:
            claim.digital_arrest_span = _span(norm, m)

        m = RE_PHONE.search(t)
        if m:
            claim.caller_number = _grounded(norm, m, 1)
        for m in RE_URL.finditer(t):
            if "@" in t[max(0, m.start() - 1):m.start()]:
                continue
            claim.urls.append(_grounded(norm, m, 0, m.group(0).lower()))
        return claim


def ground(claim: Claim) -> Claim:
    """Drop any field whose quote span is not literally in the text. Used on LLM output; a no-op for RulesExtractor."""
    t = claim.text

    def ok(span: Optional[Span]) -> bool:
        return span is not None and t[span.start:span.end] == span.text

    if claim.issuer_span and not ok(claim.issuer_span):
        claim.claimed_issuer, claim.issuer_span = Issuer.NONE, None
    claim.other_issuers = [g for g in claim.other_issuers if ok(g.span) and g.value in {i.value for i in Issuer}]
    if claim.instruction_span and not ok(claim.instruction_span):
        claim.instruction, claim.instruction_span = Instruction.NONE, None
    if claim.digital_arrest_span and not ok(claim.digital_arrest_span):
        claim.digital_arrest_span = None
    if claim.channel_span and not ok(claim.channel_span):
        claim.channel, claim.channel_span = Channel.UNKNOWN, None
    p = claim.payee
    for f in ("account", "ifsc", "vpa"):
        g = getattr(p, f)
        if g and not ok(g.span):
            setattr(p, f, None)
    if p.claimed_owner_span and not ok(p.claimed_owner_span):
        p.claimed_owner, p.claimed_owner_span = ClaimedOwner.UNKNOWN, None
    d = claim.document_ids
    for f in ("summons_no", "passcode", "issue_date", "case_no"):
        g = getattr(d, f)
        if g and not ok(g.span):
            setattr(d, f, None)
    claim.amounts = [a for a in claim.amounts if ok(a.span)]
    claim.pressure_cues = {k: v for k, v in claim.pressure_cues.items() if ok(v)}
    if claim.caller_number and not ok(claim.caller_number.span):
        claim.caller_number = None
    claim.urls = [u for u in claim.urls if ok(u.span)]
    return claim


def claim_from_picklist(*, issuer: Issuer, instruction: Instruction, channel: Channel = Channel.UNKNOWN,
                        claimed_owner: ClaimedOwner = ClaimedOwner.UNKNOWN, account: str | None = None,
                        ifsc: str | None = None, vpa: str | None = None, pressure: list[str] | None = None,
                        has_passcode: bool | None = None, mentions_summons: bool = False) -> Claim:
    """Claim-only mode: the officer ticks what the customer says she was told. Spans point at the picklist."""
    parts = [f"issuer={issuer.value}", f"instruction={instruction.value}", f"channel={channel.value}", f"owner={claimed_owner.value}"]
    if account:
        parts.append(f"account={account}")
    if ifsc:
        parts.append(f"ifsc={ifsc}")
    if vpa:
        parts.append(f"vpa={vpa}")
    text = "; ".join(parts)

    def g(key: str, value: str) -> Grounded:
        s = text.index(f"{key}={value}")
        return Grounded(value=value, span=Span(text=f"{key}={value}", start=s, end=s + len(key) + 1 + len(value)))

    claim = Claim(source="officer_picklist", text=text, extractor="picklist", claimed_issuer=issuer, instruction=instruction,
                  channel=channel, mentions_summons=mentions_summons)
    claim.issuer_span = g("issuer", issuer.value).span
    claim.instruction_span = g("instruction", instruction.value).span
    claim.payee = Payee(claimed_owner=claimed_owner, claimed_owner_span=g("owner", claimed_owner.value).span,
                        account=g("account", account) if account else None, ifsc=g("ifsc", ifsc) if ifsc else None,
                        vpa=g("vpa", vpa) if vpa else None)
    if has_passcode is False:
        claim.mentions_summons = True
    for cue in pressure or []:
        claim.pressure_cues[cue] = Span(text=cue, start=0, end=0)
    return claim
