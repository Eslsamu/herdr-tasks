#!/usr/bin/env node

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { copyFile, mkdtemp, mkdir, readFile, rm, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEMO = path.join(ROOT, "demo");
const WEB = path.join(ROOT, "web");
const OUTPUT = path.join(ROOT, "docs", "assets");
const WIDTH = 1440;
const HEIGHT = 900;
const VIEWER_WIDTH = 1440;
const VIEWER_HEIGHT = 860;
const FPS = 30;
const FRAME_COUNT = 720;
const POSTER_FRAME = 384;

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
    ...options,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${command} exited with ${result.status}\n${result.stderr || ""}`);
  }
  return result.stdout || "";
}

function loadPlaywright() {
  const require = createRequire(import.meta.url);
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    process.env.PLAYWRIGHT_NODE_MODULES
      ? path.join(process.env.PLAYWRIGHT_NODE_MODULES, "playwright")
      : null,
    "playwright",
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      if (candidate === candidates.at(-1)) {
        throw new Error(
          "Playwright is unavailable. Install it or set PLAYWRIGHT_NODE_MODULES to a node_modules directory.",
          { cause: error },
        );
      }
    }
  }
  throw new Error("Playwright is unavailable");
}

function contentType(file) {
  if (file.endsWith(".html")) return "text/html; charset=utf-8";
  if (file.endsWith(".css")) return "text/css; charset=utf-8";
  if (file.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (file.endsWith(".json")) return "application/json; charset=utf-8";
  if (file.endsWith(".png")) return "image/png";
  return "application/octet-stream";
}

function attachPageGuards(page, origin, failures) {
  page.on("request", (request) => {
    if (!request.url().startsWith(`${origin}/`)) {
      failures.push(`Unexpected external request: ${request.url()}`);
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failures.push(`HTTP ${response.status()}: ${response.url()}`);
    }
  });
  page.on("pageerror", (error) => failures.push(`Page error: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`Console error: ${message.text()}`);
  });
}

async function makeServer(fixture, temporary) {
  const captureHtml = await readFile(path.join(DEMO, "capture.html"));
  const viewerIndex = await readFile(path.join(WEB, "index.html"));
  const viewerStyles = await readFile(path.join(WEB, "styles.css"));
  const viewerScript = await readFile(path.join(WEB, "app.js"));
  const fixtureJson = Buffer.from(`${JSON.stringify(fixture)}\n`);

  const server = createServer(async (request, response) => {
    try {
      const pathname = new URL(request.url || "/", "http://127.0.0.1").pathname;
      let body;
      let type;
      if (pathname === "/capture.html") {
        body = captureHtml;
        type = contentType(pathname);
      } else if (pathname === "/terminal.json") {
        body = await readFile(path.join(temporary, "terminal.json"));
        type = contentType(pathname);
      } else if (pathname === "/capture-data.json") {
        body = fixtureJson;
        type = contentType(pathname);
      } else if (pathname === "/shots/queued.png" || pathname === "/shots/doing.png") {
        body = await readFile(path.join(temporary, pathname.slice(1)));
        type = contentType(pathname);
      } else {
        const match = pathname.match(/^\/viewer\/(queued|doing)\/(.*)$/);
        if (!match) {
          response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
          response.end("Not found\n");
          return;
        }
        const [, state, asset] = match;
        if (asset === "" || asset === "index.html") {
          body = viewerIndex;
          type = contentType("index.html");
        } else if (asset === "styles.css") {
          body = viewerStyles;
          type = contentType(asset);
        } else if (asset === "app.js") {
          body = viewerScript;
          type = contentType(asset);
        } else if (asset === "api/state") {
          body = Buffer.from(`${JSON.stringify(fixture[state].payload)}\n`);
          type = contentType("state.json");
        } else {
          response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
          response.end("Not found\n");
          return;
        }
      }
      response.writeHead(200, {
        "Content-Type": type,
        "Content-Length": body.length,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      });
      if (request.method === "HEAD") response.end();
      else response.end(body);
    } catch (error) {
      response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
      response.end(`${error.message}\n`);
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert(address && typeof address === "object");
  return { server, origin: `http://127.0.0.1:${address.port}` };
}

async function captureViewer(context, origin, state, output, failures) {
  const page = await context.newPage();
  attachPageGuards(page, origin, failures);
  await page.goto(`${origin}/viewer/${state}/`, { waitUntil: "networkidle" });
  await page.waitForFunction(
    () => document.querySelector("#connection-status")?.textContent === "Read-only · Live",
  );
  const metrics = await page.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
    scrollWidth: document.documentElement.scrollWidth,
    title: document.title,
  }));
  assert.equal(metrics.width, VIEWER_WIDTH);
  assert.equal(metrics.height, VIEWER_HEIGHT);
  assert.equal(metrics.scrollWidth, VIEWER_WIDTH);
  assert.equal(metrics.title, "SpaceName / Launch readiness");
  await page.screenshot({ path: output, animations: "disabled" });
  await page.close();
}

async function main() {
  const temporary = await mkdtemp(path.join(os.tmpdir(), "herdr-tasks-demo-"));
  const fixturePath = path.join(temporary, "capture-data.json");
  const shots = path.join(temporary, "shots");
  const frames = path.join(temporary, "frames");
  await mkdir(shots, { recursive: true });
  await mkdir(frames, { recursive: true });
  await mkdir(OUTPUT, { recursive: true });

  const python = process.env.PYTHON || "python3";
  const ffmpeg = process.env.FFMPEG || "ffmpeg";
  run(python, [path.join(DEMO, "make_fixture.py"), fixturePath]);
  run(python, [path.join(DEMO, "capture_terminal.py"), path.join(temporary, "terminal.json"), fixturePath]);
  const fixture = JSON.parse(await readFile(fixturePath, "utf8"));
  assert.equal(fixture.synthetic, true);
  assert.equal(fixture.duration_ms, 24_000);
  assert.equal(fixture.fps, FPS);
  assert.equal(fixture.queued.preview, "Tasks · Next: Run pre-release regression · 1 next · 0 waiting");
  assert.equal(fixture.doing.preview, "Tasks · Now: Run pre-release regression · 0 next · 0 waiting");

  const { chromium } = loadPlaywright();
  const launch = { headless: true };
  if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
  const browser = await chromium.launch(launch);
  let server;
  const failures = [];
  try {
    const serving = await makeServer(fixture, temporary);
    server = serving.server;
    const origin = serving.origin;
    const viewerContext = await browser.newContext({
      viewport: { width: VIEWER_WIDTH, height: VIEWER_HEIGHT },
      deviceScaleFactor: 1,
      colorScheme: "dark",
      locale: "en-US",
      timezoneId: "UTC",
      reducedMotion: "reduce",
    });
    await captureViewer(
      viewerContext,
      origin,
      "queued",
      path.join(shots, "queued.png"),
      failures,
    );
    await captureViewer(
      viewerContext,
      origin,
      "doing",
      path.join(shots, "doing.png"),
      failures,
    );
    await viewerContext.close();

    const context = await browser.newContext({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: 1,
      colorScheme: "dark",
      locale: "en-US",
      timezoneId: "UTC",
      reducedMotion: "reduce",
    });
    const page = await context.newPage();
    attachPageGuards(page, origin, failures);
    await page.goto(`${origin}/capture.html`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => window.__DEMO_READY__ === true);
    const contract = await page.evaluate(() => ({
      width: window.innerWidth,
      height: window.innerHeight,
      scrollWidth: document.documentElement.scrollWidth,
      scrollHeight: document.documentElement.scrollHeight,
      ready: document.documentElement.dataset.captureReady,
      error: document.documentElement.dataset.captureError || "",
      synthetic: document.querySelector(".synthetic-label")?.textContent?.trim(),
    }));
    assert.deepEqual(contract, {
      width: WIDTH,
      height: HEIGHT,
      scrollWidth: WIDTH,
      scrollHeight: HEIGHT,
      ready: "true",
      error: "",
      synthetic: "Synthetic data",
    });
    assert.deepEqual(failures, []);

    let previousStep;
    let previousFile;
    for (let frame = 0; frame < FRAME_COUNT; frame += 1) {
      const time = frame * 1000 / FPS;
      await page.evaluate((value) => window.__setDemoTime(value), time);
      const filename = path.join(frames, `frame-${String(frame).padStart(4, "0")}.png`);
      const step = time < 5000 ? 0 : time < 11000 ? 1 : time < 17000 ? 2 : time < 19500 ? 3 : 4;
      if (step === previousStep) await copyFile(previousFile, filename);
      else await page.screenshot({ path: filename, animations: "disabled" });
      previousStep = step;
      previousFile = filename;
      if ((frame + 1) % 90 === 0) {
        process.stdout.write(`Captured ${frame + 1}/${FRAME_COUNT} frames\n`);
      }
    }
    assert.deepEqual(failures, []);
    await context.close();
  } finally {
    await browser.close();
    if (server) await new Promise((resolve) => server.close(resolve));
  }

  const mp4 = path.join(OUTPUT, "herdr-tasks-demo.mp4");
  const webm = path.join(OUTPUT, "herdr-tasks-demo.webm");
  const poster = path.join(OUTPUT, "herdr-tasks-demo-poster.png");
  const pattern = path.join(frames, "frame-%04d.png");
  run(ffmpeg, [
    "-hide_banner", "-loglevel", "warning", "-y",
    "-framerate", String(FPS), "-start_number", "0", "-i", pattern,
    "-frames:v", String(FRAME_COUNT), "-an", "-c:v", "libx264",
    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", mp4,
  ]);
  run(ffmpeg, [
    "-hide_banner", "-loglevel", "warning", "-y", "-i", mp4,
    "-frames:v", String(FRAME_COUNT), "-an", "-c:v", "libvpx-vp9",
    "-crf", "31", "-b:v", "0", "-deadline", "good", "-cpu-used", "4",
    "-threads", "1", "-row-mt", "0", "-flags:v", "+bitexact",
    "-fflags", "+bitexact", "-map_metadata", "-1", "-pix_fmt", "yuv420p", webm,
  ]);
  await copyFile(
    path.join(frames, `frame-${String(POSTER_FRAME).padStart(4, "0")}.png`),
    poster,
  );

  const outputs = {};
  const gif = path.join(OUTPUT, "herdr-tasks-demo.gif");
  run(ffmpeg, ["-v", "error", "-y", "-i", mp4, "-filter_complex",
    "[0:v]fps=8,scale=1440:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
    "-loop", "0", gif]);
  for (const file of [mp4, webm, poster]) outputs[path.basename(file)] = (await stat(file)).size;
  process.stdout.write(`${JSON.stringify({ frameCount: FRAME_COUNT, outputs }, null, 2)}\n`);
  await rm(temporary, { recursive: true, force: true });
}

main().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
