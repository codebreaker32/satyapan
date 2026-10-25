# Satyapan on Telegram

A citizen forwards a suspicious voice note, video, photo of a notice, PDF or text to the bot. The bot asks for consent
once, sends the message to Satyapan's engine and replies with RED, AMBER or GREY, up to three plain reasons and one
line that is always there: "Verify only through the official channel. If money has already been sent, call 1930 or
report at cybercrime.gov.in." There is no GREEN and never a score. The design rules are in `docs/architecture.md`,
section 3.

The bot uses only Python's standard library and talks to two things: the Telegram Bot API (free, no key beyond the
bot token) and its own engine on `127.0.0.1:8100`, never the demo's engine on 8000.

## Set up (once)

1. In Telegram, open @BotFather, send `/newbot`, pick a name and a username ending in `bot`. BotFather answers with
   the bot's token.
2. Save the token where only you can read it. Paste it at the prompt (nothing is shown) and press Enter:

   ```bash
   read -rs T && install -m 600 /dev/null ~/.config/satyapan_tg_token && printf %s "$T" > ~/.config/satyapan_tg_token
   ```

   (`mkdir -p ~/.config` first if the folder does not exist.) The bot refuses to start if the file is missing, is not
   a token, or can be read by group or others. `SATYAPAN_TG_TOKEN_FILE=/path/to/file` points it at another file.
   Never paste the token into a chat, a commit or a log.
3. Check it: `python3 -m bot --check-token` (from the repository root) says whether the file is in place and private.

## Run

```bash
scripts/run_tg_bot.sh
```

It starts the bot's own engine from this checkout's `prototype/` on port 8100, then the bot in the foreground. If the
forensics service answers on `127.0.0.1:8765` (started by `scripts/demo_up.sh`), voice and face checks run;
otherwise only the instruction rules run, and the script says so. Logs: `clips/logs/tg-engine.log` and
`clips/logs/tg-bot.log`. Stop with Ctrl-C: the check in progress finishes, anyone still waiting is told the service
stopped, and the engine started by the script stops too.

**On the laptop.** The engine's environment is found as in `scripts/demo_up.sh` (`SATYAPAN_ENGINE_VENV`, else
`../satyapan/.venv`, else `prototype/.venv`). The bot's engine is a second engine process next to the demo's and
loads its own speech-to-text model; on the 7.3 GB team laptop start it with `SATYAPAN_WHISPER_MODEL=small` or stop the
demo first.

**On the AWS workbox** (ap-south-1), inside tmux so it keeps running after you log out:

```bash
cd ~/work/raksham/satyapan-finale      # the checkout that has bot/
tmux new -s tgbot scripts/run_tg_bot.sh
```

Detach with Ctrl-b then d; come back with `tmux attach -t tgbot`; stop with Ctrl-C inside it. If that checkout has
no `prototype/.venv`, add `SATYAPAN_ENGINE_VENV=/path/to/venv` before the script. Port 8100 must be free (the script
refuses to reuse whatever is there); `SATYAPAN_BOT_ENGINE_PORT` picks another.

Only one copy of the bot may poll Telegram at a time. A second copy, or a webhook set on the bot, makes Telegram
answer 409, and the log says so.

## What a citizen can send

- Commands: `/start` (consent), `/hindi` and `/english` (reply language; also the language a voice note is read in),
  `/stop` (withdraw consent and forget the chat), `/help`.
- Checked: a voice note or audio file, a video or round video message, a photo of a notice, a PDF or an image sent as
  a file, plain text pasted or forwarded. Anything else (stickers, GIFs, contacts, locations, other files) gets a
  sentence listing what works.
- The reply language starts as Hindi when the phone's Telegram language is Hindi, else English.

## Privacy

- **Consent first.** The first message gets a consent text in Hindi and English with Yes and No buttons. Nothing is
  checked and nothing of the message is kept until the citizen presses Yes. `/stop` withdraws it.
- **Where a file goes.** Telegram's servers hold it, as for any Telegram chat (bot chats are not end-to-end
  encrypted). The bot downloads it to `~/.local/share/satyapan-bot/incoming/<case id>/` (a folder only this user can
  open) and uploads it to its own engine on 127.0.0.1, which keeps a copy in `prototype/evidence/uploads/<case id>/`
  during the check. After the reply is sent, both are deleted. A check cut short by a crash is cleaned up at the next
  start (`pending-cleanup.json` holds the case ids until then).
- **What is kept.** In `~/.local/share/satyapan-bot/chats.json` (mode 600): per chat id, whether consent was given,
  when, and the chosen language. In `clips/logs/tg-bot.log` (mode 600): one line per check with the case id, the
  file's sha256 and the verdict. No message text, transcript, score, name or user id is logged.
- **What the engine holds in memory.** The bot's engine keeps each case, transcript included, in memory until it
  stops; it has no delete call. It serves only 127.0.0.1, and `run_tg_bot.sh` stops it together with the bot.
- **Where it runs.** On the laptop, or on the team's AWS workbox in ap-south-1 (Mumbai). No paid service, no other
  network call: the website check uses its recorded answers (`SATYAPAN_LIVE_WEB=0`) and the offline helper reader is
  off.

## Limits

- 10 checks per user per hour, counted in memory (a restart starts everyone afresh); the 11th gets a polite message
  saying when to try again.
- Files up to 20 MB, the most a Telegram bot can download. Recordings up to 5 minutes.
- One check at a time, in arrival order; everyone gets "Checking… a video can take up to a minute" at once.
- Private chats only. In a group the bot answers `/start` and `/help` with a request to message it directly.
- **The verdict comes from the officer engine, bank mocks included.** The engine runs with the demo bank's labelled
  mock records (beneficiary name look-up, outbound log, ledger, I4C suspect registry, ED verify-summon). The bot never
  shows a reason that rests on them, but the colour can still lean on them: in the end-to-end test a Hindi
  digital-arrest text was RED from an issuer rule plus the mocked beneficiary look-up. An engine mode with those
  look-ups off would make a citizen's RED rest only on issuer rules, forensics and campaign memory, as the design asks;
  it is not built.
- A hackathon prototype: the consent text tells the citizen to treat the answer as a warning, not as proof.

## Tests

```bash
python -m pytest -q tests/test_tg_bot.py          # a fake Telegram API and a stub engine, both local
python3 scripts/tg_bot_e2e.py VOICE_NOTE.ogg      # run_tg_bot.sh for real, with the fake Telegram API
```

Neither test talks to api.telegram.org.
