# Ultron: a structured morning and evening briefing, saved as a chat

Plan date: 2026-11-22, updated with your answers the same day. Builds on [PLAN-ASSISTANT.md](PLAN-ASSISTANT.md) (the briefing job and pushes) and uses the JSON output tested in [PLAN-ONE-MODEL.md](PLAN-ONE-MODEL.md).
Items marked **[verify]** are untested on this PC.

## 1. Goal

- **06:00 and 21:00** pushes that look the same every day: a greeting, then labeled lines in a fixed order.
- **Tapping the push opens an Ultron chat** that already holds the full briefing, so you can reply there ("move the dentist to Friday").
- **Ultron speaks as your butler** in every chat, not only in briefings: it calls you "sir", in the manner of Alfred or JARVIS.

**Today's briefing** (`services/assistant-cron/briefing.py`):
- The model writes "at most 6 short lines". The order, labels and wording change daily, and the model can drift from the facts.
- Tapping the push opens an empty new chat.

## 2. Who writes what

Same rule as before: **code runs the workflow, and the model does narrow jobs with JSON output.**

| Part | Written by |
|---|---|
| Greeting (1 sentence, different each day, butler tone) | Model |
| Clothing tip (1 short sentence from the weather, e.g. "A light coat should do, sir; it's breezy.") | Model |
| Which unread mails matter, which news headlines to show | Model, as IDs. Code copies the text word for word |
| Every other line: schedule, weather facts, mail and news text, order, limits, fitting the push | Code |

One model call returns:

```json
{"greeting": "Good morning, sir. A busy day ahead, I'm afraid.",
 "clothing_tip": "Rain is likely; do take the raincoat, sir.",
 "important_mail": ["m1", "m4"],
 "news": ["n2", "n5"]}
```

- Enforced by a JSON schema. Greeting ≤ 140 characters and tip ≤ 100, one line each, plain text.
- Unknown IDs or a bad answer get one retry. After that, the fallbacks in §3 take over.
- The briefing call carries the same butler persona as the chats (from `config.yaml`, since this job calls the gateway directly, not Open WebUI).

## 3. The push

### Morning, 06:00 (covers today)

```
Good morning, sir. A rather full day, I'm afraid.
TODAY: 09:30 Dentist · 14:00 Team sync · Pay electricity (overdue) · Send report · +2 more
WEATHER: Hanoi 18-24 C, rain 70%, wind 20 km/h. Do take the raincoat, sir.
MAIL: An Nguyen: contract draft · Bank: statement (2 of 9 unread)
NEWS: headline · headline · headline
```

### Evening, 21:00 (covers tomorrow)

```
Good evening, sir. Tomorrow looks gentle.
TOMORROW: 08:00 Flight check-in · 12:30 Lunch with Minh · Renew visa form
WEATHER: Hanoi 20-27 C, dry, wind 10 km/h. Light clothes will do, sir.
```

### Line rules

| Line | Content | Push limit | When empty |
|---|---|---|---|
| Greeting | From the model | 1 line | Fallback "Good morning, sir." / "Good evening, sir." |
| TODAY / TOMORROW | **One list** of events and tasks: overdue tasks (marked `(overdue)`), all-day events, timed events by time `HH:MM Title`, then tasks due that day | 6 items, then `+N more` | `TODAY: nothing scheduled, sir` |
| WEATHER | Condition, min-max temperature, rain chance, wind, then the clothing tip | 1 line | — |
| MAIL (morning) | `Sender: subject` for the picked mails, plus `(x of y unread)` | 3 mails | `MAIL: nothing important (y unread)`; left out with no unread mail |
| NEWS (morning) | Headlines picked from two searches: **politics** (wars, elections, world affairs) and **economy** (gold, stocks, crypto, markets) | 3, each ≤ 60 characters | Left out |
| UNAVAILABLE | Sections that failed: `UNAVAILABLE: News, Mail` | 1 line, always last | Left out |

Format: separator ` · `, titles cut at ~40 characters with `…`, plain text (no Markdown, no emoji), Vietnamese characters kept.

**Fitting the 600-character push:** code drops from the bottom until it fits: NEWS → `+N more` items → MAIL senders cut shorter. The greeting, schedule and weather stay.

### Fallbacks (model gone for `model_wait_minutes`, or two bad answers)

- **Greeting:** "Good morning, sir." / "Good evening, sir."
- **Clothing tip:** code rules: rain ≥ 50% "Take a raincoat, sir."; min ≤ 15 C "A warm coat, sir."; wind ≥ 25 km/h "A light jacket for the wind, sir."; max ≥ 33 C "Dress light, sir."; otherwise none.
- **Mail:** the first 3 unread mails whose sender doesn't look automatic (`noreply`, `no-reply`, `newsletter`, `notifications`, `marketing`).
- **News:** the first result of each search, then the next ones, up to 3.

## 4. The briefing chat

1. Code builds a **Markdown version** with fixed sections:
   - the greeting;
   - **Schedule**: every event and task, with times and locations;
   - **Weather**: the facts and the clothing tip;
   - **Mail** (morning): the picked mails with one line from the snippet, then the count of the rest;
   - **News** (morning): up to 6 headlines with source and link;
   - **Unavailable** sections, if any.
2. The job **creates the chat through the Open WebUI API**: model `ultron`, title `Briefing · Mon 23 Nov · morning`, a short user line ("Morning briefing") followed by the briefing as Ultron's answer. This needs `ULTRON_API_KEY` in the `assistant-cron` container. The working flow is in `logs/one-model-tests/chatflow.py`.
3. The **push link** goes to that chat (`/c/<id>`). If creating the chat fails, the push still goes out with today's link (`/?models=ultron`). Links still open in Safari on iPhone.
4. Your **replies** in that chat use `ultron` with its normal tools (calendar, tasks, mail, memory) **[verify]**, and the briefing is already in the conversation.
5. **Retention:** briefing chats older than **7 days** are deleted by the job on each run. Only chats whose title starts with `Briefing ·` are touched.

## 5. The butler persona (all Ultron chats)

The profile block (`compose/profile.md`, applied by `scripts/apply-profile.py` to `ultron`, `ultron-think` and `ultron-agent`) gets a role section in place of "casual, short and direct":
- You are Ultron, the user's personal AI assistant, and you speak like a loyal, composed butler, in the manner of Alfred or JARVIS: polite, warm, with a touch of dry wit.
- Address the user as "sir", and now and then "Master Duc".
- Stay brief: the answer first, details only if asked.

This touches only Open WebUI's prompts. The chess-coach app calls the model server directly and is not affected.

## 6. Build steps

A subagent builds this from a precise brief; I review the diff and the outputs.

1. **Refactor `briefing.py`.** Sections return data, not text. New `render_push()`, `render_chat()`, `model_picks()` (JSON schema, length and ID checks, one retry) and `fallback_picks()`. Config gains `limits:`, `persona:`, `news_queries:` and `chat_retention_days: 7`; the morning time becomes `"06:00"`. Weather adds wind.
2. **News search.** The search returned nothing on 2026-11-22. Find out why (SearXNG engines or categories) and make both queries return results.
3. **Briefing chat.** Create, link and clean up as in §4. Add `ULTRON_API_KEY` and the Open WebUI address to the container in `compose/docker-compose.yml`.
4. **Fixture runs.** `--fixture <file>` feeds fake section data, so the layout can be tested with nothing fetched or sent. Fixtures in `services/assistant-cron/fixtures/`: an empty day, a busy day (10 events, 8 tasks, 15 mails, 12 headlines), every section failed, long and Vietnamese titles, an evening run.
5. **Checks** with `--dry-run`: every fixture with the model on and off; the push ≤ 600 characters with the right line order; mail and news text only from the input; 10 busy-day runs with valid IDs and greeting and tip within limits.
6. **Persona** (§5), then re-apply the profile.
7. **One real dry run** on your data, with a real briefing chat created in Open WebUI but no push sent. I check it against the raw sections and open the chat.
8. **One real push** to your phone, with your OK. You check the lock screen, the expanded view and the tap into the chat **[verify: how many lines iOS shows before expanding]**.
9. **Docs**: README "Morning briefing and phone pushes" and the profile section.

## 7. What stays the same

- Quiet days, the section switches, city, channel and the email fallback (`config.yaml`).
- A failed section never stops the briefing.
- The model is waited for up to 30 minutes, then the fallbacks are used.
- One short model call per briefing.

## 8. Risks

| Risk | Handling |
|---|---|
| A greeting or tip that is odd or too long | Length checks, one retry, then the fixed fallback |
| Important mail missed | `(x of y unread)` always shows more exists; the chat lists the count |
| iOS cuts the push before expanding | Greeting and schedule come first |
| The news search returns nothing | One `UNAVAILABLE: News` line; step 2 fixes the cause |
| Creating the chat fails | The push still goes out, with the old link |
| The butler tone wears thin | It's one block in `compose/profile.md`; edit and re-run `apply-profile.py` |

## 9. Out of scope

- The AI papers digest (PLAN-DIGEST.md): a separate, larger workflow, saved for later.
- Live prices (gold, VN-Index, BTC) as numbers; news headlines only for now.
- Vietnamese voice, and reading the briefing aloud.
