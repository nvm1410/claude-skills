# claude-skills

Reusable [Claude Code skills](https://docs.claude.com/en/docs/claude-code) collected
while building apps. Each skill lives in its own folder containing a `SKILL.md`.

To use one, copy its folder into `~/.claude/skills/`.

## Skills

| Skill | Description |
|-------|-------------|
| [app-store-screenshots](app-store-screenshots/SKILL.md) | Code-driven marketing screenshots for Flutter apps (App Store + Google Play): a `flutter test` harness that renders real/composite screens over seeded data inside a device bezel with captions and an enlarged "hero" element — including the slot-hero system, scaling architecture, and pixel-tuning playbook. |
| [app-demo-video](app-demo-video/SKILL.md) | Mock screen-recording demo videos for Flutter apps: a director-driven `flutter test` harness that captures one PNG per pumped frame (real widgets, real gestures with visible ripples, synthetic finger indicator, scene transitions and effect overlays inside a phone bezel), stitched to MP4 with ffmpeg — including the invisible pre-push trick and beat-sheet pacing playbook. |
| [store-listing](store-listing/SKILL.md) | ASO keyword research + localized store listing copy (App Store + Google Play) across many languages: the Apify keyword pipeline (discover → score → select) with budget discipline and actor gotchas, why autocomplete output needs manual topical curation, the localization decision framework (localize names per locale; scoped vs full refresh), per-store field rules + char limits, the iOS no-duplicate-word + truthfulness rules, and a deterministic validate-then-verify loop. Bundles the scripts. |
