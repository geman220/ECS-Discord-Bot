import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PAGES: { slug: string; url: string; risk: 'HIGH' | 'MEDIUM' | 'LOW' }[] = [
  // Originally audited (HIGH/MEDIUM/LOW from initial static analysis)
  { slug: 'dashboard', url: '/admin-panel/', risk: 'HIGH' },
  { slug: 'users-comprehensive', url: '/admin-panel/users/manage', risk: 'HIGH' },
  { slug: 'user-approvals', url: '/admin-panel/users/approvals', risk: 'HIGH' },
  { slug: 'roles-comprehensive', url: '/admin-panel/roles-management', risk: 'HIGH' },
  { slug: 'league-seasons', url: '/admin-panel/league-management/seasons', risk: 'MEDIUM' },
  { slug: 'league-teams', url: '/admin-panel/league-management/teams', risk: 'MEDIUM' },
  { slug: 'match-operations', url: '/admin-panel/match-operations', risk: 'MEDIUM' },
  { slug: 'substitute-management', url: '/admin-panel/substitute-management', risk: 'MEDIUM' },
  { slug: 'ecs-fc-matches', url: '/admin-panel/ecs-fc/matches', risk: 'MEDIUM' },
  { slug: 'communication-hub', url: '/admin-panel/communication', risk: 'MEDIUM' },
  { slug: 'email-broadcasts', url: '/admin-panel/communication/email-broadcasts', risk: 'MEDIUM' },
  { slug: 'email-broadcasts-compose', url: '/admin-panel/communication/email-broadcasts/compose', risk: 'HIGH' },
  { slug: 'push-notifications', url: '/admin-panel/push-notifications', risk: 'MEDIUM' },
  { slug: 'audit-logs', url: '/admin-panel/audit-logs', risk: 'HIGH' },
  { slug: 'system-monitoring', url: '/admin-panel/system-monitoring', risk: 'MEDIUM' },
  { slug: 'feature-toggles', url: '/admin-panel/features', risk: 'LOW' },
  // Expanded sweep — every other navigation-reachable admin page
  { slug: 'announcements', url: '/admin-panel/communication/announcements', risk: 'MEDIUM' },
  { slug: 'api-management', url: '/admin-panel/api/management', risk: 'MEDIUM' },
  { slug: 'appearance', url: '/admin-panel/appearance', risk: 'MEDIUM' },
  { slug: 'cache-redis', url: '/admin-panel/cache-redis', risk: 'MEDIUM' },
  { slug: 'campaigns-list', url: '/admin-panel/communication/campaigns', risk: 'MEDIUM' },
  { slug: 'coach-dashboard', url: '/admin-panel/coach-dashboard', risk: 'MEDIUM' },
  { slug: 'discord-bot-management', url: '/admin-panel/discord-bot', risk: 'MEDIUM' },
  { slug: 'discord-onboarding', url: '/admin-panel/discord/onboarding', risk: 'MEDIUM' },
  { slug: 'discord-overview', url: '/admin-panel/discord', risk: 'MEDIUM' },
  { slug: 'discord-players', url: '/admin-panel/discord/players', risk: 'MEDIUM' },
  { slug: 'discord-role-mapping', url: '/admin-panel/discord/role-mapping', risk: 'MEDIUM' },
  { slug: 'discord-roles', url: '/admin-panel/discord/roles', risk: 'MEDIUM' },
  { slug: 'docker-management', url: '/admin-panel/system/docker', risk: 'MEDIUM' },
  { slug: 'draft-history', url: '/admin-panel/draft/history', risk: 'MEDIUM' },
  { slug: 'draft-overview', url: '/admin-panel/draft', risk: 'MEDIUM' },
  { slug: 'duplicate-registrations', url: '/admin-panel/users/duplicates', risk: 'MEDIUM' },
  { slug: 'ecs-fc-dashboard', url: '/admin-panel/ecs-fc', risk: 'MEDIUM' },
  { slug: 'ecs-fc-import', url: '/admin-panel/ecs-fc/import', risk: 'MEDIUM' },
  { slug: 'ecs-fc-opponents', url: '/admin-panel/ecs-fc/opponents', risk: 'MEDIUM' },
  { slug: 'ecs-fc-sub-requests', url: '/admin-panel/ecs-fc/sub-requests', risk: 'MEDIUM' },
  { slug: 'email-templates-list', url: '/admin-panel/communication/email-templates', risk: 'MEDIUM' },
  { slug: 'feedback-list', url: '/admin-panel/feedback', risk: 'MEDIUM' },
  { slug: 'ispy-analytics', url: '/admin-panel/ispy/analytics', risk: 'MEDIUM' },
  { slug: 'ispy-management', url: '/admin-panel/ispy', risk: 'MEDIUM' },
  { slug: 'live-reporting-dashboard', url: '/admin-panel/mls/live-reporting', risk: 'MEDIUM' },
  { slug: 'manage-leagues', url: '/admin-panel/match-operations/leagues', risk: 'MEDIUM' },
  { slug: 'match-check-in-index', url: '/admin-panel/match-operations/check-in', risk: 'MEDIUM' },
  { slug: 'match-verification', url: '/admin-panel/match-verification', risk: 'MEDIUM' },
  { slug: 'message-templates', url: '/admin-panel/communication/messages', risk: 'MEDIUM' },
  { slug: 'messaging-settings', url: '/admin-panel/communication/messaging-settings', risk: 'MEDIUM' },
  { slug: 'mls-matches', url: '/admin-panel/mls/matches', risk: 'MEDIUM' },
  { slug: 'mls-overview', url: '/admin-panel/mls', risk: 'MEDIUM' },
  { slug: 'mls-sessions', url: '/admin-panel/mls/sessions', risk: 'MEDIUM' },
  { slug: 'mls-settings', url: '/admin-panel/mls/settings', risk: 'MEDIUM' },
  { slug: 'mls-task-monitoring', url: '/admin-panel/mls/task-monitoring', risk: 'MEDIUM' },
  { slug: 'mobile-analytics', url: '/admin-panel/mobile-features/mobile-analytics', risk: 'MEDIUM' },
  { slug: 'mobile-error-analytics', url: '/admin-panel/mobile-features/error-analytics', risk: 'MEDIUM' },
  { slug: 'mobile-features', url: '/admin-panel/mobile-features', risk: 'MEDIUM' },
  { slug: 'mobile-users', url: '/admin-panel/mobile-features/mobile-users', risk: 'MEDIUM' },
  { slug: 'notification-groups-list', url: '/admin-panel/communication/notification-groups', risk: 'MEDIUM' },
  { slug: 'quick-profiles-management', url: '/admin-panel/quick-profiles', risk: 'MEDIUM' },
  { slug: 'scheduled-messages-queue', url: '/admin-panel/communication/scheduled-messages/queue', risk: 'MEDIUM' },
  { slug: 'security-dashboard', url: '/admin-panel/system/security', risk: 'MEDIUM' },
  { slug: 'store-analytics', url: '/admin-panel/store/analytics', risk: 'MEDIUM' },
  { slug: 'store-items', url: '/admin-panel/store/items', risk: 'MEDIUM' },
  { slug: 'store-management', url: '/admin-panel/store', risk: 'MEDIUM' },
  { slug: 'store-orders', url: '/admin-panel/store/orders', risk: 'MEDIUM' },
  { slug: 'system-health', url: '/admin-panel/system-health', risk: 'MEDIUM' },
  { slug: 'task-monitoring-page', url: '/admin-panel/monitoring/tasks', risk: 'MEDIUM' },
  { slug: 'user-analytics', url: '/admin-panel/users/analytics', risk: 'MEDIUM' },
  { slug: 'user-waitlist', url: '/admin-panel/users/waitlist', risk: 'MEDIUM' },
];

interface PageReport {
  project: string;
  slug: string;
  url: string;
  risk: string;
  status: number | null;
  finalUrl: string;
  scrollWidth: number;
  clientWidth: number;
  overflow: number;
  consoleErrors: string[];
  pageErrors: string[];
  notes: string[];
}

async function measureOverflow(page: Page) {
  return await page.evaluate(() => {
    return {
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    };
  });
}

async function findOffscreenElements(page: Page): Promise<string[]> {
  return await page.evaluate(() => {
    const out: string[] = [];
    const vw = document.documentElement.clientWidth;
    document.querySelectorAll('*').forEach((el) => {
      const r = (el as HTMLElement).getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      if (r.right > vw + 1) {
        const id = el.id ? `#${el.id}` : '';
        const cls = (el.className && typeof el.className === 'string')
          ? '.' + el.className.split(/\s+/).slice(0, 2).join('.')
          : '';
        const sel = `${el.tagName.toLowerCase()}${id}${cls}`.slice(0, 80);
        const overflow = Math.round(r.right - vw);
        out.push(`${sel} (+${overflow}px)`);
      }
    });
    return out.slice(0, 5);
  });
}

// Detect content scrolled inside `.overflow-x-auto` wrappers — the document doesn't
// overflow but admin tables hide their action columns this way at phone widths.
async function findScrollHiddenContent(page: Page): Promise<string[]> {
  return await page.evaluate(() => {
    const out: string[] = [];
    const wrappers = document.querySelectorAll('.overflow-x-auto, [class*="overflow-x-scroll"]');
    wrappers.forEach((el) => {
      const hidden = el.scrollWidth - el.clientWidth;
      if (hidden > 4) {
        const tag = el.tagName.toLowerCase();
        const inside = el.querySelector('table') ? 'table' :
                       el.querySelector('thead th')  ? 'table-like' : 'content';
        // try to count <th> inside this wrapper
        const ths = el.querySelectorAll('thead th').length;
        const colHint = ths > 0 ? ` (${ths} cols)` : '';
        out.push(`${tag}.overflow-x ${inside}${colHint}: +${Math.round(hidden)}px hidden`);
      }
    });
    return out.slice(0, 5);
  });
}

const REPORT_DIR = path.join(__dirname, '.audit-report-rows');
const REPORT_MD = path.join(__dirname, 'audit-report.md');
const REPORT_JSON = path.join(__dirname, 'audit-report.json');

// Write each test's result to its own file under .audit-report-rows/.
// The aggregator reads them all in afterAll. Per-file writes avoid concurrency
// or module-reload issues that ate appends in the previous JSONL approach.
fs.mkdirSync(REPORT_DIR, { recursive: true });

function writeReport(r: PageReport) {
  const safe = `${r.project}__${r.slug}.json`.replace(/[^a-zA-Z0-9._-]/g, '_');
  fs.writeFileSync(path.join(REPORT_DIR, safe), JSON.stringify(r));
}

for (const pageInfo of PAGES) {
  test(`${pageInfo.slug} (${pageInfo.risk})`, async ({ page }, testInfo) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];

    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 200));
    });
    page.on('pageerror', (err) => {
      pageErrors.push(err.message.slice(0, 200));
    });

    const response = await page.goto(pageInfo.url, { waitUntil: 'domcontentloaded', timeout: 30_000 }).catch(() => null);
    const status = response ? response.status() : null;

    // Give async content (charts, late-rendered tables) time to settle without waiting for networkidle —
    // pages with long-polling never reach networkidle.
    await page.waitForLoadState('load', { timeout: 15_000 }).catch(() => undefined);
    await page.waitForTimeout(1500);

    const finalUrl = page.url();
    const dim = await measureOverflow(page);
    const overflow = dim.scrollWidth - dim.clientWidth;

    const notes: string[] = [];
    if (overflow > 1) {
      const offscreen = await findOffscreenElements(page);
      notes.push(`overflow=${overflow}px; first offenders: ${offscreen.join(', ')}`);
    }
    const scrollHidden = await findScrollHiddenContent(page);
    if (scrollHidden.length > 0) {
      notes.push(`scroll-hidden: ${scrollHidden.join('; ')}`);
    }

    const screenshotPath = path.join(
      __dirname,
      'screenshots',
      testInfo.project.name,
      `${pageInfo.slug}.png`
    );
    fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true });

    writeReport({
      project: testInfo.project.name,
      slug: pageInfo.slug,
      url: pageInfo.url,
      risk: pageInfo.risk,
      status,
      finalUrl,
      scrollWidth: dim.scrollWidth,
      clientWidth: dim.clientWidth,
      overflow,
      consoleErrors,
      pageErrors,
      notes,
    });

    expect(status, `Page returned non-2xx status`).toBeGreaterThanOrEqual(200);
    expect(status, `Page returned non-2xx status`).toBeLessThan(400);
    expect(finalUrl, `Page redirected to login`).not.toContain('/auth/login');
  });
}

test('mobile nav hamburger toggle works', async ({ page, viewport }) => {
  test.skip(!viewport || viewport.width >= 768, 'Only on phone-sized viewports');
  await page.goto('/admin-panel/', { waitUntil: 'networkidle' });

  const menu = page.locator('#admin-nav-mobile-menu');
  const toggle = page.locator('[data-action="admin-nav-mobile-toggle"]');

  await expect(toggle, 'Mobile nav toggle button should be visible').toBeVisible();
  await expect(menu, 'Mobile nav menu should start hidden').toHaveClass(/hidden/);

  await toggle.click();
  await expect(menu, 'Mobile nav menu should open after toggle').not.toHaveClass(/(^|\s)hidden(\s|$)/);

  const accordion = page.locator('[data-action="admin-nav-mobile-accordion"]').first();
  await expect(accordion, 'At least one accordion section should exist').toBeVisible();
  const accordionContent = accordion.locator('xpath=following-sibling::*[1]');
  const initiallyHidden = await accordionContent.evaluate((el) => el.classList.contains('hidden'));

  await accordion.click();
  await expect(accordionContent).toHaveClass(initiallyHidden ? /^(?!.*\bhidden\b).*/ : /\bhidden\b/);
});

test.afterAll(async () => {
  if (!fs.existsSync(REPORT_DIR)) return;
  const reports: PageReport[] = fs.readdirSync(REPORT_DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => JSON.parse(fs.readFileSync(path.join(REPORT_DIR, f), 'utf8')) as PageReport)
    .sort((a, b) => a.project.localeCompare(b.project) || a.slug.localeCompare(b.slug));
  if (reports.length === 0) return;

  fs.writeFileSync(REPORT_JSON, JSON.stringify(reports, null, 2));

  const lines: string[] = [];
  lines.push('# Mobile Audit Report');
  lines.push('');
  lines.push(`Generated: ${new Date().toISOString()}`);
  lines.push(`Total observations: ${reports.length}`);
  lines.push('');

  const byProject = new Map<string, PageReport[]>();
  for (const r of reports) {
    if (!byProject.has(r.project)) byProject.set(r.project, []);
    byProject.get(r.project)!.push(r);
  }

  for (const [project, rows] of byProject) {
    lines.push(`## ${project}`);
    lines.push('');
    lines.push('| Page | Risk | Status | Overflow | Console Errs | Notes |');
    lines.push('|------|------|--------|----------|--------------|-------|');
    for (const r of rows) {
      const overflowCell = r.overflow > 1 ? `**+${r.overflow}px**` : 'OK';
      const errCount = r.consoleErrors.length + r.pageErrors.length;
      const errCell = errCount > 0 ? `**${errCount}**` : '0';
      const notes = r.notes.join(' / ').slice(0, 120) || '';
      lines.push(`| ${r.slug} | ${r.risk} | ${r.status ?? 'ERR'} | ${overflowCell} | ${errCell} | ${notes} |`);
    }
    lines.push('');
  }

  const errors = reports.filter((r) => r.consoleErrors.length || r.pageErrors.length);
  if (errors.length > 0) {
    lines.push('## Console / Page Errors');
    lines.push('');
    for (const r of errors) {
      lines.push(`### ${r.project} / ${r.slug}`);
      for (const e of r.pageErrors) lines.push(`- pageerror: ${e}`);
      for (const e of r.consoleErrors) lines.push(`- console.error: ${e}`);
      lines.push('');
    }
  }

  fs.writeFileSync(REPORT_MD, lines.join('\n'));
  console.log(`\n[mobile-audit] Wrote audit-report.md (${reports.length} rows)`);
});
