# App Preview

The App Store preview video is authored by Claude from real recordings of this app (the `app_preview`
stage). Apple's rule: the content is real app footage, motion graphics
only frame and highlight it.

| Path | What |
|---|---|
| `BRIEF.md` | the HyperFrames brief (`preview_brief` writes it from `app.spec.json`; `destination: app-store-preview`) |
| `recordings/<locale>/` | raw `xcrun simctl io <udid> recordVideo` captures, after `Scripts/sim_store_prep.sh` |
| `index.html`, `hyperframes.json`, `assets/` | the composition (deterministic: no `Math.random`, no timers) |
| `review/<locale>/`, `review/log.json` | self-review sheets and the scored rounds (every criterion 8+ on the final file) |
| `../../fastlane/app_previews/<locale>/` | the finished previews: 886x1920, <=30 fps, H.264, 15–30 s, stereo AAC or silent |

Flow: `preview_brief` → record → author with the `hyperframes` skill → render → `preview_review_sheets` →
`preview_review_log` (fix and re-render until 8+) → `preview_check` → founder's go → `preview_upload(confirm=<bundle id>)`.
