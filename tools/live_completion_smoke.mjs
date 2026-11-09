import { chromium } from "playwright";

const base = process.env.BASE_URL || "https://omanskylight.com";
const password = process.env.PMS_TEST_PASSWORD;
if (!password) throw new Error("PMS_TEST_PASSWORD is required");

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const failures = [];
page.on("pageerror", error => failures.push(`page: ${error.message}`));

await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
await page.locator("#id_username").fill("admin");
await page.locator("#id_password").fill(password);
await Promise.all([page.waitForURL(url => url.origin === base && url.pathname !== "/login/"), page.locator(".login-form button[type=submit]").click()]);

for (const path of ["/", "/account/profile/", "/account/security/", "/password-reset/", "/settings/mail/", "/settings/whatsapp/", "/invoices/", "/leases/", "/maintenance/"]) {
  const response = await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
  if (!response || response.status() !== 200) failures.push(`${path}: HTTP ${response?.status()}`);
}
for (const path of ["/leases/2/move/", "/maintenance/1/transition/"]) {
  const response = await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
  if (!response || response.status() >= 500) failures.push(`${path}: HTTP ${response?.status()}`);
}
const searchResponse = await page.goto(`${base}/search/?q=Atheer`, { waitUntil: "networkidle" });
if (!searchResponse || searchResponse.status() !== 200 || !(await page.getByText(/Atheer/i).first().isVisible())) failures.push("production scoped search did not return Atheer");

await page.goto(`${base}/invoices/`, { waitUntil: "networkidle" });
const invoiceHref = await page.locator('table tbody a[href^="/invoices/"]').first().getAttribute("href").catch(() => null);
if (invoiceHref) {
  await page.goto(`${base}${invoiceHref}`, { waitUntil: "networkidle" });
  const pdfHref = await page.locator('a[href$="/download/"]').first().getAttribute("href").catch(() => null);
  const pdf = pdfHref ? await context.request.get(`${base}${pdfHref}`) : null;
  if (!pdf || pdf.status() !== 200 || !(await pdf.body()).subarray(0, 5).equals(Buffer.from("%PDF-"))) failures.push("production invoice PDF is unavailable or invalid");
}

await browser.close();
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("Live read-only smoke passed: login, profile/security, provider settings, Atheer search, invoices, leases, maintenance, and PDF delivery.");
