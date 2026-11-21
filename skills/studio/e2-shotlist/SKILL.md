# Stage E2 — Script and shotlist

**Purpose:** turn the approved story into an exact shot table that the keyframe (E3), animation (E4) and finishing (E5) gates can execute without guessing.
**When:** after the user approves E1 for this episode.
**Inputs:** `episode.json` → `story`; `bible.json` → characters (look lines, traits), locations (description lines, light), hook rules.
**Output:** the `shots` array in `episode.json` (format below), and a readable table in the chat for approval.
**Tool:** none; text only. E3 and E4 turn each shot into prompts.

## Shot format

```json
"shots": [
  {
    "id": 1,
    "beat": "hook",
    "seconds": 5,
    "location": "milo-bedroom",
    "time_of_day": "morning",
    "characters": ["milo"],
    "framing": "close-up, eye level",
    "composition": "Milo's face fills the lower two thirds of the vertical frame, centered, looking straight into the lens",
    "start_pose": "Milo lies in bed on his back, eyes closed, mouth slightly open, blanket up to his chin, morning sun across the pillow",
    "action": "0-1 s still asleep; 1-2 s eyes snap open; 2-5 s he lifts his head, stares into the lens in horror, mouth opening wide",
    "camera": "static, then a fast small push-in during the stare",
    "light": "warm morning sun from the window on the left of frame",
    "dialogue": [{"speaker": "milo", "line": "No, no, no.", "emotion": "panic", "mouth_on_screen": true}],
    "lipsync": true,
    "sound": "alarm clock ringing, then silence",
    "transition_out": "hard cut",
    "continuity": "shot 2 starts with Milo already outside, dressed"
  }
]
```

`keyframe_prompt` and `motion_prompt` are added per shot later by E3 and E4.

## How to build the shotlist

1. **Count shots:** 4–6 shots of exactly 5 seconds (81 frames). One beat usually gets one shot;
   the peak may get two.
2. **For each shot, decide the camera first:** framing (shot size + angle), then composition
   (where each character is in the 9:16 frame and which way they face).
3. **Write the start pose:** exactly what the first frame shows. This becomes the keyframe.
   It must already lead into the action (facing, lean, hand position).
4. **Write the action in time order with seconds** (`0-2 s ..., 2-5 s ...`). One main action per
   shot, with at most one secondary motion (hair, cloth, background).
5. **Add dialogue** from the story draft. Mark `mouth_on_screen` and `lipsync` (at most 2 shots).
6. **Check continuity** between shots: screen direction, light, clothes, props in hand.

## Rules

1. **Exactly 5 seconds per shot.** The edit (E5) may trim, but every shot is rendered at 81 frames.
2. **Vertical frame thinking.** Characters stand tall in the frame; prefer close-ups, medium
   shots and full-body shots over wide landscapes, which become tiny on a phone.
3. **Vary shot sizes.** No two consecutive shots with the same framing. A typical episode moves
   close-up → wide → medium → close-up.
4. **Screen direction is fixed.** If Milo runs left-to-right in shot 2, he keeps running left-to-right
   in shot 3. A character facing the camera cannot "run toward" something behind them; set up the
   facing in `start_pose`.
5. **One main action per shot,** described as physical motion with speed and direction ("sprints
   from frame left to frame right"), never as intent ("tries to catch the bus").
6. **Camera moves are simple:** static, slow push-in, slow pull-out, pan left/right, tracking
   alongside, tilt up/down, handheld shake. One move per shot.
7. **Lip-sync only where it pays:** at most 2 shots, each a close-up or medium close-up with the
   speaker facing the camera or three-quarter. Every other line is spoken off-screen, from behind,
   or over a reaction shot (`mouth_on_screen: false`).
8. **Max 2 characters per shot,** and avoid physical contact between them.
9. **Light follows the location's fixed direction** from the bible, in every shot at that location.
10. **The first shot obeys the hook rules** in the bible; the last shot ends on a readable face or
    reveal and holds still for its last second (a clean end frame helps replays).
11. **Nothing from the E1 "avoid" list**, and no text anywhere in the frame.

## Worked example

Weak shot: `"Milo runs to the bus"`.

Strong shot (story "The Shortcut", peak beat):

```json
{
  "id": 4,
  "beat": "peak",
  "seconds": 5,
  "location": "maple-street",
  "time_of_day": "morning",
  "characters": ["milo"],
  "framing": "full-body shot, low angle from knee height",
  "composition": "Milo on the right third of the frame, side-on, facing frame left; a tall green hedge fills the left half of the frame",
  "start_pose": "Milo bursts sideways through the hedge, leaves flying, soaking wet hair flattened, arms out for balance, mid-stride, leaning toward frame left",
  "action": "0-2 s he stumbles out of the hedge toward frame left, shaking off leaves; 2-3 s he stops and looks up; 3-5 s he freezes in surprise as a yellow bus slides into frame from the left and stops in front of him",
  "camera": "static",
  "light": "low warm sun from the left of frame, long shadows toward the right",
  "dialogue": [],
  "lipsync": false,
  "sound": "rustling leaves, bus brakes hissing",
  "transition_out": "hard cut",
  "continuity": "Milo's hair and hoodie are wet from shot 3 onward; he moves right-to-left in shots 2-4"
}
```

Readable version for the chat (one row per shot):

| # | Beat | Framing | What we see (5 s) | Dialogue | Lip-sync |
|---|---|---|---|---|---|
| 4 | Peak | Full body, low angle | Wet Milo bursts out of a hedge, stops, a yellow bus slides in and stops in front of him | — | No |

## Self-check before asking for approval

- [ ] 4–6 shots, every one 5 seconds, total 20–30 s.
- [ ] Every shot has framing, composition with facing direction, start pose, timed action, one camera move, light.
- [ ] Start pose leads into the action (facing and lean match the motion direction).
- [ ] No two consecutive shots share the same framing.
- [ ] Screen direction consistent across shots in the same scene.
- [ ] At most 2 lip-sync shots; at most 2 characters per shot; no text in frame.
- [ ] Dialogue total at most 40 words, at most 12 words in any shot.
- [ ] Shot 1 follows the hook rules; the last shot ends on a face or reveal with a held final second.

## Failures and fixes

| Symptom | Cause | Fix | Return to |
|---|---|---|---|
| Character moves the wrong way in the video | Start pose didn't set up the facing | Rewrite `start_pose` and `composition` with the facing toward the motion | E2, then E3 |
| Shot looks static | Action too vague or too small for 5 s | Give a clear physical action with timings, or add a camera move | E2 |
| Shot is chaotic, things morph | Two or more main actions in one shot | Split into two shots or drop one action | E2 |
| Edit feels flat | Same framing repeated | Alternate close and wide shots | E2 |
| Lip-sync looks wrong | Speaker in profile or too small in frame | Make it a close-up facing camera or three-quarter, or move the line off-screen | E2 |
