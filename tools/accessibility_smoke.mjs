import { chromium } from "playwright";
import fs from "node:fs/promises";

const base = process.env.BASE_URL || "https://omanskylight.com";
const password = process.env.PMS_TEST_PASSWORD || "admin";
const axePath = new URL("../node_modules/axe-core/axe.min.js", import.meta.url);
const axeSource = await fs.readFile(axePath, "utf8");
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const reports = [];

async function audit(name, url) {
  await page.goto(url, { waitUntil: "networkidle" });
  await page.addScriptTag({ content: axeSource });
  const result = await page.evaluate(async () => await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } }));
  const violations = result.violations.filter(item => ["critical", "serious"].includes(item.impact));
  reports.push({ name, url, violations: violations.map(item => ({ id: item.id, impact: item.impact, help: item.help, nodes: item.nodes.map(node => node.target) })) });
}

await audit("public listings", `${base}/listings/`);
await audit("login", `${base}/login/`);
await page.locator("#id_username").fill("admin");
await page.locator("#id_password").fill(password);
await Promise.all([page.waitForURL(`${base}/**`), page.getByRole("button", { name: "Sign in", exact: true }).click()]);
await audit("staff dashboard", `${base}/`);
await audit("resident portal", `${base}/portal/`);
await page.setViewportSize({ width: 390, height: 844 });
await audit("resident portal mobile", `${base}/portal/`);

await browser.close();
await fs.mkdir("artifacts", { recursive: true });
await fs.writeFile("artifacts/phase13-accessibility.json", JSON.stringify(reports, null, 2) + "\n");
const violations = reports.flatMap(report => report.violations.map(item => `${report.name}: ${item.impact} ${item.id} (${item.nodes.length} nodes)`));
if (violations.length) {
  console.error(violations.join("\n"));
  process.exit(1);
}
console.log("Accessibility smoke passed with no critical or serious WCAG A/AA violations across public, login, staff, resident, and mobile views.");
