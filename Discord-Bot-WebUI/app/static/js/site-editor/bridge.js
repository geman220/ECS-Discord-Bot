// app/static/js/site-editor/bridge.js
//
// In-iframe half of the site editor. Loaded ONLY by edit-mode section renders
// (?edit=1, server-gated to Site Editors) inside the editor shell's
// same-origin iframe. The page IS the edit surface:
//   - hover/tap highlights sections ([data-sid]) and blocks ([data-bid])
//   - floating in-frame toolbars (must live in THIS document — TinyMCE inline
//     cannot manage a contenteditable across the frame boundary)
//   - text blocks ([data-editable=html]) edit in place via TinyMCE inline
//     (vendored lib injected on demand; contenteditable fallback)
//   - structural ops are sent to the parent shell (postMessage), which owns
//     the document state + server writes; the parent sends back rendered
//     section HTML to swap in (one rendering source of truth: Jinja)
//
// Protocol (bridge -> parent): ready, select, op {kind: move-section/
// duplicate-section/delete-section/move-block/duplicate-block/delete-block/
// add-section/add-block/edit-block/edit-section}, text-change {bid, html}.
// (parent -> bridge): swap-section {sid, html}, remove-section {sid},
// refresh-page {html}, deselect.

/* eslint-env browser */

const parentWin = window.parent;
const SAME = window.location.origin;

function post(msg) {
  try { parentWin.postMessage({ __siteEditor: true, ...msg }, SAME); } catch (e) { /* no-op */ }
}

// ---------------------------------------------------------------------------
// Selection + toolbars
// ---------------------------------------------------------------------------

let selected = null; // {kind: 'section'|'block', el, sid, bid}
let toolbarEl = null;
let outlineEl = null;

function ensureChrome() {
  if (outlineEl) return;
  outlineEl = document.createElement('div');
  outlineEl.id = 'pse-outline';
  outlineEl.style.cssText = 'position:absolute;pointer-events:none;border:2px solid #2563eb;' +
    'border-radius:6px;z-index:9998;display:none;box-shadow:0 0 0 4px rgba(37,99,235,.15);';
  document.body.appendChild(outlineEl);
  toolbarEl = document.createElement('div');
  toolbarEl.id = 'pse-toolbar';
  toolbarEl.style.cssText = 'position:absolute;z-index:9999;display:none;';
  document.body.appendChild(toolbarEl);
  toolbarEl.addEventListener('click', onToolbarClick);
}

function rectOf(el) {
  const r = el.getBoundingClientRect();
  return { top: r.top + window.scrollY, left: r.left + window.scrollX, w: r.width, h: r.height };
}

function positionChrome(el) {
  const r = rectOf(el);
  outlineEl.style.display = 'block';
  outlineEl.style.top = `${r.top - 2}px`;
  outlineEl.style.left = `${r.left - 2}px`;
  outlineEl.style.width = `${r.w + 4}px`;
  outlineEl.style.height = `${r.h + 4}px`;
  toolbarEl.style.display = 'flex';
  const tbTop = Math.max(8, r.top - 40);
  toolbarEl.style.top = `${tbTop}px`;
  toolbarEl.style.left = `${Math.max(8, r.left)}px`;
}

const BTN = 'display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;' +
  'background:#111827;color:#fff;border:0;cursor:pointer;font-size:15px;';

function toolbarHtml(kind) {
  const b = (act, label, title) =>
    `<button type="button" data-act="${act}" title="${title}" style="${BTN}">${label}</button>`;
  const wrap = (inner) =>
    `<div style="display:flex;border-radius:8px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,.25);">${inner}</div>`;
  if (kind === 'section') {
    return wrap(
      b('edit-section', '⚙', 'Section settings') + b('add-section', '＋', 'Add section below') +
      b('move-section-up', '↑', 'Move up') + b('move-section-down', '↓', 'Move down') +
      b('duplicate-section', '⧉', 'Duplicate') + b('delete-section', '🗑', 'Delete section'));
  }
  return wrap(
    b('edit-block', '✎', 'Edit block') + b('add-block', '＋', 'Add block after') +
    b('move-block-up', '↑', 'Move up') + b('move-block-down', '↓', 'Move down') +
    b('duplicate-block', '⧉', 'Duplicate') + b('delete-block', '🗑', 'Delete block'));
}

function select(kind, el) {
  ensureChrome();
  deactivateTextEditing();
  const sectionEl = el.closest('[data-sid]');
  selected = {
    kind, el,
    sid: sectionEl ? sectionEl.getAttribute('data-sid') : null,
    bid: kind === 'block' ? el.getAttribute('data-bid') : null,
    btype: kind === 'block' ? el.getAttribute('data-btype') : null,
  };
  toolbarEl.innerHTML = toolbarHtml(kind);
  positionChrome(el);
  post({ type: 'select', kind, sid: selected.sid, bid: selected.bid, btype: selected.btype });
}

function deselect() {
  selected = null;
  if (outlineEl) outlineEl.style.display = 'none';
  if (toolbarEl) toolbarEl.style.display = 'none';
  deactivateTextEditing();
}

function onToolbarClick(e) {
  const btn = e.target.closest('[data-act]');
  if (!btn || !selected) return;
  e.preventDefault();
  e.stopPropagation();
  const act = btn.getAttribute('data-act');
  if (act === 'edit-block' && selected.el.getAttribute('data-editable') === 'html') {
    activateTextEditing(selected.el);
    return;
  }
  post({ type: 'op', kind: act, sid: selected.sid, bid: selected.bid, btype: selected.btype });
}

// Click routing: text blocks go straight to inline editing; anything inside a
// block selects the block; otherwise the section. Links never navigate in
// edit mode.
document.addEventListener('click', (e) => {
  if (e.target.closest('#pse-toolbar, .pse-addblock, .pse-drag')) return;
  const a = e.target.closest('a');
  if (a) e.preventDefault();
  const editable = e.target.closest('[data-editable="html"]');
  const block = e.target.closest('[data-bid]');
  const section = e.target.closest('[data-sid]');
  if (editable && activeTextEl === editable) return; // typing
  if (editable) {
    select('block', editable);
    activateTextEditing(editable);
    return;
  }
  if (block) { select('block', block); return; }
  if (section) { select('section', section); return; }
  deselect();
  post({ type: 'deselect' });
}, true);

document.addEventListener('submit', (e) => e.preventDefault(), true);

// Hover affordance (desktop): light outline on hoverable targets.
let hoverEl = null;
document.addEventListener('mouseover', (e) => {
  const t = e.target.closest('[data-bid], [data-sid]');
  if (t === hoverEl) return;
  if (hoverEl && hoverEl !== (selected && selected.el)) hoverEl.style.outline = '';
  hoverEl = t;
  if (hoverEl && hoverEl !== (selected && selected.el)) {
    hoverEl.style.outline = '1px dashed rgba(37,99,235,.6)';
    hoverEl.style.outlineOffset = '2px';
  }
});

// ---------------------------------------------------------------------------
// Inline text editing (TinyMCE inline inside THIS document)
// ---------------------------------------------------------------------------

let activeTextEl = null;
let activeEditor = null;
let tinyLoading = null;
let textDebounce = null;

function loadTiny() {
  if (window.tinymce) return Promise.resolve();
  if (tinyLoading) return tinyLoading;
  tinyLoading = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = '/static/vendor/tinymce/tinymce.min.js';
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('tinymce load failed'));
    document.head.appendChild(s);
  });
  return tinyLoading;
}

function emitText(el) {
  clearTimeout(textDebounce);
  textDebounce = setTimeout(() => {
    post({ type: 'text-change', bid: el.getAttribute('data-bid'), html: el.innerHTML });
  }, 400);
}

function activateTextEditing(el) {
  if (activeTextEl === el) return;
  deactivateTextEditing();
  activeTextEl = el;
  loadTiny().then(() => {
    if (activeTextEl !== el) return;
    window.tinymce.init({
      target: el,
      inline: true,
      menubar: false,
      license_key: 'gpl',
      toolbar: 'blocks | bold italic | link | bullist numlist | removeformat',
      block_formats: 'Paragraph=p; Heading 2=h2; Heading 3=h3; Heading 4=h4',
      // img MUST be here or TinyMCE silently strips every inline image from the
      // richtext the moment you click to edit it (the sanitizer allows img, so
      // these are valid content). Keep it in sync with html_sanitizer img attrs.
      valid_elements: 'p,br,strong/b,em/i,u,s,a[href|title|target],ul,ol,li,' +
        'h1,h2,h3,h4,blockquote,span[class],code,img[src|alt|width|height|loading]',
      setup(ed) {
        activeEditor = ed;
        ed.on('input change Undo Redo', () => emitText(el));
        ed.on('blur', () => {
          clearTimeout(textDebounce);
          post({ type: 'text-change', bid: el.getAttribute('data-bid'), html: el.innerHTML });
        });
      },
    });
  }).catch(() => {
    // Fallback: raw contenteditable (server sanitizes everything anyway).
    el.setAttribute('contenteditable', 'true');
    el.focus();
    el.addEventListener('input', () => emitText(el));
  });
}

function deactivateTextEditing() {
  if (activeEditor) {
    try { activeEditor.destroy(); } catch (e) { /* no-op */ }
    activeEditor = null;
  }
  if (activeTextEl) {
    activeTextEl.removeAttribute('contenteditable');
    activeTextEl = null;
  }
}

// ---------------------------------------------------------------------------
// Drag-and-drop section reordering (SortableJS, loaded on demand)
// ---------------------------------------------------------------------------

let sortLoading = null;
function loadSortable() {
  if (window.Sortable) return Promise.resolve();
  if (sortLoading) return sortLoading;
  sortLoading = new Promise((resolve) => {
    const s = document.createElement('script');
    s.src = '/static/vendor/libs/sortablejs/sortable.js';
    s.onload = () => resolve();
    s.onerror = () => resolve(); // degrade to the up/down buttons
    document.head.appendChild(s);
  });
  return sortLoading;
}

function addDragHandle(sectionEl) {
  if (sectionEl.querySelector(':scope > .pse-drag')) return;
  if (getComputedStyle(sectionEl).position === 'static') sectionEl.style.position = 'relative';
  const h = document.createElement('div');
  h.className = 'pse-drag';
  h.title = 'Drag to reorder section';
  h.textContent = '⠿';
  h.style.cssText = 'position:absolute;top:8px;right:8px;z-index:9997;width:28px;height:28px;' +
    'display:flex;align-items:center;justify-content:center;background:#111827;color:#fff;' +
    'border-radius:6px;cursor:grab;opacity:0;transition:opacity .15s;font-size:15px;line-height:1;';
  sectionEl.addEventListener('mouseenter', () => { h.style.opacity = '1'; });
  sectionEl.addEventListener('mouseleave', () => { h.style.opacity = '0'; });
  sectionEl.appendChild(h);
}

// A persistent "＋ Add block / widget" bar at the bottom of every section — the
// discoverable way to add blocks/widgets (otherwise you must find a block's + ).
function addBlockBar(sectionEl) {
  if (sectionEl.querySelector(':scope > .pse-addblock')) return;
  const bar = document.createElement('button');
  bar.type = 'button';
  bar.className = 'pse-addblock';
  bar.textContent = '＋ Add block / widget';
  bar.style.cssText = 'position:relative;z-index:9996;display:block;width:100%;padding:10px;' +
    'background:rgba(37,99,235,.10);color:#1d4ed8;border:0;border-top:1px dashed rgba(37,99,235,.5);' +
    'cursor:pointer;font-size:13px;font-weight:700;letter-spacing:.02em;';
  bar.addEventListener('mouseenter', () => { bar.style.background = 'rgba(37,99,235,.20)'; });
  bar.addEventListener('mouseleave', () => { bar.style.background = 'rgba(37,99,235,.10)'; });
  bar.addEventListener('click', (e) => {
    e.stopPropagation();
    post({ type: 'op', kind: 'add-block-in-section', sid: sectionEl.getAttribute('data-sid') });
  });
  sectionEl.appendChild(bar);
}

let sortContainer = null;
function setupDrag() {
  loadSortable().then(() => {
    if (!window.Sortable) return;
    const first = document.querySelector('[data-sid]');
    if (!first || !first.parentElement) return;
    const container = first.parentElement;
    // (Re)decorate every top-level section with a drag handle + add-block bar —
    // new ones arrive via swap/insert after this ran the first time.
    container.querySelectorAll(':scope > [data-sid]').forEach((el) => { addDragHandle(el); addBlockBar(el); });
    if (container === sortContainer) return; // Sortable already wired here
    sortContainer = container;
    new window.Sortable(container, {
      draggable: '[data-sid]',
      handle: '.pse-drag',
      animation: 150,
      onStart() { deselect(); post({ type: 'deselect' }); },
      onEnd() {
        const order = Array.from(container.querySelectorAll(':scope > [data-sid]'))
          .map((el) => el.getAttribute('data-sid'));
        post({ type: 'op', kind: 'reorder-sections', order });
      },
    });
  });
}

// ---------------------------------------------------------------------------
// Parent -> bridge commands
// ---------------------------------------------------------------------------

window.addEventListener('message', (e) => {
  if (e.origin !== SAME || !e.data || !e.data.__siteEditor) return;
  const msg = e.data;
  if (msg.type === 'swap-section') {
    const el = document.querySelector(`[data-sid="${CSS.escape(msg.sid)}"]`);
    if (el && typeof msg.html === 'string') {
      deselect();
      const tpl = document.createElement('template');
      tpl.innerHTML = msg.html.trim();
      const fresh = tpl.content.firstElementChild;
      if (fresh) el.replaceWith(fresh);
      setupDrag();
    }
  } else if (msg.type === 'insert-section') {
    // html + afterSid (null = prepend)
    const tpl = document.createElement('template');
    tpl.innerHTML = (msg.html || '').trim();
    const fresh = tpl.content.firstElementChild;
    if (!fresh) return;
    const anchor = msg.afterSid
      ? document.querySelector(`[data-sid="${CSS.escape(msg.afterSid)}"]`) : null;
    if (anchor) anchor.after(fresh); else document.querySelector('main, body').prepend(fresh);
    fresh.scrollIntoView({ behavior: 'smooth', block: 'center' });
    setupDrag();
  } else if (msg.type === 'remove-section') {
    const el = document.querySelector(`[data-sid="${CSS.escape(msg.sid)}"]`);
    if (el) { deselect(); el.remove(); }
  } else if (msg.type === 'move-section-dom') {
    const el = document.querySelector(`[data-sid="${CSS.escape(msg.sid)}"]`);
    if (!el) return;
    const sib = msg.dir === 'up' ? el.previousElementSibling : el.nextElementSibling;
    if (sib && sib.hasAttribute('data-sid')) {
      if (msg.dir === 'up') sib.before(el); else sib.after(el);
      if (selected && selected.el === el) positionChrome(el);
    }
  } else if (msg.type === 'refresh-page') {
    window.location.reload();
  } else if (msg.type === 'deselect') {
    deselect();
  }
});

window.addEventListener('scroll', () => { if (selected) positionChrome(selected.el); },
  { passive: true });
window.addEventListener('resize', () => { if (selected) positionChrome(selected.el); });

post({ type: 'ready' });
setupDrag();
