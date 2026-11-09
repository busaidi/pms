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
await page.goto(`${base}/portal/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: /Welcome/ }).isVisible())) failures.push("resident dashboard missing");
if (!(await page.getByRole("link", { name: "Staff app" }).isVisible())) failures.push("dual staff/tenant navigation missing");
await page.screenshot({ path: new URL("phase10-portal-desktop.png", output).pathname, fullPage: true });

await page.goto(`${base}/portal/applications/`, { waitUntil: "networkidle" });
if (!(await page.getByText("Fatma Al Farsi").or(page.getByText("Al Mouj Waves")).first().isVisible())) failures.push("applicant tracking missing");
await page.goto(`${base}/portal/leases/`, { waitUntil: "networkidle" });
if (await page.locator(".inventory-card").count() < 1) failures.push("resident lease missing");
await page.goto(`${base}/portal/invoices/`, { waitUntil: "networkidle" });
if (await page.locator(".data-table tbody tr").count() < 1) failures.push("resident invoice history missing");
await page.getByRole("link", { name: "Open" }).first().click();
if (!(await page.getByRole("heading", { name: "Charges" }).isVisible())) failures.push("resident invoice detail missing");
if (!(await page.getByRole("link", { name: "Download PDF" }).isVisible())) failures.push("resident invoice download missing");
await page.goto(`${base}/portal/maintenance/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("link", { name: "Report an issue" }).isVisible())) failures.push("resident maintenance action missing");

await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${base}/portal/`, { waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase10-portal-mobile.png", output).pathname, fullPage: true });
if (await page.locator("body").evaluate(body => body.scrollWidth > body.clientWidth + 2)) failures.push("mobile portal has horizontal overflow");

await browser.close();
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Phase 10 browser smoke passed: dual identity, applications, leases, invoices, maintenance, and mobile portal.");
