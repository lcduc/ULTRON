# Stage E6 — Post pack

**Purpose:** everything needed to upload the finished episode: cover image, caption, hashtags, alt text.
**When:** after the user approves the final video (E5).
**Inputs:** the final video; `episode.json` (story, shots, dialogue); `bible.json` (title, logline, characters); captions of earlier posts, to avoid repetition.
**Output:** `episodes/<nn-slug>/post/` containing `cover.png` (1080×1920) and `post.md`:

```markdown
# Cover
cover.png — from shot 4, frame 40

# Caption
<hook line>

<1-2 short lines of context or a joke>

<question that invites comments>

Episode 7 of Maple Street. Follow for the next one.

#hashtag1 #hashtag2 #hashtag3 #hashtag4

# Alt text
<one sentence describing the video for screen readers>

# Upload checklist
- AI label: on
```

**Tool:** cover frame taken from the final video (E5 tools); text written by the model.

## Cover image

1. **Prefer a frame from the episode** (the peak or button shot) where a face shows a strong,
   readable expression. Pick the frame, don't generate a new image, so the cover matches the video.
2. If no frame works, make one with `qwen_edit` from the character master, using the E3 keyframe
   formula, with the character's face large in the top half of the frame.
3. **No text in the image.** If the user wants a title on the cover, it is added later as a text
   overlay in E5 tooling, never drawn by the image model.
4. Keep the face and key action in the center area: Instagram crops covers to a square-ish tile
   on the profile grid **[verify current crop]**.

## Caption formula

| Part | Rule |
|---|---|
| **Hook line** | First line, under 80 characters. It must make sense before the "more" cut: a relatable statement, a question, or the situation in a few words. No hashtags, no episode number here |
| **Context** | 1–2 short lines. Adds a joke or the character's point of view. Use character names |
| **Comment prompt** | One question viewers can answer in a word: "Team Milo or team Mia?", "What would you have done?" |
| **Series line** | "Episode N of <title>. Follow for the next one." |
| **Hashtags** | 3–5 relevant tags at the end: one for the series, 1–2 for the format (animation, short film), 1–2 for the topic of the episode. No banned or unrelated trending tags **[verify current Instagram guidance on hashtag count]** |

## Rules

1. **Honest and specific.** The caption describes this episode. No clickbait the video does not
   deliver.
2. **No repetition.** Compare with the last 10 captions; change the hook structure and question.
3. **Short lines, plain English,** at most one emoji per line, none in the hook if it hurts clarity.
4. **Turn on Instagram's AI label** when uploading (the "AI info" setting). Say so in the upload
   checklist. Hiding AI use risks reach and the account.
5. **No other creators' names, characters or audio** in captions or tags.
6. **Alt text** describes what happens in one plain sentence.

## Worked example

Weak: "Milo is late again lol #animation #funny #viral #fyp #explore #reels"

Strong:

```
Me thinking I found a faster way to school:

Milo's shortcut was 100% genius. The sprinkler did not agree.

Have you ever been saved by the person you were trying to impress?

Episode 7 of Maple Street. Follow for the next one.

#maplestreetseries #3danimation #animatedshort #siblings #schoolmornings
```

Alt text: "An animated boy with orange hair runs through gardens to catch his school bus, gets soaked by a sprinkler, and finds his sister already on board."

## Self-check before asking for approval

- [ ] Cover is a real frame from the episode (or a matching keyframe), face readable at thumbnail size, no text drawn in it.
- [ ] Hook line under 80 characters and understandable alone.
- [ ] One comment question; series line present.
- [ ] 3–5 relevant hashtags, no unrelated trending tags.
- [ ] Not a repeat of a recent caption.
- [ ] Alt text present; AI label reminder in the checklist.

## Failures and fixes

| Symptom | Cause | Fix | Return to |
|---|---|---|---|
| Cover face unreadable on the grid | Frame too wide or mid-motion blur | Pick a closer, still frame; or make a cover keyframe | E6 (or E3) |
| Few comments | No question, or a hard one | Ask a one-word, opinion-style question | E6 |
| Captions all sound the same | Same hook structure | Rotate: statement, question, "POV:", quote of a line | E6 |
