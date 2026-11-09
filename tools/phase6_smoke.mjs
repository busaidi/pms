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

await page.goto(`${base}/maintenance/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Maintenance" }).isVisible())) failures.push("maintenance list heading missing");
if (await page.locator(".data-table tbody tr").count() < 1) failures.push("demo maintenance ticket missing");
await page.screenshot({ path: new URL("phase6-maintenance-desktop.png", output).pathname, fullPage: true });
await page.getByRole("link", { name: "Open" }).first().click();
if (!(await page.getByText("Status history").isVisible())) failures.push("maintenance status history missing");
if (!(await page.getByText("Unit blocked").isVisible())) failures.push("unit blocking status missing");

await page.setViewportSize({ width: 390, height: 844 });
await page.goto(page.url(), { waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase6-maintenance-mobile.png", output).pathname, fullPage: true });

await page.setViewportSize({ width: 1440, height: 1000 });
await page.goto(`${base}/notifications/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Notifications" }).isVisible())) failures.push("notifications page missing");
await page.goto(`${base}/settings/reminders/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Rent reminders" }).isVisible())) failures.push("reminder settings page missing");
if (!(await page.getByText("Recent deliveries").isVisible())) failures.push("reminder delivery log missing");
await page.screenshot({ path: new URL("phase6-reminders-desktop.png", output).pathname, fullPage: true });

await browser.close();
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("Phase 6 browser smoke passed: maintenance list/workspace, mobile layout, notifications, and reminder settings.");
