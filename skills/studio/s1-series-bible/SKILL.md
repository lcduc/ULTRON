# Stage S1 — Series bible

**Purpose:** define the series once, so every later prompt copies from one source instead of inventing details.
**When:** first gate of a season, before anything is drawn. Revisit only when a new character or location is added.
**Inputs:** the user's idea (one line is enough), plus anything they say about audience and tone.
**Output:** `studio/series/<series-id>/bible.json` (format below), and a short readable summary in the chat for approval.
**Tool:** none; text only.

## What the bible must contain

```json
{
  "series_id": "maple-street",
  "title": "Maple Street",
  "logline": "One sentence: who, what they want, what keeps going wrong.",
  "audience": "Who it is for, e.g. teens and young adults who like light comedy",
  "tone": "3-5 words, e.g. warm, chaotic, sibling comedy",
  "world": "2-3 sentences: where and when it takes place, what is normal there",
  "episode_formula": "The repeatable shape of an episode, e.g. Milo makes a plan, it backfires, Mia saves it in the last shot",
  "hook_rules": ["rules for the first 2 seconds, see below"],
  "running_gags": ["2-4 repeatable jokes or situations"],
  "season_arc": "Optional: one sentence of change across the season",
  "style": {"style_block": "filled at S2", "image_model": "filled at S2", "settings": {}},
  "characters": [
    {
      "id": "milo",
      "name": "Milo",
      "role": "lead",
      "age": 14,
      "personality": ["over-confident", "big-hearted", "always late"],
      "want": "to be seen as grown-up",
      "flaw": "acts before thinking",
      "look_line": "Milo, a 14-year-old boy, slim build, big green eyes, light freckles, messy spiky bright orange hair, plain olive-green hoodie with no print, dark blue jeans, white sneakers with orange laces",
      "silhouette": "spiky hair makes him readable even as a tiny shape",
      "palette": ["bright orange", "olive green", "dark blue"],
      "signature_props": [],
      "voice": {"description": "filled at S4", "ref_clip": "", "settings": {}},
      "masters": []
    }
  ],
  "locations": [
    {
      "id": "maple-street",
      "name": "Maple Street",
      "description_line": "a quiet suburban street of red-brick houses with white window frames, green lawns and young trees, wide grey asphalt road, parked cars along one side",
      "default_time": "morning",
      "light": "low sun from the left of frame, warm",
      "plates": []
    }
  ],
  "props": [],
  "music": {"theme": "filled at S6", "moods": {}}
}
```

## Procedure

1. Ask the user at most three questions if the idea is unclear: who the main character is, what
   kind of humor or emotion, and who the audience is. Otherwise propose and let them correct.
2. Write the logline, tone, world and episode formula first. Show them for approval before
   writing characters.
3. Write 2–4 characters. Each needs a want, a flaw and 3 personality traits that create conflict
   with the others.
4. Write each character's **look line** (see rules). This exact text is pasted into every image and
   video prompt for the rest of the season.
5. Write 2–5 locations with a **description line** and fixed light direction.
6. Save `bible.json` and show a readable summary: logline, formula, one line per character and
   location.

## Rules

1. **Original only.** No real people, brands, existing characters, or names from well-known
   films or series. The series must be ours to monetize.
2. **2–4 main characters.** More cannot be kept consistent on this hardware, and no shot may have
   more than 2 characters.
3. **Distinct silhouettes and colors.** Each character needs one shape feature (hair, build,
   accessory) and one dominant color no other character uses, so viewers and the model can tell
   them apart at phone size.
4. **Look lines: 25–45 words, fixed order:** name, age and build, face (eyes, skin details),
   hair (style, color), top, bottom, shoes, one accessory at most. Clothes are plain: write
   "with no print" or "plain". No text, logos, patterns or tiny details (jewelry, buttons).
5. **One outfit per season.** Changing clothes breaks consistency. Exceptions become a new master
   at S3.
6. **Locations the models can draw.** Prefer simple, readable places (street, kitchen, classroom,
   park, bedroom). Avoid crowds, signs with writing, mirrors, complex machinery.
7. **The formula must repeat.** Viewers arrive at any episode. Each episode stands alone, with a
   light running thread.
8. **Write for muted viewing.** Most Reels start muted. The premise must work as visual comedy or
   emotion; dialogue adds to it.
9. **Hook rules** go in the bible so every episode follows them, for example:
   - The first shot shows a character's face with a strong expression, or an action already in
     motion.
   - Something is wrong or surprising within the first 2 seconds.
   - No slow establishing shots at the start.

## Worked example

Weak idea: "a funny series about a boy."

Strong bible summary (what you show for approval):
- **Logline:** Milo, 14, is desperate to prove he is grown-up, but every plan he makes goes wrong
  in front of his unimpressed older sister Mia.
- **Tone:** warm, chaotic, sibling comedy.
- **Formula:** Milo announces a plan → he starts it with total confidence → it backfires in a
  visual way → Mia reacts or fixes it with one line → final shot: Milo's face.
- **Characters:** Milo (orange spiky hair, olive hoodie: over-confident, always late); Mia
  (17, long black ponytail, mustard-yellow jacket: calm, sarcastic, secretly kind).
- **Locations:** Maple Street (morning, sun from the left); family kitchen (morning, window light
  from the right).
- **Running gags:** Milo's alarm clock; Mia's slow sip of tea before every comment.

## Self-check before asking for approval

- [ ] Every character has want, flaw, 3 traits, look line of 25–45 words in the fixed order.
- [ ] No two characters share a dominant color or silhouette feature.
- [ ] No text, logos or prints in any look line; clothes say "plain" or "with no print".
- [ ] Every location has a description line and a fixed light direction.
- [ ] Nothing is copied from an existing film, series or brand.
- [ ] The episode formula can produce 14 different episodes without new characters.

## Failures and fixes

| Symptom | Cause | Fix | Return to |
|---|---|---|---|
| Characters look alike in images | Similar build, hair or colors | Change one silhouette feature and one color | S1 |
| A character's clothes change between shots | Look line vague ("casual clothes") | Name each garment and its color | S1, then S3 |
| Episodes feel the same | Formula too narrow | Add 2–3 running gags and a second formula variant | S1 |
| Stories need places the model draws badly | Location list too complex | Replace with simpler locations | S1, then S5 |
