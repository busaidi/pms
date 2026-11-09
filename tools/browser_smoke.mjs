import { chromium } from "playwright";

const baseUrl = process.env.PMS_BASE_URL || "https://omanskylight.com";
const username = process.env.PMS_TEST_USERNAME || "admin";
const password = process.env.PMS_TEST_PASSWORD;

if (!password) throw new Error("PMS_TEST_PASSWORD is required");

const browser = await chromium.launch({ headless: true });
const errors = [];

async function capture(viewport, suffix) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`${suffix}: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`${suffix}: ${error.message}`));

  await page.goto(`${baseUrl}/login/`, { waitUntil: "networkidle" });
  if (suffix === "desktop") {
    await page.screenshot({ path: "docs/design/login-live.png", fullPage: true });
  }
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await Promise.all([
    page.waitForURL(`${baseUrl}/`),
    page.getByRole("button", { name: "Sign in", exact: true }).click(),
  ]);
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: `docs/design/dashboard-${suffix}.png`, fullPage: true });

  if (suffix === "desktop" && process.env.PMS_TEST_PASSKEY === "1") {
    const cdp = await context.newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true } });
    await page.goto(`${baseUrl}/account/security/`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Register passkey" }).click();
    await page.waitForFunction(() => document.body.textContent.includes("1 registered") || document.querySelector(".passkey-message")?.textContent);
    await page.screenshot({ path: "docs/design/security-live.png", fullPage: true });
    if (!(await page.getByText("1 registered").isVisible())) errors.push(`desktop: passkey was not registered: ${await page.locator(".passkey-message").textContent()}`);
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByLabel("Username").fill(username);
    await page.getByRole("button", { name: "Sign in with a passkey" }).click();
    await page.waitForURL(`${baseUrl}/`);
    await page.goto(`${baseUrl}/roles/`, { waitUntil: "networkidle" });
    await page.screenshot({ path: "docs/design/roles-live.png", fullPage: true });
    await page.goto(`${baseUrl}/team/`, { waitUntil: "networkidle" });
    if (!(await page.getByRole("heading", { name: "Team" }).isVisible())) errors.push("desktop: team page unavailable");
  }

  if (suffix === "mobile") {
    const menu = page.locator("[data-sidebar-open]");
    await menu.click();
    if ((await menu.getAttribute("aria-expanded")) !== "true") {
      errors.push("mobile: navigation did not open");
    }
  }
  await context.close();
}

await capture({ width: 1440, height: 1024 }, "desktop");
await capture({ width: 390, height: 844 }, "mobile");

const publicContext = await browser.newContext({ viewport: { width: 1440, height: 1024 } });
const publicPage = await publicContext.newPage();
publicPage.on("console", (message) => {
  if (message.type() === "error") errors.push(`public: ${message.text()}`);
});
publicPage.on("pageerror", (error) => errors.push(`public: ${error.message}`));
await publicPage.goto(`${baseUrl}/listings/`, { waitUntil: "networkidle" });
await publicPage.getByRole("link", { name: "Al Mouj Waves" }).click();
await publicPage.waitForLoadState("networkidle");
await publicPage.screenshot({ path: "docs/design/public-listing-live.png", fullPage: true });
if (!(await publicPage.getByRole("link", { name: "Apply now" }).isVisible())) {
  errors.push("public: application entry point is not visible");
}
await publicContext.close();
await browser.close();

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log("Browser smoke test passed at desktop and mobile viewports.");
