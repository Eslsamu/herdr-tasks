# Deterministic demo capture

The public demo shows an isolated Herdr terminal with scripted example chat, followed by the actual browser queue UI. It uses a disposable SQLite database and exercises the real `Store`, `top_status`, `browser_payload`, and browser renderer. Chat is fictional; this is an example walkthrough, not a live model run. There are no title sequences, slogans, or promotional transitions.

Requirements:

- Python 3.10+ with `pyte` (capture dependency only)
- Herdr installed for the isolated terminal capture
- Node.js with Playwright and Chromium
- FFmpeg with `libx264` and `libvpx-vp9`

Run:

```sh
node demo/capture_demo.mjs
```

If those tools are not on their default paths, point the script at existing installations:

```sh
PLAYWRIGHT_NODE_MODULES=/path/to/node_modules \
CHROMIUM_EXECUTABLE=/path/to/chromium \
FFMPEG=/path/to/ffmpeg \
node demo/capture_demo.mjs
```

The script starts an ephemeral loopback-only server, fails on external requests or browser errors, captures exactly 720 lossless frames, and removes its temporary database, screenshots, and frames after a successful encode. It writes:

- `docs/assets/herdr-tasks-demo.mp4` — 24 seconds, H.264, 1440×900, 30 fps, silent
- `docs/assets/herdr-tasks-demo.webm` — 24 seconds, VP9, 1440×900, 30 fps, silent
- `docs/assets/herdr-tasks-demo-poster.png` — browser queue frame
- `docs/assets/herdr-tasks-demo.gif` — inline README animation, 1440×900, 8 fps

The demo is a truthful compressed walkthrough, not a recording of live execution: a follow-up enters the queue when Agent One processes it, the browser remains read-only, and the synthetic QA agent claims the task through the CLI.
