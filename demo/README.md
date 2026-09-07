# Deterministic demo capture

The public demo uses a disposable SQLite database and generic synthetic agents. It exercises the real `Store`, `top_status`, `browser_payload`, and browser renderer without reading a live Herdr session or task database.

Requirements:

- Python 3.10+
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

- `docs/assets/herdr-tasks-demo.mp4` — 24 seconds, H.264, 1920×1080, 30 fps, silent
- `docs/assets/herdr-tasks-demo.webm` — 24 seconds, VP9, 1920×1080, 30 fps, silent
- `docs/assets/herdr-tasks-demo-poster.png` — meaningful 1920×1080 poster frame

The demo is a truthful compressed walkthrough, not a recording of live execution: a follow-up enters the queue when Agent One processes it, the browser remains read-only, and the synthetic QA agent claims the task through the CLI.
