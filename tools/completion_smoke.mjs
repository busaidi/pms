import { chromium } from "playwright";
import fs from "node:fs/promises";

const base = process.env.BASE_URL || "http://127.0.0.1:8765";
const output = new URL("../artifacts/", import.meta.url);
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const failures = [];
page.on("console", message => { if (message.type() === "error") failures.push(`console: ${message.text()}`); });
page.on("pageerror", error => failures.push(`page: ${error.message}`));

await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
await page.locator("#id_username").fill("admin");
await page.locator("#id_password").fill("admin");
await Promise.all([page.waitForURL(`${base}/**`), page.getByRole("button", { name: "Sign in", exact: true }).click()]);
if (await page.locator("html").getAttribute("lang") === "ar") {
  await Promise.all([page.waitForLoadState("networkidle"), page.locator(".language-switcher button").click()]);
}

const tenantName = `Browser Workflow Tenant ${Date.now()}`;
await page.goto(`${base}/tenants/new/`, { waitUntil: "networkidle" });
await page.locator("#id_full_name").fill(tenantName);
await page.locator("#id_email").fill(`browser-${Date.now()}@example.test`);
await page.locator("#id_phone").fill("92999999");
await page.locator("#id_id_number").fill(`BROWSER-${Date.now()}`);
await Promise.all([page.waitForURL(/\/tenants\/\d+\/$/), page.getByRole("button", { name: "Save", exact: true }).click()]);
if (!(await page.getByRole("heading", { name: tenantName }).isVisible())) failures.push("tenant creation did not reach the tenant workspace");

await page.locator('input[name="q"]').fill("Al Mouj");
await page.locator('input[name="q"]').press("Enter");
await page.waitForLoadState("networkidle");
if (!(await page.getByText("Al Mouj Waves", { exact: true }).first().isVisible())) failures.push("global search did not return the seeded property");

await page.goto(`${base}/account/security/`, { waitUntil: "networkidle" });
for (const label of ["Two-factor authentication", "Passkeys", "Change password"]) {
  if (!(await page.getByText(label, { exact: true }).first().isVisible())) failures.push(`security action missing: ${label}`);
}
await page.goto(`${base}/account/confirm-password/`, { waitUntil: "networkidle" });
await page.locator('#id_password').fill("admin");
await Promise.all([page.waitForURL(`${base}/account/security/`), page.getByRole("button", { name: "Confirm password" }).click()]);
const status = await context.request.get(`${base}/account/confirmed-password-status/`);
if (status.status() !== 200 || !(await status.json()).confirmed) failures.push("password confirmation status was not persisted");

await page.goto(`${base}/settings/mail/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Mail settings" }).isVisible())) failures.push("mail settings page missing");
await page.goto(`${base}/settings/whatsapp/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "WhatsApp settings" }).isVisible())) failures.push("WhatsApp settings page missing");

await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${base}/search/?q=Al+Mouj`, { waitUntil: "networkidle" });
if (await page.locator("body").evaluate(body => body.scrollWidth > body.clientWidth + 2)) failures.push("mobile search has horizontal overflow");
await page.screenshot({ path: new URL("completion-search-mobile.png", output).pathname, fullPage: true });

await browser.close();
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("Completion browser smoke passed: tenant creation, scoped search, password confirmation, account security, provider settings, and mobile layout.");
