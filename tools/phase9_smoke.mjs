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

await page.goto(`${base}/listings/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Explore our properties" }).isVisible())) failures.push("public listing index missing");
if (await page.locator(".listing-card").count() < 1) failures.push("published demo listings missing");
if (!(await page.locator('meta[name="description"]').getAttribute("content"))) failures.push("SEO description missing");
if (!(await page.locator('link[rel="canonical"]').getAttribute("href"))) failures.push("canonical URL missing");
await page.screenshot({ path: new URL("phase9-public-desktop.png", output).pathname, fullPage: true });
await page.locator(".listing-card .listing-link").first().click();
if (!(await page.getByRole("link", { name: "Apply now" }).isVisible())) failures.push("public property application action missing");

await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${base}/listings/`, { waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase9-public-mobile.png", output).pathname, fullPage: true });

await page.setViewportSize({ width: 1440, height: 1000 });
await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
await page.locator("#id_username").fill("admin");
await page.locator("#id_password").fill("admin");
await Promise.all([page.waitForURL(`${base}/**`), page.getByRole("button", { name: "Sign in", exact: true }).click()]);
await page.goto(`${base}/applications/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Rental applications" }).isVisible())) failures.push("application queue missing");
if (await page.locator(".data-table tbody tr").count() < 1) failures.push("demo application missing");
await page.getByRole("link", { name: "Open" }).first().click();
if (!(await page.getByRole("heading", { name: "Rental offer snapshot" }).isVisible())) failures.push("application offer snapshot missing");
await page.screenshot({ path: new URL("phase9-application-workspace.png", output).pathname, fullPage: true });
await page.goto(`${base}/settings/public-portal/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Public portal and SEO" }).isVisible())) failures.push("public portal settings missing");

await browser.close();
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Phase 9 browser smoke passed: listings, SEO, responsive public pages, application review, and public settings.");
