# Skill: Studio (animated story series pipeline)

Use this skill for any work on the animated series: planning a season, writing an episode, making
images, video, voices or music for it, or finishing and posting it. The full design is in
`PLAN-STUDIO.md` in the Ultron repository; this file is the working summary.

## How to use the stage skills

The pipeline is a fixed sequence of gates. Each gate has its own skill file. Before doing a gate,
read its file completely and follow it.

| Gate | Skill file | Produces |
|---|---|---|
| S1 Series bible | `s1-series-bible/SKILL.md` | `bible.json`: premise, characters, world, tone, episode formula |
| S2 Style lock | `s2-style-lock/SKILL.md` | The style block and image settings |
| S3 Character masters | `s3-character-masters/SKILL.md` | Full-body reference images per character |
| S4 Voices | `s4-voices/SKILL.md` | One reference voice clip per character |
| S5 Locations and props | `s5-locations-props/SKILL.md` | Empty location plates, prop masters |
| S6 Music palette | `s6-music/SKILL.md` | Theme track and mood variants |
| E1 Story | `e1-story/SKILL.md` | Five-beat episode story |
| E2 Script and shotlist | `e2-shotlist/SKILL.md` | `episode.json` shot table with dialogue |
| E3 Keyframes | `e3-keyframes/SKILL.md` | One start image per shot |
| E4 Animation | `e4-animation/SKILL.md` | One 5-second clip per shot, lip-sync where marked |
| E5 Finishing | `e5-finishing/SKILL.md` | Final 1080×1920 video with music and captions |
| E6 Post pack | `e6-post-pack/SKILL.md` | Cover image, caption, hashtags |

Season gates (S) are done once per season. Episode gates (E) are done for every episode.

## Rules for every gate

1. **One gate at a time.** Do not start a gate until the user has approved the one before it.
   Show the result, ask for approval, and stop.
2. **Repair, don't re-roll.** When the user rejects part of a result, redo only that part
   (one shot, one image, one line), and keep the rest.
3. **The bible is the source of truth.** Character looks, the style block, location
   descriptions and voice settings come from `bible.json`. Copy them word for word. Never
   paraphrase, shorten or "improve" them inside a prompt.
4. **Prompts are long and specific.** A one-line prompt is never acceptable for images or video.
   Each stage skill gives a prompt formula with slots; fill every slot.
5. **Negative prompts do nothing on the fast templates.** `qwen_edit` and `wan22_i2v` run at
   CFG 1.0, where ComfyUI ignores the negative prompt. Write what you want in the positive prompt
   ("plain light-grey background", "clean fabric with no print") instead of relying on the
   negative prompt to remove it.
6. **No text anywhere in images.** Models garble letters ("SCHOK BUS"). No logos or prints on
   clothes, no signs, no writing on screens or books. Captions are added in E5, not in images.
7. **Shots are 81 frames (5 seconds at 16 fps).** 49-frame clips were judged not smooth enough.
8. **The keyframe decides the action.** The video model keeps the pose, facing and framing of
   the start image. A character who must run left in the shot must already face and lean left in
   the keyframe.
9. **English for all prompts and dialogue.**
10. **Record what you made.** For every generated file, keep the prompt, seed and template next
    to it, so it can be remade exactly.

## Writing a prompt: the shared method

Every image or video prompt is assembled from blocks in this order. The stage skills say which
blocks apply and give the exact formula.

1. **Style block:** from the bible, word for word.
2. **Shot framing:** shot size and angle ("medium-wide shot, eye level, vertical 9:16 frame").
3. **Character block(s):** each character's look line from the bible, word for word, plus
   their pose, expression and position in frame for this shot.
4. **Setting:** the location's description from the bible, plus time of day and weather.
5. **Action or motion:** what happens (video: in time order, with speed and direction).
6. **Camera:** movement for video (static, slow push-in, tracking left), lens feel for stills.
7. **Light and color:** direction and quality of light, mood.
8. **Exclusions written positively:** "plain hoodie with no print", "empty street, no other
   people", "no text".

Use concrete visual nouns and verbs. Avoid abstract words that cannot be drawn ("beautiful",
"epic", "amazing"). Say how things look, not how they feel.

## Example cast used in the skill files

The stage skills use one test series in their examples, so the prompts can be compared:

- **Style block:** "3D animated feature film still, stylized cartoon proportions, large
  expressive eyes, soft rounded shapes, smooth clean materials, warm soft global illumination,
  gentle shadows, rich saturated colors, simple clean textures, shallow depth of field"
- **Milo** (look line): "Milo, a 14-year-old boy, slim build, big green eyes, light freckles,
  messy spiky bright orange hair, plain olive-green hoodie with no print, dark blue jeans,
  white sneakers with orange laces"
- **Maple Street** (location): "a quiet suburban street of red-brick houses with white window
  frames, green lawns and young trees, wide grey asphalt road, parked cars along one side"

These are examples only. The real series comes from gate S1.

## Tools

Image and video jobs go through the ComfyUI skill: `skills/comfyui/SKILL.md`. Run one job at a
time; each job unloads the chat model until it finishes.
