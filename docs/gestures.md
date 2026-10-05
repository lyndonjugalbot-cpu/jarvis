# Gestures

How the HUD turns webcam frames into panel actions, and how to tune and test it.

## Pipeline

```
webcam -> tracker.js (MediaPipe HandLandmarker, in the browser)
       -> mirrored + One Euro smoothed landmarks
       -> recognizer.js (per hand: pose, how long it has held, wrist speed)
       -> arbiter.js (one gesture at a time, section 7.1 of the spec)
       -> controller.js (cursor, hit-testing, panels, dock)
```

`pose.js`, `recognizer.js`, `arbiter.js` and `engine.js` have no browser code, so the whole engine
runs in Node tests. Video never leaves the browser.

All distances are in hand sizes (h, wrist to middle knuckle) and speeds in h per second, so the
rules work at any distance from the camera. Every threshold is in `src/gestures/settings.js` and
in the settings drawer (press **S**). Changes apply immediately and are saved in the browser.

## Gestures

| Gesture | Rule | Action |
| --- | --- | --- |
| Arm | Open palm toward the camera, wrist nearly still, 500 ms (only while disarmed) | Gestures on; off after 6 s with no hand |
| Point | Index out, other fingers curled | Move the cursor; hovering highlights a panel |
| Pinch tap | Thumb and index tips within 0.25 h, released within 300 ms | Select a panel or a dock item |
| Pinch hold | Pinch held 300 ms with no second pinching hand | Drag the panel under the cursor |
| Fist | Four fingers curled, thumb tucked, 400 ms | Minimize the focused panel to the dock |
| Two-hand spread | Both hands pinching, distance grows 40% | Maximize (others fade back) |
| Two-hand squeeze | Both hands pinching, distance shrinks 40% | Restore |
| Swipe left/right | Open palm moving sideways faster than 2 h/s | Change focus |
| Swipe down | Open palm moving down faster than 2 h/s | Close the focused panel |
| Thumbs up/down | Four fingers curled, thumb out within 35° of vertical, 600 ms | Confirm / cancel (wired to the core in Phase 3) |

One deviation from the spec table: swipes left and right also need an open palm. Otherwise
moving the cursor quickly while pointing would swipe.

## Look-alike rules (spec 7.1)

- **One gesture at a time:** two-hand gestures beat one-hand gestures, holds beat swipes, and
  pointing is the default.
- **Drag vs two-hand:** after a pinch starts, the engine waits 200 ms for the other hand. A second
  hand joining mid-drag hands the same panel over to the resize.
- **Fist vs thumbs:** the thumb decides. A change of shape restarts the hold timer, so a fist that
  opens into a thumbs-up only confirms.
- **Arm vs swipe down:** arming needs a still palm while disarmed; swiping needs a fast palm while
  armed.
- **Release flick:** swipes are ignored for 300 ms after a pinch ends.

Two implementation details keep these reliable:

- A pose counts only after 4 consecutive frames.
- Drags and resizes follow the hand only on frames where the fingers are still pinched, so
  opening the fingers doesn't nudge the panel.

## Testing

```sh
cd frontend && npm test
```

- `tests/gestures.test.js`: scripted hand sessions for every gesture and each look-alike pair,
  built with `src/gestures/synth.js`.
- `tests/pose.test.js`: every pose at several sizes, positions, tilts and both hands.
- `tests/recordings.test.js`: replays real webcam sessions.

To add a real recording, start the camera, press **R**, perform the gesture, and press **R**
again to download the JSON. Add the events it should produce and save it as
`frontend/tests/recordings/<name>.json`:

```json
{ "expect": ["armed", "drag_start", "drag_end"], "frames": [...] }
```

## Debugging

- **D** shows the camera view with the tracked hands, each hand's pose and speed, and recent events.
- **P** plays a scripted demo through the real engine.
- From the browser console, `jarvis.replay(frames)` replays any recording.

The synthetic tests can't confirm two things against a real camera:

- **Palm direction:** if arming never works, try *Swap MediaPipe's left/right* in the settings
  drawer, or turn off *Open palm must face the camera*.
- **Thresholds:** they are the spec's starting values and may need tuning for your camera and
  lighting.
