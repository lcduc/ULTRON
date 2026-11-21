# Stage E1 — Episode story

**Purpose:** a five-beat story for one 20–30 second episode that can be shot in 4–6 five-second shots.
**When:** first episode gate. Usually done in batches (7–14 stories at once) after the season gates are approved.
**Inputs:** `bible.json` (logline, formula, characters with want/flaw/traits, locations, running gags, hook rules), and the titles of earlier episodes so ideas don't repeat.
**Output:** the `story` field of `studio/series/<series-id>/episodes/<nn-slug>/episode.json`:

```json
"story": {
  "title": "The Shortcut",
  "premise": "One sentence.",
  "beats": {
    "hook": "...", "setup": "...", "turn": "...", "peak": "...", "button": "..."
  },
  "characters": ["milo", "mia"],
  "locations": ["maple-street"],
  "dialogue_draft": [{"speaker": "milo", "line": "..."}]
}
```

**Tool:** none; text only.

## Story formula

| Beat | Time | What it must do |
|---|---|---|
| **Hook** | 0–5 s (shot 1) | Grab attention in the first 2 seconds: a strong expression, an action already happening, or something visibly wrong. Never a calm establishing shot |
| **Setup** | 5–10 s | What the character wants right now, shown through action |
| **Turn** | 10–15 s | The plan goes wrong, or a surprise changes the situation |
| **Peak** | 15–20 s | The biggest visual moment: the backfire, the reveal, the emotional hit |
| **Button** | 20–25 s | A reaction, one line, or a small twist that makes people replay, comment or follow |

Each beat is one sentence describing **what we see**, not what characters think.

## Rules

1. **One idea per episode.** One want, one obstacle, one payoff. 25 seconds has no room for a
   subplot.
2. **Visible, not internal.** Write "Milo sprints, skids, and misses the bus by a centimeter",
   not "Milo feels frustrated". The model can only draw what is visible.
3. **Works muted.** The story must be understood without sound. Dialogue makes it funnier, but
   is not needed to follow it.
4. **Dialogue budget: 40 words per episode, at most 12 words per shot.** Speech runs about 2.5
   words per second; a 5-second shot holds one short line.
5. **At most 2 characters in any beat, and at most 2 talking close-ups per episode.**
6. **Stay inside what the models do well:**
   - Do: walking, running, turning, sitting, falling over, big facial expressions, pointing,
     doors, simple objects held in hand, weather, light changes.
   - Avoid: crowds, text, reading or writing, phones with visible screens, eating with cutlery,
     detailed hand work, fights, two characters hugging or touching for long, vehicles in fast
     motion, mirrors.
7. **Use the bible.** The conflict comes from a character's want or flaw. Use the formula and,
   where it fits, a running gag. Only bible characters and locations.
8. **No repeats.** Check the earlier episode titles and premises; each new story needs a
   different situation or a clear twist on an old one.
9. **The button earns engagement.** End on a face, a reveal, or a line that invites "this is so
   me" comments or a replay. A cliffhanger is fine if the next episode answers it.

## Worked example

Weak: "Milo is late for the bus."

Strong:
- **Title:** The Shortcut
- **Premise:** Late again, Milo takes a "genius" shortcut through the neighbors' gardens to beat the bus.
- **Hook:** Close-up: Milo's eyes snap open, he stares at the camera in horror as morning sun floods the room.
- **Setup:** On Maple Street, the yellow school bus pulls away; Milo points at a gap between two houses and grins.
- **Turn:** He sprints through a garden and a sprinkler switches on, soaking him.
- **Peak:** Dripping, he bursts out of a hedge just as the bus stops right in front of him; the door opens.
- **Button:** Mia, dry, sits by the bus window, takes a slow sip of tea and says "Nice shortcut."
- **Dialogue draft:** Milo: "Shortcut. Genius." (8 words left unused); Mia: "Nice shortcut."

## Self-check before asking for approval

- [ ] Hook shows an action or a strong face within 2 seconds.
- [ ] Every beat is one visible event; no thoughts or feelings without a visible action.
- [ ] Understandable with the sound off.
- [ ] Dialogue at most 40 words, no line over 12 words.
- [ ] Only bible characters and locations; never more than 2 characters in a beat.
- [ ] Nothing from the "avoid" list.
- [ ] Not a repeat of an earlier episode.

## Failures and fixes

| Symptom | Cause | Fix | Return to |
|---|---|---|---|
| Viewers swipe away in the first seconds | Slow hook | Start in the middle of the action or on a strong face | E1 |
| Story unclear without sound | Plot carried by dialogue | Replace a line with a visible action | E1 |
| A shot needs something the model can't draw | Beat uses an "avoid" item | Rewrite the beat around a doable action | E1 |
| Episodes blur together | Same formula beats every time | Use a different running gag or formula variant | E1, or S1 to add gags |
