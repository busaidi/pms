import { chromium } from "playwright";
import fs from "node:fs/promises";

const base = process.env.BASE_URL || "https://omanskylight.com";
const password = process.env.PMS_TEST_PASSWORD;
if (!password) throw new Error("PMS_TEST_PASSWORD is required");

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const failures = [];
page.on("console", message => { if (message.type() === "error") failures.push(`console: ${message.text()}`); });
page.on("pageerror", error => failures.push(`page: ${error.message}`));

await page.goto(`${base}/listings/`, { waitUntil: "networkidle" });
await Promise.all([
  page.waitForURL(`${base}/listings/`),
  page.locator(".language-switcher button").click(),
]);
if (await page.locator("html").getAttribute("lang") !== "ar") failures.push("Arabic language was not activated");
if (await page.locator("html").getAttribute("dir") !== "rtl") failures.push("Arabic page is not RTL");
if (!(await page.getByRole("heading", { name: "استكشف عقاراتنا" }).isVisible())) failures.push("public Arabic copy missing");

await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
if (!(await page.getByText("اسم المستخدم", { exact: true }).isVisible())) failures.push("Arabic login label missing");
await page.locator("#id_username").fill("admin");
await page.locator("#id_password").fill(password);
await Promise.all([
  page.waitForURL(url => url.origin === base && url.pathname !== "/login/", { waitUntil: "networkidle" }),
  page.locator('.login-form button[type="submit"]').click(),
]);
await Promise.all([
  page.waitForURL(url => url.origin === base, { waitUntil: "networkidle" }),
  page.locator(".language-switcher button").click(),
]);
if (!(await page.getByRole("heading", { name: "نظرة عامة على المحفظة" }).isVisible())) failures.push("Arabic dashboard missing");

await fs.mkdir("artifacts", { recursive: true });
await page.screenshot({ path: "artifacts/arabic-dashboard-desktop.png", fullPage: true });
await page.setViewportSize({ width: 390, height: 844 });
await page.reload({ waitUntil: "networkidle" });
await page.screenshot({ path: "artifacts/arabic-dashboard-mobile.png", fullPage: true });
if (await page.locator("body").evaluate(body => body.scrollWidth > body.clientWidth + 2)) failures.push("Arabic mobile page has horizontal overflow");

await context.addCookies([{ name: "django_language", value: "en", url: base }]);
await page.goto(`${base}/account/profile/`, { waitUntil: "networkidle" });
if (await page.locator("html").getAttribute("lang") !== "ar") failures.push("Saved profile language did not override a stale cookie");
if (!(await page.getByRole("heading", { name: "الملف الشخصي", exact: true }).isVisible())) failures.push("Arabic profile page missing");

await browser.close();
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Arabic smoke passed: switcher, RTL pages, saved profile preference, login, dashboard, and mobile layout.");
