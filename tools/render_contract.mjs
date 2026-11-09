import { chromium } from "playwright";
import { readFile } from "node:fs/promises";

// HTML comes from escaped, server-owned templates. Never fetch remote resources.
let html = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) html += chunk;
const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ javaScriptEnabled: false });
  await context.route("**/*", route => route.abort());
  const page = await context.newPage();
  await page.setContent(html, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.emulateMedia({ media: "print" });
  if (await page.locator('#editable-contract-terms').count()) {
    await page.evaluate(await readFile(new URL('../static/js/contract-pagination.js', import.meta.url), 'utf8'));
  }
  const overflow = await page.locator(".page.dynamic").evaluateAll(pages => pages.some(page => page.scrollHeight > page.clientHeight + 2));
  if (overflow) throw new Error("Contract content exceeds its page; shorten the fields before printing.");
  const pdf = await page.pdf({ format: "A4", printBackground: true, preferCSSPageSize: true });
  process.stdout.write(pdf);
} finally {
  await browser.close();
}
