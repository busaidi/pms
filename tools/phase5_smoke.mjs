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

await page.goto(`${base}/invoices/`, { waitUntil: "networkidle" });
if (await page.locator(".data-table tbody tr").count() !== 25) failures.push("expected a full paginated invoice page");
const invoiceCountText = await page.getByText(/^\d+ invoices$/).textContent();
if (!invoiceCountText || Number.parseInt(invoiceCountText, 10) < 51) failures.push("expected at least 51 reconciled invoices");
await page.goto(`${base}/invoices/?status=paid`, { waitUntil: "networkidle" });
if (await page.locator("tr", { hasText: "INV-2026-0001" }).count() !== 1) failures.push("paid demo invoice missing");
await page.goto(`${base}/invoices/`, { waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase5-invoices-desktop.png", output).pathname, fullPage: true });
await page.getByRole("link", { name: "Open" }).first().click();
if (!(await page.getByRole("heading", { name: /^INV/ }).isVisible())) failures.push("invoice workspace did not open");
if (!(await page.getByText("Signed payment link").isVisible())) failures.push("signed payment link missing");
const signedUrl = await page.locator('input[readonly]').inputValue();

const downloadPromise = page.waitForEvent("download");
await page.getByRole("link", { name: "Download PDF" }).click();
const download = await downloadPromise;
const downloadedPath = await download.path();
if (!downloadedPath || !(await fs.readFile(downloadedPath)).subarray(0, 5).equals(Buffer.from("%PDF-"))) failures.push("invoice PDF is invalid");

await page.setViewportSize({ width: 390, height: 844 });
await page.goto(page.url(), { waitUntil: "networkidle" });
await page.screenshot({ path: new URL("phase5-invoice-mobile.png", output).pathname, fullPage: true });

await page.setViewportSize({ width: 1440, height: 1000 });
await page.goto(`${base}/payments/`, { waitUntil: "networkidle" });
if (await page.locator(".data-table tbody tr").count() < 1) failures.push("confirmed demo payment missing");
await page.screenshot({ path: new URL("phase5-payments-desktop.png", output).pathname, fullPage: true });
await page.goto(`${base}/settings/payment-gateway/`, { waitUntil: "networkidle" });
if (!(await page.getByRole("heading", { name: "Payment gateway" }).isVisible())) failures.push("payment gateway settings missing");

const publicContext = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 } });
const publicPage = await publicContext.newPage();
await publicPage.goto(signedUrl, { waitUntil: "networkidle" });
if (!(await publicPage.getByText("Amount due").isVisible())) failures.push("anonymous signed payment page missing");
await publicPage.screenshot({ path: new URL("phase5-signed-payment-mobile.png", output).pathname, fullPage: true });

await browser.close();
if (failures.length) { console.error(failures.join("\n")); process.exit(1); }
console.log("Phase 5 browser smoke passed: invoice ledger, workspace, PDF, payments, signed checkout, and mobile layouts.");
