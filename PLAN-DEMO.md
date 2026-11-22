# Ultron: a demo video

Plan date: 2026-11-22. Tool: [brag](https://github.com/latent-spaces/brag), the same tool you used for the automatic-octo-computing-machines demo.
Decisions (2026-11-22): landscape 16:9; the other §7 defaults accepted (no voiceover, calm butler tone without film names, fake calendar tool for scene 3, video goes in `docs/assets/` after approval).

## 1. What brag makes

- A **15–25 second launch video** with motion, music and share copy, made by the agent from the project itself.
- On Opus 5.5 / Sonnet 5.5, `/brag` hands off to **`/brag-slim`**: one skill file, no Hyperframes, no Node needed. It builds the visuals from the project's real UI and assets, writes its own soundtrack, and renders with ffmpeg (installed here).
- Output: `brag-output/` with `brag-plan.md` (storyboard), the share copy, `brag.mp4` and `brag.jpg` (poster).
- It's not a screen recording: it animates the real interface. So the material has to exist as real screens first (§3).

## 2. The story

**Angle:** a private butler-assistant that runs entirely on your own PC.

| # | Scene | ~s | Source |
|---|---|---|---|
| 1 | **Hook:** an iPhone lock screen at 06:00, the push "Good morning, sir. A rather full day…" | 3 | The real push text from a fake-day briefing |
| 2 | Tap → the briefing chat opens: schedule, weather with the clothing tip, mail, news | 4 | The real Open WebUI chat, demo data |
| 3 | Reply "Move the dentist to Friday" → "Done, sir. Friday at 09:30." | 4 | A real reply on demo data |
| 4 | Voice call: waveform, "Good evening, sir" | 3 | The call screen |
| 5 | A photo question (vision) and a quick agent task | 3 | Real replies, demo data |
| 6 | **Punchline:** "One model. Your PC. Nothing leaves the house." + Ultron logo | 3 | The showcase page style (`docs/index.html`) |

brag decides the final cut, timing and music; this table is its brief.

## 3. Demo data, so nothing personal shows

The video is made to be shared, so **none of your real events, mail, name or profile appear in it.**

1. **A demo user in Open WebUI** ("Alex", fictional) with its own API key and a fictional profile block. Your account and chats stay untouched.
2. **A demo calendar and to-do list:** the busy-day fixture from the briefing (`services/assistant-cron/fixtures/busy-day.json`), already fictional.
3. **The briefing chat** created for the demo user from that fixture (`--fixture --dry-run --chat`, run with the demo user's key). Nothing is pushed.
4. **Replies in scenes 3 and 5** are real model answers in the demo user's chats. Scene 3 must not touch your real Google calendar: the demo user gets **no Google tools**, and the reply comes from a small fake calendar tool, or the move is shown as a planned action **[decide]**.
5. **Screens** are captured with a headless browser at the video's size, then given to brag as real UI to animate.
6. **The lock-screen push** is drawn from the real push text (the iPhone frame is a mock-up).
7. Before the render I check every scene still for real names, addresses, keys, hostnames or the Tailscale URL.

## 4. Before filming

- **Tomorrow's 06:00 briefing:** you confirm the push and the tap into the chat look right. Any fixes land before filming, so the video shows what really works.
- **One voice call from your iPhone.** It hasn't been tried on the phone since the switch to one model.

## 5. Steps

| # | Step | Who |
|---|---|---|
| 1 | Install `/brag-slim`: copy `skills/brag-slim/` from the repo into `~/.claude/skills/` (one file, no scripts run). Needs your OK to download | Me |
| 2 | Demo user, fictional profile, demo briefing chat, demo replies (§3) | Subagent |
| 3 | Capture the screens at the video's size; draw the lock-screen push | Subagent |
| 4 | Run `/brag-slim` in the repo with §2 as the brief and the screens as material | Subagent on Sonnet 5.5, to save tokens |
| 5 | Review the storyboard, stills from every scene, and the privacy check (§3.7) | Me |
| 6 | Render `brag.mp4`; you watch it and ask for changes | You |
| 7 | Keep or delete the demo user. `brag-output/` goes in `.gitignore` unless you want the video in the repo | You decide |

## 6. Risks

| Risk | Handling |
|---|---|
| Real data leaks into a frame | Demo user only, plus the still check before rendering |
| The demo shows something that doesn't work yet | §4 first; every reply in the video is a real model answer |
| Open WebUI screens look generic | brag adds the motion and type; the briefing push and butler lines carry the identity |
| Token cost of a full brag run | Run it on Sonnet 5.5 in a subagent; I review only the plan and stills |

## 7. Open questions

| # | Question | Default if you don't say |
|---|---|---|
| 1 | Where will it be posted? Vertical 9:16 (Reels, TikTok, Shorts) or landscape 16:9 (GitHub, LinkedIn, X)? | **Decided 2026-11-22: landscape 1920×1080** |
| 2 | Voiceover? brag can narrate with Kokoro, which already runs on this PC | Off: music and on-screen text |
| 3 | Tone? | Calm and dry, like the butler. No film character names in a public video (JARVIS, Alfred): "your own butler, on your own PC" |
| 4 | Scene 3: a fake calendar tool for a real "Done, sir", or show the move as planned? | Fake calendar tool |
| 5 | Put the video in the repo (README, showcase page)? | Yes, `docs/assets/`, after you approve it |
