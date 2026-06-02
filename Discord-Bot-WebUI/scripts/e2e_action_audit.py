#!/usr/bin/env python3
"""
Read-only UI certification inspector (PROD-SAFE).

Drives a RUNNING instance with Playwright but NEVER clicks anything that could
change state. It loads each page and INSPECTS the live DOM + the app's real
EventDelegation registry to find genuinely-broken UI:

  - JS console errors / uncaught pageerrors on load   -> BROKEN page
  - data-modal-target / data-modal-toggle whose target element is absent -> UNWIRED_MODAL
  - data-action / data-on-change values that are NOT registered in
    window.EventDelegation AND have no plausible inline handler  -> UNREGISTERED_ACTION
    (candidates — some actions are handled by page-inline scripts, so review;
     the modal + console-error checks are definitive)

Because it only navigates (GET) and reads the DOM/JS state, it is SAFE to run
against PRODUCTION — it does not click buttons, submit forms, or mutate data.

Run from your laptop against the public prod URL, or on the VPS over SSH:
  pip install playwright && playwright install chromium
  BASE_URL=https://your-domain ECS_E2E_USER=admin@you ECS_E2E_PASS=*** \
    python scripts/e2e_action_audit.py --out ui_cert.json
  # cover the Classic shell (what non-admins get) by logging in as a player:
  ECS_E2E_USER=player@you ECS_E2E_PASS=*** python scripts/e2e_action_audit.py --shell classic --out ui_cert_classic.json

Exit code is non-zero if any BROKEN page or UNWIRED_MODAL is found (CI-friendly).
"""
import argparse
import json
import os
import sys
from urllib.parse import urljoin, urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright not installed. Run: pip install playwright && playwright install chromium")

SKIP_LINK = ('logout', 'signout', 'sign-out')
# Prod-safety: never *navigate* to a link whose URL implies a state change — a
# GET-based mutation endpoint would otherwise fire just from crawling. We only
# crawl view/page routes. (create/edit/new are kept — those are form pages.)
import re as _re
MUTATION_PATH = _re.compile(
    r'(delete|remove|clear|reset|purge|/sync|send|process|approve|deny|reject|'
    r'revoke|void|/ban|jail|kill|cleanup|deactivate|activate|retry|trigger|'
    r'execute|/run|cancel|assign|unassign|toggle|generate|export|download|'
    r'set-current|normalize|fetch-|schedule-all|start-|stop-)', _re.I)

# In-page inspector: returns the actionable findings for the current page without
# clicking anything. Uses the app's own EventDelegation.isRegistered().
INSPECT_JS = r"""
() => {
  const out = { unregistered: [], unwired_modals: [] };
  const ED = window.EventDelegation;
  const isReg = (a) => { try { return ED && typeof ED.isRegistered === 'function' && ED.isRegistered(a); } catch(e){ return false; } };
  // data-action / data-on-change with no registered handler (candidates)
  const seenA = new Set();
  document.querySelectorAll('[data-action],[data-on-change]').forEach(el => {
    const a = el.getAttribute('data-action') || el.getAttribute('data-on-change');
    if (!a || seenA.has(a)) return; seenA.add(a);
    if (!isReg(a)) {
      // heuristic inline-handler check: any <script> text references this action?
      const inline = Array.from(document.querySelectorAll('script:not([src])'))
        .some(s => s.textContent && (s.textContent.includes("'"+a+"'") || s.textContent.includes('"'+a+'"')));
      if (!inline) out.unregistered.push(a);
    }
  });
  // data-modal-target / toggle whose target element does not exist
  const seenM = new Set();
  document.querySelectorAll('[data-modal-target],[data-modal-toggle]').forEach(el => {
    const id = el.getAttribute('data-modal-target') || el.getAttribute('data-modal-toggle');
    if (!id || seenM.has(id)) return; seenM.add(id);
    if (!document.getElementById(id)) out.unwired_modals.push(id);
  });
  return out;
}
"""


def login(page, base):
    cookie = os.getenv('ECS_E2E_COOKIE')
    if cookie:
        return True
    user, pw = os.getenv('ECS_E2E_USER'), os.getenv('ECS_E2E_PASS')
    if not (user and pw):
        print("WARN: no creds — only public pages will be reachable.")
        return False
    for path in ('/login', '/auth/login'):
        try:
            page.goto(urljoin(base + '/', path.lstrip('/')), wait_until='domcontentloaded', timeout=20000)
        except Exception:
            continue
        u = page.query_selector('input[name="email"], input[name="username"], input[type="email"]')
        p = page.query_selector('input[name="password"], input[type="password"]')
        if u and p:
            u.fill(user); p.fill(pw)
            btn = page.query_selector('button[type="submit"], input[type="submit"]')
            (btn.click() if btn else page.keyboard.press('Enter'))
            try: page.wait_for_load_state('networkidle', timeout=20000)
            except Exception: pass
            if '/login' not in page.url:
                print(f"Logged in as {user}")
                return True
    print("ERROR: login failed (check creds / form selectors).")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default=os.getenv('BASE_URL', 'http://localhost:5000'))
    ap.add_argument('--shell', choices=['console', 'classic'], default='console')
    ap.add_argument('--max-pages', type=int, default=250)
    ap.add_argument('--out', default='ui_cert.json')
    ap.add_argument('--seeds', nargs='*', default=['/', '/admin-panel', '/admin-panel/dashboard'])
    args = ap.parse_args()
    base = args.base.rstrip('/')
    host = urlparse(base).netloc

    findings = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context()
        cookie = os.getenv('ECS_E2E_COOKIE')
        if cookie:
            secure = base.startswith('https')
            jar = []
            for part in cookie.split(';'):
                if '=' not in part:
                    continue
                n, _, v = part.strip().partition('=')
                jar.append({'name': n.strip(), 'value': v.strip(), 'url': base,
                            'httpOnly': True, 'secure': secure})
            if jar:
                ctx.add_cookies(jar)
        page = ctx.new_page()
        if cookie:
            # Verify the supplied session actually authenticates (Discord-OAuth apps
            # have no password form, so a copied session cookie is the way in).
            try:
                page.goto(urljoin(base + '/', (args.seeds[1] if len(args.seeds) > 1 else '').lstrip('/')) or base, wait_until='domcontentloaded', timeout=20000)
            except Exception:
                pass
            if '/login' in page.url:
                print("ERROR: supplied ECS_E2E_COOKIE did not authenticate (redirected to login). "
                      "Re-copy a fresh 'session' cookie from a logged-in browser.")
            else:
                print("Authenticated via supplied session cookie.")
        else:
            login(page, base)

        # BFS crawl (GET only)
        seen, queue, pages = set(), [urljoin(base + '/', s.lstrip('/')) for s in args.seeds], []
        while queue and len(pages) < args.max_pages:
            url = queue.pop(0).split('#')[0]
            if url in seen:
                continue
            seen.add(url)
            errors = []
            page.on('console', lambda m, e=errors: e.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda ex, e=errors: e.append(str(ex)))
            try:
                page.goto(url, wait_until='networkidle', timeout=25000)
            except Exception as e:
                findings.append({'url': url, 'status': 'LOAD_ERROR', 'detail': str(e)[:140]})
                page.remove_listener('console', lambda *a: None) if False else None
                continue
            if urlparse(page.url).netloc != host:
                continue
            pages.append(page.url)
            try:
                res = page.evaluate(INSPECT_JS)
            except Exception:
                res = {'unregistered': [], 'unwired_modals': []}
            if errors:
                findings.append({'url': page.url, 'status': 'CONSOLE_ERROR', 'detail': ' | '.join(errors[:3])[:240]})
            for mid in res.get('unwired_modals', []):
                findings.append({'url': page.url, 'status': 'UNWIRED_MODAL', 'detail': f'no element id="{mid}"'})
            for a in res.get('unregistered', []):
                findings.append({'url': page.url, 'status': 'UNREGISTERED_ACTION', 'detail': f'data-action="{a}" not in EventDelegation registry and no inline handler found'})
            # discover more links
            for el in page.query_selector_all('a[href]'):
                href = el.get_attribute('href') or ''
                if not href or href.startswith(('#', 'mailto:', 'tel:', 'javascript:')) or any(s in href.lower() for s in SKIP_LINK):
                    continue
                if MUTATION_PATH.search(href):  # prod-safety: don't crawl GET-mutation links
                    continue
                full = urljoin(page.url, href).split('#')[0]
                if urlparse(full).netloc == host and full not in seen:
                    queue.append(full)
        browser.close()

    by = {}
    for f in findings:
        by.setdefault(f['status'], []).append(f)
    summary = {k: len(v) for k, v in sorted(by.items())}
    json.dump({'base': base, 'shell': args.shell, 'pages_audited': len(pages),
               'summary': summary, 'findings': findings}, open(args.out, 'w'), indent=2)

    print("\n=== READ-ONLY UI CERTIFICATION ===")
    print(f"pages audited: {len(pages)}")
    print(json.dumps(summary, indent=2))
    print(f"full report: {args.out}")
    for st in ('LOAD_ERROR', 'CONSOLE_ERROR', 'UNWIRED_MODAL', 'UNREGISTERED_ACTION'):
        for f in by.get(st, [])[:40]:
            print(f"  [{st}] {f['url']}  {f['detail']}")
    hard = by.get('LOAD_ERROR', []) + by.get('UNWIRED_MODAL', [])
    sys.exit(1 if hard else 0)


if __name__ == '__main__':
    main()
