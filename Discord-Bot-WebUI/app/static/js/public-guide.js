/**
 * Public Guide reader chrome (progressive enhancement).
 *
 * Loaded ONLY on the public /guide page (see public/page_sections.html). The
 * guide is one long sections document (~9 chapters, 40+ subsections) rendered
 * server-side; this module adds navigation on top of whatever headings exist
 * in the DOM, so it keeps working after admins edit the page in the site
 * builder:
 *   - sticky toolbar under the site nav: Contents button, scrollspy label
 *     showing the current chapter, search, and a reading-progress bar
 *   - dropdown panel with a two-level TOC (h2 chapters / h3 subsections)
 *   - client-side full-text search with jump-to-match + flash highlight
 *   - back-to-top button
 *
 * No jQuery on purpose — the Vite inject() plugin only adds the import when
 * `$` is referenced, and this must stay a small standalone chunk.
 */

const MIN_CHAPTERS = 3;        // below this the page isn't "long" — do nothing
const SEARCH_MIN_CHARS = 2;
const SEARCH_MAX_RESULTS = 40;

function esc(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function slugify(text) {
  return text.toLowerCase().trim()
    .replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-').slice(0, 80) || 'section';
}

/* Ensure every h2/h3 has a unique id so the TOC and search can link to it.
   Seeded chapters ship h2 ids from the converter; h3s (and any headings admins
   add later in the builder) get generated ones. */
function ensureIds(headings) {
  const seen = new Set(headings.map((h) => h.id).filter(Boolean));
  headings.forEach((h) => {
    if (!h.id) {
      let base = slugify(h.textContent); let id = base; let n = 2;
      while (seen.has(id)) id = `${base}-${n++}`;
      seen.add(id); h.id = id;
    }
  });
}

/* Outline = ordered chapters (h2) each owning the h3s that follow it. */
function buildOutline(main) {
  const headings = Array.from(main.querySelectorAll('h2, h3'));
  ensureIds(headings);
  const chapters = [];
  headings.forEach((h) => {
    if (h.tagName === 'H2') {
      chapters.push({ el: h, title: h.textContent.trim(), subs: [] });
    } else if (chapters.length) {
      chapters[chapters.length - 1].subs.push({ el: h, title: h.textContent.trim() });
    }
  });
  return { chapters, headings };
}

/* Flat text index for search: every prose-ish element tagged with its chapter.
   Content ABOVE the first h2 (the hero blurb, the intro/download paragraphs)
   is real on-page text and must be findable too — it gets a pseudo-chapter. */
function buildSearchIndex(main, chapters) {
  const index = [];
  let chapter = { title: 'Introduction' };
  const walk = main.querySelectorAll('h2, h3, h4, p, li, dt, dd');
  walk.forEach((el) => {
    if (el.tagName === 'H2') {
      const c = chapters.find((ch) => ch.el === el);
      if (c) chapter = c;
      return; // chapter titles are already in the TOC
    }
    // Skip nav content (the server-rendered "What's inside" card): its links
    // duplicate chapter titles and the card is hidden once we mount, so a
    // search hit there would jump to an invisible element.
    if (el.closest('nav')) return;
    const text = el.textContent.replace(/\s+/g, ' ').trim();
    if (text) index.push({ el, text, chapter, isHeading: el.tagName === 'H3' });
  });
  return index;
}

function snippet(text, q) {
  const at = text.toLowerCase().indexOf(q.toLowerCase());
  const start = Math.max(0, at - 40);
  const end = Math.min(text.length, at + q.length + 60);
  const pre = (start > 0 ? '…' : '') + esc(text.slice(start, at));
  const hit = esc(text.slice(at, at + q.length));
  const post = esc(text.slice(at + q.length, end)) + (end < text.length ? '…' : '');
  return `${pre}<mark class="bg-ecs-green/20 dark:bg-ecs-green/30 text-inherit rounded-sm px-0.5">${hit}</mark>${post}`;
}

function flashTarget(el) {
  const box = el.closest('li, dd, dt, p, h2, h3, h4') || el;
  box.classList.add('transition-colors', 'duration-700', 'rounded-lg',
    'bg-ecs-green/15', 'dark:bg-ecs-green/25');
  setTimeout(() => box.classList.remove('bg-ecs-green/15', 'dark:bg-ecs-green/25'), 1600);
}

function init() {
  const main = document.querySelector('main');
  if (!main) return;
  const { chapters } = buildOutline(main);
  if (chapters.length < MIN_CHAPTERS) return;
  const searchIndex = buildSearchIndex(main, chapters);

  // The server-rendered "What's inside" card is superseded by this toolbar;
  // keep it in the markup for no-JS visitors and crawlers, hide it here.
  const inlineToc = main.querySelector('nav[aria-label="Guide contents"]');
  if (inlineToc) (inlineToc.closest('section') || inlineToc).classList.add('hidden');

  // ---- Toolbar ----------------------------------------------------------
  const bar = document.createElement('div');
  bar.className = 'sticky z-30 border-b border-gray-200 dark:border-gray-800 '
    + 'bg-white/95 dark:bg-gray-950/95 backdrop-blur';
  // The site header is sticky with a variable top (admin bar shifts it), so
  // compute our resting offset from it instead of hardcoding top-16.
  const hdr = document.querySelector('header');
  const hdrTop = hdr ? (parseFloat(getComputedStyle(hdr).top) || 0) : 0;
  const barTop = hdrTop + (hdr ? hdr.offsetHeight : 64);
  bar.style.top = `${barTop}px`;

  // Anchor clearance: the macro's scroll-mt-24 (96px) predates this toolbar —
  // header + bar is ~112px (more with the admin bar), so jumped-to headings
  // would tuck underneath. Inline style wins over the class.
  const anchorClearance = `${barTop + 48 + 16}px`;
  main.querySelectorAll('h2, h3').forEach((h) => {
    h.style.scrollMarginTop = anchorClearance;
  });

  bar.innerHTML = `
    <div class="relative mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
      <div class="flex h-12 items-center gap-2">
        <button type="button" data-guide-toggle aria-expanded="false"
                class="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold
                       text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition">
          <i class="ti ti-list-details text-base"></i>
          <span class="hidden sm:inline">Contents</span>
          <i class="ti ti-chevron-down text-xs transition-transform" data-guide-chevron></i>
        </button>
        <span class="min-w-0 flex-1 truncate text-sm text-gray-500 dark:text-gray-400" data-guide-current></span>
        <button type="button" data-guide-search-open aria-label="Search the guide"
                class="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium
                       text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition">
          <i class="ti ti-search text-base"></i>
          <span class="hidden sm:inline">Search</span>
        </button>
      </div>
      <div class="absolute inset-x-0 bottom-0 h-0.5 bg-gray-100 dark:bg-gray-800">
        <div class="h-full w-0 bg-ecs-green" data-guide-progress></div>
      </div>
      <div class="absolute inset-x-0 top-full hidden" data-guide-panel>
        <div class="mx-2 sm:mx-4 mt-1 rounded-xl border border-gray-200 dark:border-gray-800
                    bg-white dark:bg-gray-950 shadow-xl overflow-hidden">
          <div class="border-b border-gray-100 dark:border-gray-800 p-3">
            <div class="relative">
              <i class="ti ti-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"></i>
              <input type="search" data-guide-search placeholder="Search the guide…"
                     aria-label="Search the guide" autocomplete="off"
                     class="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900
                            py-2 pl-9 pr-3 text-sm text-gray-900 dark:text-white placeholder-gray-400
                            focus:border-ecs-green focus:ring-ecs-green/40 focus:ring-2 focus:outline-none">
            </div>
          </div>
          <div class="max-h-[60vh] overflow-y-auto overscroll-contain p-2" data-guide-list></div>
        </div>
      </div>
    </div>`;
  main.prepend(bar);

  const panel = bar.querySelector('[data-guide-panel]');
  const list = bar.querySelector('[data-guide-list]');
  const searchInput = bar.querySelector('[data-guide-search]');
  const toggleBtn = bar.querySelector('[data-guide-toggle]');
  const chevron = bar.querySelector('[data-guide-chevron]');
  const currentLabel = bar.querySelector('[data-guide-current]');
  const progress = bar.querySelector('[data-guide-progress]');

  // ---- TOC / search result rendering ------------------------------------
  const chapterLink = 'block rounded-lg px-3 py-2 text-sm font-semibold hover:bg-gray-50 dark:hover:bg-gray-900';
  const subLink = 'block rounded-lg px-3 py-1.5 pl-8 text-sm hover:bg-gray-50 dark:hover:bg-gray-900';

  function renderToc(activeId) {
    list.innerHTML = chapters.map((c, i) => {
      const on = c.el.id === activeId;
      const subs = c.subs.map((s) => {
        const sOn = s.el.id === activeId;
        return `<a href="#${s.el.id}" class="${subLink} ${sOn
          ? 'text-ecs-green dark:text-ecs-blue-400 font-medium'
          : 'text-gray-600 dark:text-gray-300'}">${esc(s.title)}</a>`;
      }).join('');
      return `<a href="#${c.el.id}" class="${chapterLink} ${on
        ? 'text-ecs-green dark:text-ecs-blue-400'
        : 'text-gray-900 dark:text-white'}">
          <span class="mr-2 inline-block w-5 text-right text-xs font-normal text-gray-400">${i + 1}</span>${esc(c.title)}
        </a>${subs}`;
    }).join('');
  }

  function renderResults(q) {
    const needle = q.toLowerCase();
    // Collect ALL matches, THEN rank and cap — capping the document-order walk
    // first would let 40 early body hits crowd out a matching heading in a
    // late chapter, defeating the headings-first ranking where it matters.
    let hits = searchIndex.filter((item) => item.text.toLowerCase().includes(needle));
    // Heading hits first — they're better jump targets than body text.
    hits.sort((a, b) => Number(b.isHeading) - Number(a.isHeading));
    hits = hits.slice(0, SEARCH_MAX_RESULTS);
    if (!hits.length) {
      list.innerHTML = `<p class="px-3 py-6 text-center text-sm text-gray-500 dark:text-gray-400">
        No matches for “${esc(q)}”.</p>`;
      return;
    }
    list.innerHTML = hits.map((h, i) => `
      <button type="button" data-guide-hit="${i}"
              class="block w-full rounded-lg px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-900">
        <span class="block text-[11px] font-semibold uppercase tracking-wide text-ecs-green dark:text-ecs-blue-400">
          ${esc(h.chapter.title)}</span>
        <span class="block text-sm text-gray-700 dark:text-gray-300">${snippet(h.text, q)}</span>
      </button>`).join('');
    list.querySelectorAll('[data-guide-hit]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const hit = hits[Number(btn.dataset.guideHit)];
        closePanel();
        hit.el.style.scrollMarginTop = anchorClearance;
        hit.el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        flashTarget(hit.el);
      });
    });
  }

  // ---- Panel open/close --------------------------------------------------
  let open = false;
  function openPanel(focusSearch) {
    open = true;
    panel.classList.remove('hidden');
    toggleBtn.setAttribute('aria-expanded', 'true');
    chevron.classList.add('rotate-180');
    if (!searchInput.value.trim()) renderToc(currentId);
    if (focusSearch) searchInput.focus();
  }
  function closePanel() {
    open = false;
    panel.classList.add('hidden');
    toggleBtn.setAttribute('aria-expanded', 'false');
    chevron.classList.remove('rotate-180');
  }
  toggleBtn.addEventListener('click', () => (open ? closePanel() : openPanel(false)));
  bar.querySelector('[data-guide-search-open]').addEventListener('click', () => openPanel(true));
  document.addEventListener('click', (e) => {
    if (open && !bar.contains(e.target)) closePanel();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && open) { closePanel(); return; }
    // "/" jumps to guide search unless the user is already typing somewhere.
    if (e.key === '/' && !open && !/^(input|textarea|select)$/i.test(e.target.tagName)) {
      e.preventDefault(); openPanel(true);
    }
  });
  list.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (!a) return;
    // Smooth-scroll TOC jumps ourselves (matches search-result jumps) but keep
    // the hash in the URL so the position is shareable/bookmarkable.
    const target = document.getElementById(a.getAttribute('href').slice(1));
    if (target) {
      e.preventDefault();
      closePanel();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      history.pushState(null, '', a.getAttribute('href'));
    } else {
      closePanel();
    }
  });
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim();
    if (q.length >= SEARCH_MIN_CHARS) renderResults(q);
    else renderToc(currentId);
  });

  // ---- Scrollspy + progress + back-to-top -------------------------------
  const topBtn = document.createElement('button');
  topBtn.type = 'button';
  topBtn.setAttribute('aria-label', 'Back to top');
  topBtn.className = 'fixed bottom-5 right-5 z-30 hidden h-11 w-11 items-center justify-center '
    + 'rounded-full bg-gray-900/80 dark:bg-gray-700/90 text-white shadow-lg backdrop-blur '
    + 'hover:bg-ecs-green transition';
  topBtn.innerHTML = '<i class="ti ti-arrow-up text-lg"></i>';
  topBtn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  document.body.appendChild(topBtn);

  const spyTargets = [];
  chapters.forEach((c) => {
    spyTargets.push({ el: c.el, chapter: c, label: c.title });
    c.subs.forEach((s) => spyTargets.push({ el: s.el, chapter: c, label: `${c.title} › ${s.title}` }));
  });

  let currentId = null;
  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const line = bar.getBoundingClientRect().bottom + 16;
      let active = null;
      for (const t of spyTargets) {
        if (t.el.getBoundingClientRect().top <= line) active = t;
        else break;
      }
      currentLabel.textContent = active ? active.label : '';
      const newId = active ? active.el.id : null;
      if (newId !== currentId) {
        currentId = newId;
        if (open && searchInput.value.trim().length < SEARCH_MIN_CHARS) renderToc(currentId);
      }
      const doc = document.documentElement;
      const max = doc.scrollHeight - window.innerHeight;
      progress.style.width = max > 0 ? `${Math.min(100, (window.scrollY / max) * 100)}%` : '0%';
      topBtn.classList.toggle('hidden', window.scrollY < 600);
      topBtn.classList.toggle('flex', window.scrollY >= 600);
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
