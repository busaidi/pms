import { chromium } from "playwright";
import fs from "node:fs/promises";

const base = process.env.BASE_URL || "https://omanskylight.com";
const output = new URL("../artifacts/", import.meta.url);
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const failures = [];
page.on("console", message => { if (message.type() === "error") failures.push(`console: ${message.text()}`); });
page.on("pageerror", error => failures.push(`page: ${error.message}`));

await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
await page.locator("#id_username").fill("admin");
await page.locator("#id_password").fill("admin");
await Promise.all([page.waitForURL(`${base}/**`), page.getByRole("button", { name: "Sign in", exact: true }).click()]);
await page.goto(`${base}/settings/integrations/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Integrations and extensions" }).isVisible())) failures.push("integration management missing");
for (const provider of ["Manual bank transfer", "Django email", "WhatsApp log"]) {
  if (!(await page.getByText(provider, { exact: true }).isVisible())) failures.push(`${provider} missing`);
}
if (!(await page.getByText("Reference extension", { exact: true }).isVisible())) failures.push("reference extension missing");
await page.screenshot({ path: new URL("phase11-integrations-desktop.png", output).pathname, fullPage: true });
await page.getByRole("link", { name: "Open lifecycle probe" }).click();
if (!(await page.getByRole("heading", { name: "Event listener result" }).isVisible())) failures.push("extension event probe missing");
const health = await context.request.get(`${base}/settings/extensions/health/`);
if (health.status() !== 200 || (await health.json()).status !== "ok") failures.push("extension health is degraded");
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${base}/settings/integrations/`, { waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase11-integrations-mobile.png", output).pathname, fullPage: true });

await browser.close();
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Phase 11 browser smoke passed: providers, extension registries, event probe, health, and mobile UI.");
