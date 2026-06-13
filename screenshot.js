#!/usr/bin/env node
/**
 * Playwright screenshot script for AI News HTML cards.
 * Takes a 1920×1080 screenshot of the generated HTML.
 *
 * Usage:
 *   node screenshot.js <input.html> [--output <output.png>]
 *
 * Options:
 *   --output   Output PNG path (default: input file name with .png)
 *   --wait     Wait ms after page load (default: 2000, for fonts/animations)
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');
const os = require('os');

// ─── Config ────────────────────────────────────────────────────────────────

// Google Fonts may be blocked in China; provide fallback fonts.
// The HTML already specifies 'Noto Sans SC', 'JetBrains Mono' in CSS `font-family`.
// Playwright will use whatever fonts are available on the system.
// On Windows, if Noto Sans SC isn't installed, it falls back to system CJK fonts.

/**
 * Find a usable Chromium executable in Playwright's cache.
 * Returns path or null.
 */
function findChromePath() {
  const cacheDir = path.join(os.homedir(), '.cache', 'ms-playwright');

  // Priority 1: chromium-headless-shell (preferred by Playwright for headless)
  const headlessShell = findExecutableInCache(
    cacheDir, 'chromium_headless_shell-*', 'chrome-headless-shell-linux64', 'chrome-headless-shell'
  );
  if (headlessShell && checkDeps(headlessShell)) return headlessShell;

  // Priority 2: snap chromium (has bundled deps, most reliable)
  const snapChrome = '/snap/bin/chromium';
  if (fs.existsSync(snapChrome)) return snapChrome;

  // Priority 3: regular chromium from cache (may be missing system libs)
  const regularChrome = findExecutableInCache(
    cacheDir, 'chromium-*', 'chrome-linux64', 'chrome'
  );
  if (regularChrome && checkDeps(regularChrome)) return regularChrome;

  // Priority 4: system chromium-browser wrapper
  const systemChrome = '/usr/bin/chromium-browser';
  if (fs.existsSync(systemChrome)) return systemChrome;

  return null;
}

/**
 * Quick check if the binary has its critical shared libraries.
 */
function checkDeps(binaryPath) {
  try {
    const { spawnSync } = require('child_process');
    const result = spawnSync('ldd', [binaryPath], { stdio: 'pipe', timeout: 5000, encoding: 'utf8' });
    return !result.stdout.includes('not found');
  } catch (e) {
    // ldd failed (maybe it's a script, not ELF binary) - assume it works
    return true;
  }
}

function findExecutableInCache(cacheDir, revisionGlob, subDir, binaryName) {
  try {
    const items = fs.readdirSync(cacheDir);
    const match = items.find(i => {
      if (typeof revisionGlob === 'string' && revisionGlob.includes('*')) {
        const pattern = '^' + revisionGlob.replace(/\*/g, '\\d+').replace(/_/g, '_') + '$';
        return new RegExp(pattern).test(i);
      }
      return i === revisionGlob;
    });
    if (match) {
      const exe = path.join(cacheDir, match, subDir, binaryName);
      if (fs.existsSync(exe)) return exe;
    }
  } catch (e) {
    // ignore
  }
  return null;
}

/**
 * Check if the chrome binary is a snap (sandboxed).
 * Snap cannot access /tmp/ — so we copy HTML to output dir before navigating.
 */
function isSnap(binaryPath) {
  return binaryPath && binaryPath.includes('/snap/');
}

async function takeScreenshot(htmlPath, outputPath, waitMs = 2000) {
  const absHtml = path.resolve(htmlPath);
  const absOutput = path.resolve(outputPath);

  if (!fs.existsSync(absHtml)) {
    console.error(`[SCREENSHOT] ERROR: HTML file not found: ${absHtml}`);
    process.exit(1);
  }

  console.log(`[SCREENSHOT] 输入: ${absHtml}`);
  console.log(`[SCREENSHOT] 输出: ${absOutput}`);

  // Find chrome binary
  const chromePath = findChromePath();
  const launchConfig = {
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-software-rasterizer',
    ],
  };
  if (chromePath) {
    console.log(`[SCREENSHOT] Chromium: ${chromePath}`);
    launchConfig.executablePath = chromePath;
  } else {
    console.log('[SCREENSHOT] No cached Chromium found, trying Playwright default');
  }

  const browser = await chromium.launch(launchConfig);

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
    bypassCSP: true,
  });

  const page = await context.newPage();

  try {
    // Snap chromium can't access /tmp/ via file:// — copy HTML to output dir
    let htmlFileUrl;
    if (isSnap(chromePath) && absHtml.startsWith('/tmp/')) {
      const outputDir = path.dirname(absOutput);
      const localHtml = path.join(outputDir, path.basename(absHtml));
      fs.copyFileSync(absHtml, localHtml);
      htmlFileUrl = `file://${localHtml}`;
      console.log(`[SCREENSHOT] Copied HTML to snap-accessible path: ${localHtml}`);
    } else {
      htmlFileUrl = `file://${absHtml}`;
    }

    // Use 'domcontentloaded' for local files — 'networkidle' hangs when
    // Google Fonts CDN is blocked (GFW). Fonts will fallback to system CJK.
    await page.goto(htmlFileUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });

    // Wait for fonts (network or fallback) and CSS animations to finish
    await page.waitForTimeout(waitMs);

    // Verify body dimensions
    const dimensions = await page.evaluate(() => {
      const body = document.body;
      return {
        width: body.scrollWidth,
        height: body.scrollHeight,
        childCount: body.children.length,
      };
    });

    console.log(`[SCREENSHOT] 页面尺寸: ${dimensions.width}×${dimensions.height}`);

    if (dimensions.width === 0 || dimensions.height === 0) {
      throw new Error('Page rendered with zero dimensions');
    }

    // If the rendered page is taller than 1080, something is overflowing
    if (dimensions.height > 1200) {
      console.warn(`[SCREENSHOT] WARN: 页面高度 ${dimensions.height} > 1080，可能有内容溢出`);
    }

    // Take screenshot of the full element at exact viewport size
    await page.screenshot({
      path: outputPath,
      type: 'png',
      fullPage: false, // Only viewport (1920×1080)
    });

    // Verify output
    const stat = fs.statSync(outputPath);
    console.log(`[SCREENSHOT] OK: ${outputPath} (${(stat.size / 1024).toFixed(1)} KB)`);

    return outputPath;
  } catch (err) {
    console.error(`[SCREENSHOT] ERROR: ${err.message}`);
    // Try fallback: wait longer and retry
    console.log('[SCREENSHOT] Retrying with longer wait...');
    await page.waitForTimeout(5000);
    await page.screenshot({
      path: outputPath,
      type: 'png',
      fullPage: false,
    });
    const stat = fs.statSync(outputPath);
    if (stat.size > 0) {
      console.log(`[SCREENSHOT] OK (retry): ${outputPath} (${(stat.size / 1024).toFixed(1)} KB)`);
      return outputPath;
    }
    console.error('[SCREENSHOT] Failed to capture screenshot');
    process.exit(1);
  } finally {
    await browser.close();
  }
}

// ─── CLI ───────────────────────────────────────────────────────────────────

function main() {
  const args = process.argv.slice(2);
  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    console.log(`
Usage:
  node screenshot.js <input.html> [options]

Options:
  --output <path>   Output PNG path (default: input .html → .png)
  --wait <ms>       Wait ms after page load (default: 2000)
    `);
    process.exit(0);
  }

  const htmlPath = args[0];
  let outputPath = null;
  let waitMs = 2000;

  for (let i = 1; i < args.length; i++) {
    if (args[i] === '--output' && i + 1 < args.length) {
      outputPath = args[++i];
    } else if (args[i] === '--wait' && i + 1 < args.length) {
      waitMs = parseInt(args[++i], 10) || 2000;
    }
  }

  if (!outputPath) {
    const parsed = path.parse(htmlPath);
    outputPath = path.join(parsed.dir, parsed.name + '.png');
  }

  takeScreenshot(htmlPath, outputPath, waitMs).then(() => {
    process.exit(0);
  }).catch(err => {
    console.error(err);
    process.exit(1);
  });
}

if (require.main === module) {
  main();
}

module.exports = { takeScreenshot };
