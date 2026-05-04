import { chromium, FullConfig } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const AUTH_FILE = path.join(__dirname, 'auth.json');
const BASE_URL = process.env.MOBILE_AUDIT_BASE_URL || 'http://localhost:5000';
const EMAIL = process.env.MOBILE_AUDIT_EMAIL;
const PASSWORD = process.env.MOBILE_AUDIT_PASSWORD;
const REUSE_EXISTING = process.env.MOBILE_AUDIT_REUSE_AUTH === '1';
const HEADED_LOGIN = process.env.MOBILE_AUDIT_HEADED === '1';

async function globalSetup(_config: FullConfig) {
  if (REUSE_EXISTING && fs.existsSync(AUTH_FILE)) {
    console.log('[mobile-audit] Reusing existing auth.json (MOBILE_AUDIT_REUSE_AUTH=1)');
    return;
  }

  if (HEADED_LOGIN) {
    await runHeadedLogin();
    return;
  }

  if (!EMAIL || !PASSWORD) {
    throw new Error(
      '[mobile-audit] Set MOBILE_AUDIT_EMAIL and MOBILE_AUDIT_PASSWORD env vars, ' +
      'or set MOBILE_AUDIT_HEADED=1 for interactive Discord login, ' +
      'or set MOBILE_AUDIT_REUSE_AUTH=1 to reuse a previously captured auth.json.'
    );
  }

  console.log(`[mobile-audit] Logging in as ${EMAIL} via ${BASE_URL}/auth/login`);
  const browser = await chromium.launch();
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  await page.goto(`${BASE_URL}/auth/login`, { waitUntil: 'domcontentloaded' });

  await page.evaluate(() => {
    const section = document.getElementById('emailLoginSection');
    if (section) section.classList.remove('hidden');
  });

  await page.fill('#email', EMAIL);
  await page.fill('#password', PASSWORD);

  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes('/auth/login'), { timeout: 30_000 }),
    page.click('button[type="submit"]:has-text("Sign In with Email")'),
  ]);

  const finalUrl = page.url();
  if (finalUrl.includes('/auth/login') || finalUrl.includes('/auth/verify-2fa')) {
    throw new Error(`[mobile-audit] Login appears to have failed or hit 2FA. Final URL: ${finalUrl}`);
  }

  await context.storageState({ path: AUTH_FILE });
  await browser.close();
  console.log(`[mobile-audit] Saved storageState to ${AUTH_FILE}`);
}

async function runHeadedLogin() {
  console.log('[mobile-audit] Headed login: complete the sign-in flow manually in the browser window.');
  console.log(`[mobile-audit] Target: ${BASE_URL}`);
  console.log('[mobile-audit] Waiting up to 10 minutes for you to land on a logged-in page on the target host...');
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await page.goto(`${BASE_URL}/auth/login`).catch(() => undefined);

  const targetHost = new URL(BASE_URL).host;
  const isLoggedInUrl = (urlStr: string): boolean => {
    let u: URL;
    try { u = new URL(urlStr); } catch { return false; }
    if (u.host !== targetHost) return false;
    const p = u.pathname;
    if (p === '' || p === '/about:blank') return false;
    if (p.startsWith('/auth/login')) return false;
    if (p.startsWith('/auth/discord')) return false;
    if (p.includes('verify_2fa') || p.includes('two-factor') || p.includes('verify-2fa')) return false;
    if (p.includes('verify')) return false;
    if (p.startsWith('/auth/forgot') || p.startsWith('/auth/reset')) return false;
    return true;
  };

  const deadline = Date.now() + 10 * 60_000;
  let lastUrl = '';
  while (Date.now() < deadline) {
    let url = '';
    try { url = page.url(); } catch { /* page may transiently be detached during nav */ }
    if (url && url !== lastUrl) {
      console.log(`[mobile-audit] current url: ${url}`);
      lastUrl = url;
    }
    if (url && isLoggedInUrl(url)) {
      // Confirm the page actually loaded (not just URL changed mid-redirect)
      try {
        await page.waitForLoadState('domcontentloaded', { timeout: 5_000 });
        // Settled — break out
        break;
      } catch {
        // Still navigating, keep polling
      }
    }
    await new Promise((r) => setTimeout(r, 1_000));
  }

  const finalUrl = page.url();
  if (!isLoggedInUrl(finalUrl)) {
    await browser.close().catch(() => undefined);
    throw new Error(`[mobile-audit] Did not detect logged-in URL within timeout. Last URL: ${finalUrl}`);
  }

  console.log(`[mobile-audit] Detected logged-in URL: ${finalUrl}`);
  await context.storageState({ path: AUTH_FILE });
  await browser.close();
  console.log(`[mobile-audit] Saved storageState to ${AUTH_FILE}`);
}

export default globalSetup;
