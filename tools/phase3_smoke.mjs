import { chromium } from "playwright";
import fs from "node:fs/promises";

const base = process.env.BASE_URL || "https://omanskylight.com";
const out = new URL("../artifacts/", import.meta.url);
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const failures = [];
page.on("console", (message) => { if (message.type() === "error") failures.push(`console: ${message.text()}`); });
page.on("pageerror", (error) => failures.push(`page: ${error.message}`));

await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
await page.locator("#id_username").fill("admin");
await page.locator("#id_password").fill("admin");
await Promise.all([page.waitForURL(`${base}/**`), page.getByRole("button", { name: "Sign in", exact: true }).click()]);
await page.goto(`${base}/properties/`, { waitUntil: "networkidle" });
if (await page.locator(".inventory-card").count() < 4) failures.push("expected four demo properties");
await page.screenshot({ path: new URL("phase3-properties-desktop.png", out).pathname, fullPage: true });

await page.goto(`${base}/properties/al-mouj-waves/?tab=units`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Al Mouj Waves" }).isVisible())) failures.push("property workspace heading missing");
if (await page.locator(".data-table tbody tr").count() < 3) failures.push("demo units missing");
await page.goto(`${base}/properties/al-mouj-waves/?tab=pricing`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Unit type rates" }).isVisible())) failures.push("pricing workspace missing");
if (await page.getByText("OMR 690.000").count() === 0) failures.push("unit override price missing");

await page.goto(`${base}/properties/transfer/`, { waitUntil: "networkidle" });
if (await page.locator(".transfer-card").count() < 4) failures.push("CSV datasets missing");
const downloadPromise = page.waitForEvent("download");
await page.getByRole("link", { name: "Export" }).nth(2).click();
const download = await downloadPromise;
if (!(await download.suggestedFilename()).includes("units-export")) failures.push("unit export filename incorrect");
await page.goto(`${base}/properties/master-data/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Types & amenities" }).isVisible())) failures.push("inventory master data missing");

await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${base}/properties/qurum-heights/?tab=pricing`, { waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase3-pricing-mobile.png", out).pathname, fullPage: true });

const publicPage = await context.newPage();
await publicPage.goto(`${base}/listings/`, { waitUntil: "networkidle" });
if (!(await publicPage.getByText("Jabal Akhdar Retreat").isVisible())) failures.push("whole-property public demo missing");
await publicPage.goto(`${base}/listings/al-mouj-waves/unit-types/two-bedroom/`, { waitUntil: "networkidle" });
if (!(await publicPage.getByRole("heading", { name: "Two bedroom" }).isVisible())) failures.push("public unit type detail missing");

await browser.close();
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Phase 3 browser smoke passed: inventory, rates, CSV export, responsive workspace, and public listing.");
