import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { inflateSync } from "node:zlib";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = path.resolve(SCRIPT_DIR, "..");
const VERIFICATION_ROOT = path.resolve(REPOSITORY_ROOT, "output", "verification");
const ALLOWED_OUTPUT_TASKS = new Set(["LLMWIKI-009", "LLMWIKI-013"]);
const DEFAULT_VIEWPORTS = ["390x844", "1280x720", "1366x768", "1920x1080"];
const REQUIRED_TABS = [
  { key: "graph", label: "图谱" },
  { key: "timeline", label: "时间线" },
  { key: "sources", label: "来源" },
];

function usage() {
  console.log(
    [
      "Usage: node scripts/verify-llmwiki-visual.mjs --base-url URL --out DIR [--viewports WxH,...]",
      "The output directory must be below output/verification/LLMWIKI-009 or output/verification/LLMWIKI-013.",
      "The runner never installs Playwright or a browser. Missing prerequisites return exit code 2.",
    ].join("\n"),
  );
}

function parseArgs(argv) {
  const values = { baseUrl: "", out: "", viewports: DEFAULT_VIEWPORTS };
  const optionNames = { "base-url": "baseUrl", out: "out", viewports: "viewports" };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      usage();
      process.exit(0);
    }
    if (!argument.startsWith("--")) {
      throw new Error(`Unexpected argument: ${argument}`);
    }
    const option = argument.slice(2);
    const key = optionNames[option];
    if (!key) {
      throw new Error(`Unknown option: --${option}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for --${key}`);
    }
    index += 1;
    if (key === "viewports") {
      values.viewports = value.split(",").map((item) => item.trim()).filter(Boolean);
    } else {
      values[key] = value;
    }
  }
  if (!values.baseUrl || !values.out) {
    throw new Error("--base-url and --out are required");
  }
  let parsedUrl;
  try {
    parsedUrl = new URL(values.baseUrl);
  } catch {
    throw new Error("--base-url must be an http(s) URL");
  }
  if (!/^https?:$/.test(parsedUrl.protocol)) {
    throw new Error("--base-url must be an http(s) URL");
  }
  const viewports = values.viewports.map(parseViewport);
  if (!viewports.length) {
    throw new Error("At least one viewport is required");
  }
  return { baseUrl: parsedUrl, out: path.resolve(REPOSITORY_ROOT, values.out), viewports };
}

function parseViewport(value) {
  const match = /^(\d+)x(\d+)$/.exec(value);
  if (!match) {
    throw new Error(`Invalid viewport: ${value}; expected WIDTHxHEIGHT`);
  }
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width < 200 || height < 240 || width > 5000 || height > 5000) {
    throw new Error(`Viewport out of bounds: ${value}`);
  }
  return { width, height, label: `${width}x${height}` };
}

function isWithin(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return relative === "" || (relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}

function isAllowedOutputDirectory(candidate) {
  if (!isWithin(VERIFICATION_ROOT, candidate)) return false;
  const relative = path.relative(VERIFICATION_ROOT, candidate);
  const taskDirectory = relative.split(path.sep)[0];
  return ALLOWED_OUTPUT_TASKS.has(taskDirectory);
}

function writeText(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, value, "utf8");
}

function writeJson(filePath, value) {
  writeText(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

function resolvePlaywright() {
  const require = createRequire(import.meta.url);
  const searchPaths = [
    REPOSITORY_ROOT,
    path.join(REPOSITORY_ROOT, "apps", "desktop"),
    process.cwd(),
  ];
  if (process.env.PLAYWRIGHT_MODULE_PATH) {
    searchPaths.unshift(process.env.PLAYWRIGHT_MODULE_PATH);
  }

  const npmGlobal = process.env.APPDATA ? path.join(process.env.APPDATA, "npm", "node_modules") : "";
  if (npmGlobal) searchPaths.push(npmGlobal);

  const npmCache = process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "npm-cache", "_npx") : "";
  if (npmCache && fs.existsSync(npmCache)) {
    for (const entry of fs.readdirSync(npmCache)) {
      searchPaths.push(path.join(npmCache, entry, "node_modules"));
    }
  }

  for (const candidate of searchPaths) {
    try {
      const resolved = require.resolve("playwright", { paths: [candidate] });
      return { name: "playwright", resolved, module: require(resolved) };
    } catch {
      // Try the smaller runtime as a fallback. It still provides chromium.launch
      // when a browser executable is installed by the caller.
      try {
        const resolved = require.resolve("playwright-core", { paths: [candidate] });
        return { name: "playwright-core", resolved, module: require(resolved) };
      } catch {
        continue;
      }
    }
  }
  return null;
}

function resolveBrowserExecutable() {
  const candidates = [
    process.env.PLAYWRIGHT_EXECUTABLE_PATH,
    process.env.CHROME_PATH,
    process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Google", "Chrome", "Application", "chrome.exe") : "",
    process.env["ProgramFiles(x86)"] ? path.join(process.env["ProgramFiles(x86)"], "Google", "Chrome", "Application", "chrome.exe") : "",
    process.env["ProgramFiles(x86)"] ? path.join(process.env["ProgramFiles(x86)"], "Microsoft", "Edge", "Application", "msedge.exe") : "",
    process.env.ProgramFiles ? path.join(process.env.ProgramFiles, "Microsoft", "Edge", "Application", "msedge.exe") : "",
  ];
  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || null;
}

function readPngPixels(buffer) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (buffer.length < 33 || !buffer.subarray(0, 8).equals(signature)) {
    throw new Error("Screenshot is not a PNG");
  }
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const compressed = [];
  while (offset + 12 <= buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;
    if (dataEnd + 4 > buffer.length) throw new Error("Truncated PNG chunk");
    if (type === "IHDR") {
      width = buffer.readUInt32BE(dataStart);
      height = buffer.readUInt32BE(dataStart + 4);
      bitDepth = buffer[dataStart + 8];
      colorType = buffer[dataStart + 9];
      const compression = buffer[dataStart + 10];
      const filter = buffer[dataStart + 11];
      const interlace = buffer[dataStart + 12];
      if (compression !== 0 || filter !== 0 || interlace !== 0) throw new Error("Unsupported PNG encoding");
    } else if (type === "IDAT") {
      compressed.push(buffer.subarray(dataStart, dataEnd));
    } else if (type === "IEND") {
      break;
    }
    offset = dataEnd + 4;
  }
  if (!width || !height || bitDepth !== 8 || ![2, 6].includes(colorType)) {
    throw new Error(`Unsupported PNG format (width=${width}, height=${height}, bitDepth=${bitDepth}, colorType=${colorType})`);
  }
  const bytesPerPixel = colorType === 6 ? 4 : 3;
  const rowBytes = width * bytesPerPixel;
  const inflated = inflateSync(Buffer.concat(compressed));
  const expected = height * (rowBytes + 1);
  if (inflated.length < expected) throw new Error("PNG scanline data is truncated");
  const previous = Buffer.alloc(rowBytes);
  const current = Buffer.alloc(rowBytes);
  const buckets = new Map();
  let pixels = 0;
  let transparent = 0;
  let cursor = 0;
  const paeth = (a, b, c) => {
    const p = a + b - c;
    const pa = Math.abs(p - a);
    const pb = Math.abs(p - b);
    const pc = Math.abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  };
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[cursor++];
    inflated.copy(current, 0, cursor, cursor + rowBytes);
    cursor += rowBytes;
    for (let x = 0; x < rowBytes; x += 1) {
      const left = x >= bytesPerPixel ? current[x - bytesPerPixel] : 0;
      const up = previous[x];
      const upLeft = x >= bytesPerPixel ? previous[x - bytesPerPixel] : 0;
      if (filter === 1) current[x] = (current[x] + left) & 0xff;
      else if (filter === 2) current[x] = (current[x] + up) & 0xff;
      else if (filter === 3) current[x] = (current[x] + Math.floor((left + up) / 2)) & 0xff;
      else if (filter === 4) current[x] = (current[x] + paeth(left, up, upLeft)) & 0xff;
      else if (filter !== 0) throw new Error(`Unsupported PNG filter: ${filter}`);
    }
    for (let x = 0; x < width; x += 1) {
      const index = x * bytesPerPixel;
      const alpha = colorType === 6 ? current[index + 3] : 255;
      const key = colorType === 6 && alpha < 8 ? "transparent" : `${current[index] >> 4},${current[index + 1] >> 4},${current[index + 2] >> 4}`;
      buckets.set(key, (buckets.get(key) || 0) + 1);
      pixels += 1;
      if (alpha < 8) transparent += 1;
    }
    current.copy(previous);
  }
  let dominant = 0;
  for (const count of buckets.values()) dominant = Math.max(dominant, count);
  return {
    width,
    height,
    pixels,
    dominant_pixels: dominant,
    transparent_pixels: transparent,
    nonblank_ratio: pixels ? Number((1 - dominant / pixels).toFixed(6)) : 0,
  };
}

async function inspectPage(page, screenshotPath) {
  const screenshot = await page.screenshot({ path: screenshotPath, type: "png", fullPage: false });
  const pixels = readPngPixels(screenshot);
  const dom = await page.evaluate(() => {
    const isVisible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const closedDetailsContent = element.closest("details:not([open])") && !element.matches("summary");
      return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0 && !element.closest('[aria-hidden="true"], [hidden]') && !closedDetailsContent;
    };
    const overflow = {
      client_width: document.documentElement.clientWidth,
      scroll_width: document.documentElement.scrollWidth,
      horizontal: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      offenders: [],
    };
    if (overflow.horizontal) {
      for (const element of document.querySelectorAll("body *")) {
        if (!isVisible(element)) continue;
        const rect = element.getBoundingClientRect();
        if (rect.left < -1 || rect.right > document.documentElement.clientWidth + 1) {
          overflow.offenders.push({ tag: element.tagName.toLowerCase(), id: element.id || "", class_name: String(element.className || "").slice(0, 100) });
          if (overflow.offenders.length >= 12) break;
        }
      }
    }
    const images = [...document.images].filter(isVisible);
    const imageFailures = images.filter((image) => !image.complete || image.naturalWidth === 0).length;
    const canvas = [...document.querySelectorAll("canvas")].filter(isVisible).map((element) => ({ width: element.width, height: element.height }));
    const focusables = [...document.querySelectorAll('a[href]:not([tabindex="-1"]), button:not([tabindex="-1"]), input:not([type="hidden"]):not([tabindex="-1"]), textarea:not([tabindex="-1"]), select:not([tabindex="-1"]), summary:not([tabindex="-1"]), [contenteditable="true"]:not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])')].filter((element) => {
      if (!isVisible(element)) return false;
      if (element.matches(":disabled,[aria-disabled=\"true\"]")) return false;
      return true;
    });
    const focusIdentity = focusables.map((element, index) => ({ index, tag: element.tagName.toLowerCase(), id: element.id || "", role: element.getAttribute("role") || "" }));
    const tabSemantics = [...document.querySelectorAll('[role="button"],[role="link"],[role="checkbox"],[role="switch"],[role="tab"]')].filter((element) => isVisible(element) && !element.matches('[aria-disabled="true"]') && element.getAttribute("role") !== "tab");
    const semanticMissingTab = tabSemantics.filter((element) => element.tabIndex < 0).length;
    return { overflow, image_count: images.length, image_failures: imageFailures, canvas, focusables: focusIdentity, semantic_missing_tab: semanticMissingTab };
  });

  const focus = await inspectFocus(page, dom.focusables.length);
  const contrast = await page.evaluate(() => {
    const parse = (value) => {
      const match = value.match(/rgba?\(([^)]+)\)/i);
      if (!match) return null;
      const parts = match[1].split(",").map((item) => item.trim());
      const channels = parts.slice(0, 3).map(Number);
      if (channels.some((item) => !Number.isFinite(item))) return null;
      const alpha = parts.length > 3 ? Number(parts[3]) : 1;
      return { r: channels[0], g: channels[1], b: channels[2], a: Number.isFinite(alpha) ? alpha : 1 };
    };
    const blend = (front, back) => ({ r: front.r * front.a + back.r * (1 - front.a), g: front.g * front.a + back.g * (1 - front.a), b: front.b * front.a + back.b * (1 - front.a) });
    const backgroundFor = (element) => {
      let result = { r: 255, g: 255, b: 255 };
      const chain = [];
      for (let current = element; current; current = current.parentElement) chain.push(current);
      for (const current of chain.reverse()) {
        const color = parse(getComputedStyle(current).backgroundColor);
        if (color && color.a > 0) result = blend(color, result);
      }
      return result;
    };
    const linear = (channel) => {
      const value = channel / 255;
      return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    };
    const ratio = (foreground, background) => {
      const foregroundL = 0.2126 * linear(foreground.r) + 0.7152 * linear(foreground.g) + 0.0722 * linear(foreground.b);
      const backgroundL = 0.2126 * linear(background.r) + 0.7152 * linear(background.g) + 0.0722 * linear(background.b);
      return (Math.max(foregroundL, backgroundL) + 0.05) / (Math.min(foregroundL, backgroundL) + 0.05);
    };
    const elements = [];
    const seen = new Set();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const text = String(node.nodeValue || "").replace(/\s+/g, " ").trim();
      const element = node.parentElement;
      const closedDetailsContent = element && element.closest("details:not([open])") && !element.matches("summary");
      if (!text || !element || seen.has(element) || element.closest('[aria-hidden="true"], [hidden]') || closedDetailsContent) continue;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) === 0 || rect.width <= 0 || rect.height <= 0 || element.matches(":disabled,[aria-disabled=\"true\"]")) continue;
      seen.add(element);
      const foreground = parse(style.color);
      if (!foreground || foreground.a === 0) continue;
      const size = Number.parseFloat(style.fontSize) || 16;
      const weight = Number.parseInt(style.fontWeight, 10) || 400;
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      const value = ratio(blend(foreground, backgroundFor(element)), backgroundFor(element));
      elements.push({ ratio: Number(value.toFixed(3)), required: large ? 3 : 4.5, large, text_length: text.length });
    }
    const failures = elements.filter((item) => item.ratio + 0.01 < item.required);
    return { checked: elements.length, failures: failures.length, samples: failures.slice(0, 20) };
  });

  const canvasChecks = [];
  const canvasCount = await page.locator("canvas").count();
  for (let index = 0; index < Math.min(canvasCount, 8); index += 1) {
    const locator = page.locator("canvas").nth(index);
    if (!(await locator.isVisible().catch(() => false))) continue;
    try {
      const canvasShot = await locator.screenshot({ type: "png" });
      const canvasPixels = readPngPixels(canvasShot);
      canvasChecks.push({ index, ...canvasPixels, passed: canvasPixels.nonblank_ratio >= 0.01 });
    } catch (error) {
      canvasChecks.push({ index, passed: false, error_code: "canvas_screenshot_failed", error: String(error).slice(0, 160) });
    }
  }

  return {
    screenshot: path.basename(screenshotPath),
    dimensions: { width: pixels.width, height: pixels.height, pixels: pixels.pixels },
    nonblank: { ratio: pixels.nonblank_ratio, threshold: 0.01, passed: pixels.nonblank_ratio >= 0.01 },
    overflow: dom.overflow,
    focus,
    contrast,
    images: { count: dom.image_count, failures: dom.image_failures, passed: dom.image_failures === 0 },
    canvases: { count: dom.canvas.length, checks: canvasChecks, passed: canvasChecks.every((item) => item.passed) },
    state_passed: pixels.nonblank_ratio >= 0.01 && !dom.overflow.horizontal && focus.unreachable === 0 && contrast.failures === 0 && dom.image_failures === 0 && canvasChecks.every((item) => item.passed),
  };
}

async function resetScrollPositions(page) {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    for (const element of document.querySelectorAll("*")) {
      if (element instanceof HTMLElement) {
        element.scrollTop = 0;
        element.scrollLeft = 0;
      }
    }
  });
}

async function inspectFocus(page, expectedCount) {
  const reached = new Set();
  const indicatorMissing = [];
  let offscreen = 0;
  const iterations = Math.min(Math.max(expectedCount + 5, 12), 500);
  const previousTabIndex = await page.evaluate(() => {
    const body = document.body;
    const previous = body.getAttribute("tabindex");
    body.setAttribute("tabindex", "-1");
    body.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return previous;
  });
  try {
    for (let index = 0; index < iterations; index += 1) {
      await page.keyboard.press("Tab");
      const state = await page.evaluate(() => {
        const isVisible = (element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          const closedDetailsContent = element.closest("details:not([open])") && !element.matches("summary");
          return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0 && !element.closest('[aria-hidden="true"], [hidden]') && !closedDetailsContent;
        };
        const active = document.activeElement;
        // React Flow exposes keyboard-focusable edges as SVG <g> elements. Treat
        // every rendered Element as a candidate so the probe does not report
        // those legitimate controls as unreachable merely because they are not
        // HTMLElement instances.
        if (!(active instanceof Element) || active === document.body || !isVisible(active)) return { index: -1, indicator: false, offscreen: false };
        const focusables = [...document.querySelectorAll('a[href]:not([tabindex="-1"]), button:not([tabindex="-1"]), input:not([type="hidden"]):not([tabindex="-1"]), textarea:not([tabindex="-1"]), select:not([tabindex="-1"]), summary:not([tabindex="-1"]), [contenteditable="true"]:not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])')].filter((element) => isVisible(element) && !element.matches(":disabled,[aria-disabled=\"true\"]"));
        const rect = active.getBoundingClientRect();
        const style = getComputedStyle(active);
        const indicator = active.matches(":focus-visible") && (style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0 || style.boxShadow !== "none" || style.textDecorationLine.includes("underline"));
        return { index: focusables.indexOf(active), indicator, offscreen: rect.right < 0 || rect.left > window.innerWidth || rect.bottom < 0 || rect.top > window.innerHeight };
      });
      if (state.index >= 0) {
        reached.add(state.index);
        if (!state.indicator && indicatorMissing.length < 20) indicatorMissing.push(state.index);
        if (state.offscreen) offscreen += 1;
      }
    }
  } finally {
    await page.evaluate((previous) => {
      const body = document.body;
      if (previous === null) body.removeAttribute("tabindex");
      else body.setAttribute("tabindex", previous);
      window.scrollTo(0, 0);
    }, previousTabIndex);
  }
  return {
    expected: expectedCount,
    reached: reached.size,
    unreachable: Math.max(0, expectedCount - reached.size),
    offscreen_focus_events: offscreen,
    indicator_missing_samples: indicatorMissing,
    passed: Math.max(0, expectedCount - reached.size) === 0,
  };
}

async function inspectReducedMotion(page, targetUrl) {
  try {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForSelector(".llmwiki-memory-shell", { state: "visible", timeout: 15000 });
    const uiSettled = await page
      .waitForFunction(
        () => !document.querySelector('.llmwiki-loading-line, .llmwiki-state[role="status"]'),
        undefined,
        { timeout: 8000 },
      )
      .then(() => true)
      .catch(() => false);
    await page.waitForTimeout(250);
    const result = await page.evaluate(async () => {
      const visible = (element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        const closedDetailsContent = element.closest("details:not([open])") && !element.matches("summary");
        return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0 && !element.closest('[aria-hidden="true"], [hidden]') && !closedDetailsContent;
      };
      const elements = [...document.querySelectorAll("body *")].filter(visible).slice(0, 600);
      const before = elements.map((element) => {
        const rect = element.getBoundingClientRect();
        return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
      });
      await new Promise((resolve) => setTimeout(resolve, 450));
      let moved = 0;
      let maxDisplacement = 0;
      elements.forEach((element, index) => {
        const rect = element.getBoundingClientRect();
        const initial = before[index];
        const displacement = Math.max(Math.abs(rect.left - initial.left), Math.abs(rect.top - initial.top), Math.abs(rect.width - initial.width), Math.abs(rect.height - initial.height));
        if (displacement > 1) moved += 1;
        maxDisplacement = Math.max(maxDisplacement, displacement);
      });
      const positionAnimations = document.getAnimations().filter((animation) => animation.playState === "running").filter((animation) => (animation.effect?.getKeyframes?.() || []).some((frame) => ["transform", "translate", "top", "left", "right", "bottom"].some((property) => property in frame)));
      const meaningfulPositionAnimations = positionAnimations.filter((animation) => {
        const timing = animation.effect?.getTiming?.();
        const duration = Number(timing?.duration);
        const iterations = Number(timing?.iterations);
        return iterations === Infinity || !Number.isFinite(duration) || duration > 1;
      });
      return {
        media_matches: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        moved_elements: moved,
        max_displacement_px: Number(maxDisplacement.toFixed(2)),
        running_position_animations: meaningfulPositionAnimations.length,
        suppressed_submillisecond_position_transitions: positionAnimations.length - meaningfulPositionAnimations.length,
      };
    });
    return {
      ...result,
      ui_settled: uiSettled,
      passed: uiSettled && result.media_matches && result.moved_elements === 0 && result.running_position_animations === 0,
    };
  } catch (error) {
    return { passed: false, error_code: "reduced_motion_probe_failed", error: String(error).slice(0, 160) };
  }
}

function markdownReport(report) {
  const lines = [
    "# LLM Wiki visual verification",
    "",
    `- status: **${report.status}**`,
    `- runner: \`${report.schema_version}\``,
    `- target: \`${report.target_url}\``,
    `- Playwright: \`${report.prerequisites.playwright.status}\` (${report.prerequisites.playwright.module || "unavailable"})`,
    "",
    "| Viewport | State | Screenshot | Nonblank | Overflow | Focus | Contrast | Reduced motion |",
    "| --- | --- | --- | ---: | --- | --- | --- | --- |",
  ];
  for (const viewport of report.viewports) {
    for (const state of viewport.states) {
      lines.push(`| ${viewport.label} | ${state.state} | ${state.checks?.screenshot || "-"} | ${state.checks ? `${state.checks.nonblank.ratio} (${state.checks.nonblank.passed ? "pass" : "fail"})` : "-"} | ${state.checks ? (state.checks.overflow.horizontal ? "fail" : "pass") : "-"} | ${state.checks ? `${state.checks.focus.reached}/${state.checks.focus.expected}` : "-"} | ${state.checks ? `${state.checks.contrast.failures} failures` : "-"} | ${viewport.reduced_motion ? (viewport.reduced_motion.passed ? "pass" : "fail") : "-"} |`);
    }
  }
  lines.push("", "States that could not be rendered or checked are evidence gaps, not successful visual validation.", "");
  return lines.join("\n");
}

function emptyReport(targetUrl, reason) {
  return {
    schema_version: "llmwiki-visual-report.v1",
    generated_at: new Date().toISOString(),
    status: "Partial",
    target_url: targetUrl,
    prerequisites: { playwright: { status: "missing", module: null, reason } },
    viewports: [],
    non_verified: [reason],
    exit_code: 2,
  };
}

async function main() {
  let options;
  try {
    options = parseArgs(process.argv.slice(2));
    if (!isAllowedOutputDirectory(options.out)) {
      throw new Error("--out must stay below output/verification/LLMWIKI-009 or output/verification/LLMWIKI-013");
    }
    fs.mkdirSync(options.out, { recursive: true });
  } catch (error) {
    console.error(`VISUAL_USAGE_ERROR: ${String(error.message || error)}`);
    usage();
    process.exitCode = 2;
    return;
  }

  const targetUrl = new URL(options.baseUrl.toString());
  if (!targetUrl.hash) targetUrl.hash = "#memory";
  const sessionToken = (process.env.AGENT_PET_SESSION_TOKEN || "").trim();
  const playwright = resolvePlaywright();
  if (!playwright) {
    const report = emptyReport(targetUrl.toString(), "playwright_module_unavailable");
    writeJson(path.join(options.out, "visual-report.json"), report);
    writeText(path.join(options.out, "visual-report.md"), markdownReport(report));
    console.error("VISUAL_PREREQUISITE_MISSING: install Playwright in the verification environment; no browser was downloaded by this runner.");
    process.exitCode = 2;
    return;
  }

  const report = {
    schema_version: "llmwiki-visual-report.v1",
    generated_at: new Date().toISOString(),
    status: "Passed",
    target_url: targetUrl.toString(),
    prerequisites: {
      playwright: {
        status: "available",
        module: playwright.name,
        resolved: path.basename(playwright.resolved),
      },
      browser: { status: "system_or_bundled", executable: resolveBrowserExecutable() },
      backend_auth: { status: sessionToken ? "configured" : "missing" },
    },
    viewports: [],
    non_verified: [],
    exit_code: 0,
  };
  if (!sessionToken) {
    report.status = "Partial";
    report.non_verified.push("backend_session_token_missing");
  }
  let browser;
  try {
    if (typeof playwright.module.chromium?.launch !== "function") throw new Error("chromium_launch_unavailable");
    const executablePath = resolveBrowserExecutable();
    browser = await playwright.module.chromium.launch({
      headless: true,
      ...(executablePath ? { executablePath } : {}),
    });
    for (const viewport of options.viewports) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: 1,
        ...(sessionToken ? { extraHTTPHeaders: { Authorization: `Bearer ${sessionToken}` } } : {}),
      });
      const page = await context.newPage();
      const requestFailures = [];
      const consoleErrors = [];
      const httpErrors = [];
      page.on("requestfailed", (request) => requestFailures.push(request.resourceType()));
      page.on("response", (response) => {
        if (response.status() < 400) return;
        let safeUrl = response.url();
        try {
          const parsed = new URL(safeUrl);
          safeUrl = `${parsed.origin}${parsed.pathname}`;
        } catch {
          safeUrl = "[invalid-url]";
        }
        httpErrors.push({
          status: response.status(),
          method: response.request().method(),
          resource_type: response.request().resourceType(),
          url: safeUrl,
        });
      });
      page.on("pageerror", (error) => {
        consoleErrors.push(`pageerror:${String(error).replaceAll(sessionToken, "[REDACTED]").slice(0, 240)}`);
      });
      page.on("console", (message) => {
        if (message.type() !== "error") return;
        consoleErrors.push(message.text().replaceAll(sessionToken, "[REDACTED]").slice(0, 240));
      });
      const viewportReport = { label: viewport.label, states: [], request_failures: requestFailures, http_errors: httpErrors, console_errors: consoleErrors, reduced_motion: null };
      let shellAvailable = false;
      try {
        await page.goto(targetUrl.toString(), { waitUntil: "domcontentloaded", timeout: 15000 });
        await page.waitForTimeout(1000);
        shellAvailable = (await page.locator(".llmwiki-memory-shell").count()) > 0;
      } catch (error) {
        viewportReport.states.push({ state: "route", status: "Failed", reason_code: "page_navigation_failed", error: String(error).slice(0, 160) });
      }
      if (!shellAvailable) {
        if (!viewportReport.states.length) viewportReport.states.push({ state: "route", status: "Failed", reason_code: "memory_route_not_rendered" });
        report.status = "Failed";
      } else {
        for (const tab of REQUIRED_TABS) {
          const tabLocator = page.locator('[role="tab"]').filter({ hasText: tab.label }).first();
          if ((await tabLocator.count()) === 0) {
            viewportReport.states.push({ state: tab.key, status: "Failed", reason_code: "required_memory_tab_missing" });
            report.status = "Failed";
            continue;
          }
          await tabLocator.click();
          await page.waitForTimeout(300);
          await resetScrollPositions(page);
          const screenshotPath = path.join(options.out, `${viewport.label}-${tab.key}.png`);
          try {
            const checks = await inspectPage(page, screenshotPath);
            const stateStatus = checks.state_passed ? "Passed" : "Failed";
            viewportReport.states.push({ state: tab.key, status: stateStatus, checks });
            if (!checks.state_passed) report.status = "Failed";
          } catch (error) {
            viewportReport.states.push({ state: tab.key, status: "Failed", reason_code: "visual_probe_failed", error: String(error).slice(0, 160) });
            report.status = "Failed";
          }
        }
      }
      const motionPage = await context.newPage();
      viewportReport.reduced_motion = await inspectReducedMotion(motionPage, targetUrl.toString());
      if (!viewportReport.reduced_motion.passed) report.status = "Failed";
      await motionPage.close();
      await page.close();
      await context.close();
      report.viewports.push(viewportReport);
    }
  } catch (error) {
    report.status = "Partial";
    report.non_verified.push(`browser_launch_or_context_failed:${String(error).slice(0, 160)}`);
  } finally {
    if (browser) await browser.close().catch(() => undefined);
  }
  if (report.status === "Passed" && report.viewports.some((item) => item.states.some((state) => state.status !== "Passed"))) report.status = "Failed";
  if (report.status === "Passed" && report.viewports.some((item) => item.request_failures.length > 0)) report.status = "Partial";
  if (report.status === "Passed" && report.viewports.some((item) => item.http_errors.length > 0)) report.status = "Partial";
  if (report.status === "Passed" && report.viewports.some((item) => item.console_errors.length > 0)) report.status = "Partial";
  report.exit_code = report.status === "Passed" ? 0 : report.status === "Failed" ? 1 : 2;
  writeJson(path.join(options.out, "visual-report.json"), report);
  writeText(path.join(options.out, "visual-report.md"), markdownReport(report));
  console.log(`Visual report: ${path.join(options.out, "visual-report.json")}`);
  process.exitCode = report.exit_code;
}

main().catch((error) => {
  console.error(`VISUAL_RUNNER_ERROR: ${String(error.stack || error)}`);
  process.exitCode = 1;
});
