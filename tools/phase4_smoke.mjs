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

await page.goto(`${base}/tenants/`, { waitUntil: "networkidle" });
if (await page.locator(".data-table tbody tr").count() < 5) failures.push("five demo tenants were not rendered");
await page.screenshot({ path: new URL("phase4-tenants-desktop.png", output).pathname, fullPage: true });
const demoTenantRow = page.locator("tr", { hasText: "Ahmed Al Balushi" });
if (await demoTenantRow.count() !== 1) failures.push("demo tenant is missing");
else await demoTenantRow.getByRole("link", { name: "Open" }).click();
if (!(await page.getByRole("heading", { name: "Ahmed Al Balushi" }).isVisible())) failures.push("tenant workspace did not open");

await page.goto(`${base}/leases/`, { waitUntil: "networkidle" });
if (await page.locator(".data-table tbody tr").count() < 5) failures.push("five demo leases were not rendered");
const wholeRow = page.locator("tr", { hasText: "Jabal Akhdar Retreat" });
if (await wholeRow.count() !== 1) failures.push("whole-property lease is missing");
else await wholeRow.getByRole("link").click();
if (!(await page.getByRole("heading", { name: /^LSX/ }).isVisible())) failures.push("lease workspace did not open");
if (await page.locator("#schedule tbody tr").count() !== 7) failures.push("daily whole-property schedule should contain seven periods");
await page.screenshot({ path: new URL("phase4-lease-desktop.png", output).pathname, fullPage: true });

await page.setViewportSize({ width: 390, height: 844 });
await page.reload({ waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase4-lease-mobile.png", output).pathname, fullPage: true });

await page.goto(`${base}/leases/expirations/?days=90`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Upcoming expirations" }).isVisible())) failures.push("expiration selection page missing");
await page.goto(`${base}/properties/transfer/`, { waitUntil: "networkidle" });
if (await page.locator(".transfer-card").count() !== 5) failures.push("tenant CSV dataset missing");

await browser.close();
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("Phase 4 browser smoke passed: tenants, whole-property lease, schedule, mobile workspace, expirations, and tenant CSV.");
