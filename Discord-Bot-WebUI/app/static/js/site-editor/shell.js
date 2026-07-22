// app/static/js/site-editor/shell.js
//
// Parent half of the site editor (the /admin-panel/site-editor/<id> page).
// Owns the document state, the save protocol, and the panels; the iframe
// bridge owns in-place selection/typing. One rendering source of truth: every
// structural change round-trips through the server, which returns Jinja-
// rendered section HTML for the bridge to swap in.
//
// Save protocol: every write carries base_rev; a 409 means another tab/editor
// moved the draft — we reload state and tell the user, never blind-overwrite.

/* eslint-env browser */

const root = document.getElementById('site-editor');
if (root) initEditor(root);

function initEditor(rootEl) {
  const pageId = rootEl.dataset.pageId;
  const api = (p) => `/admin-panel/site-editor/${pageId}${p}`;
  const iframe = document.getElementById('pse-frame');
  const statusEl = document.getElementById('pse-status');
  const publishBtn = document.getElementById('pse-publish');
  const csrf = (document.querySelector('meta[name=csrf-token]') || {}).content || '';

  let doc = { v: 1, sections: [] };
  let draftRev = 0;
  let dirty = false;
  let saving = false;
  let saveTimer = null;
  let undoStack = [];
  let redoStack = [];
  const ORIGIN = window.location.origin;

  // ---------- utils ----------
  const uid = (p) => `${p}_${Math.random().toString(36).slice(2, 10)}`;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  // Escape a value before it is interpolated into an innerHTML attribute. Link
  // and image-URL fields carry author-controlled strings; the server URL
  // validators allow embedded quotes, so without this a Site Editor could
  // break out of the attribute and run script in a Global Admin's session.
  const escAttr = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const toast = (msg, kind) => {
    if (window.Swal) {
      window.Swal.fire({ toast: true, position: 'top-end', timer: 2500, showConfirmButton: false,
        icon: kind || 'info', title: msg });
    }
  };
  const setStatus = (t) => { if (statusEl) statusEl.textContent = t; };

  function jfetch(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body: JSON.stringify(body || {}),
    }).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      return { status: r.status, data };
    });
  }

  function sendBridge(msg) {
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ __siteEditor: true, ...msg }, ORIGIN);
    }
  }

  // ---------- doc helpers ----------
  const sIdx = (sid) => doc.sections.findIndex((s) => s.id === sid);
  function findBlock(bid) {
    for (const s of doc.sections) {
      const i = (s.blocks || []).findIndex((b) => b.id === bid);
      if (i >= 0) return { section: s, index: i, block: s.blocks[i] };
    }
    return null;
  }

  function pushUndo() {
    undoStack.push(clone(doc));
    if (undoStack.length > 50) undoStack.shift();
    redoStack = [];
  }

  // ---------- save protocol ----------
  // Saves are serialized on a promise chain: a structural op that awaits save()
  // always gets a settled result reflecting the latest doc, even if a debounced
  // text save was mid-flight. The old code early-returned null while a save ran,
  // so the caller's `if (res && res.section_html) swap` never fired and the
  // iframe silently desynced from the stored doc during rapid editing.
  let saveChain = Promise.resolve();

  function scheduleSave(opts) {
    dirty = true;
    setStatus('Editing…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { save(opts); }, 700);
  }

  function save(opts = {}) {
    const run = saveChain.then(() => _doSave(opts));
    saveChain = run.catch(() => {});   // keep the chain alive past a failed save
    return run;
  }

  async function _doSave(opts = {}) {
    saving = true;
    setStatus('Saving…');
    const { status, data } = await jfetch(api('/draft'), {
      doc, base_rev: draftRev, render_section: opts.renderSection || null,
    });
    saving = false;
    if (status === 409) {
      setStatus('Out of date');
      toast('This page changed somewhere else — reloading the latest draft.', 'warning');
      await loadState();
      sendBridge({ type: 'refresh-page' });
      return null;
    }
    if (!data.success) { setStatus('Save failed'); toast(data.error || 'Save failed', 'error'); return null; }
    draftRev = data.draft_rev;
    doc = data.doc; // server-normalized (sanitized html, coerced settings)
    dirty = false;
    setStatus('Saved');
    (data.notes || []).slice(0, 3).forEach((n) => toast(n, 'info'));
    return data;
  }

  async function flushSave() {
    clearTimeout(saveTimer);
    if (dirty) save();
    await saveChain;      // let any in-flight/queued save settle before publish
    return null;
  }

  // ---------- structural ops (from bridge toolbar or panels) ----------
  async function applyOp(msg) {
    const { kind, sid, bid } = msg;
    if (kind === 'edit-section') return openSectionSettings(sid);
    if (kind === 'edit-block') return openBlockSettings(bid);
    if (kind === 'add-section') return openSectionPicker(sid);
    if (kind === 'add-block') return openBlockMenu(bid);
    if (kind === 'add-block-in-section') {
      const si = sIdx(sid);
      if (si >= 0) openBlockMenuForSection(doc.sections[si]);
      return;
    }

    if (kind === 'reorder-sections') {
      // Drag-and-drop already reordered the iframe DOM; mirror it in the doc.
      pushUndo();
      const order = msg.order || [];
      const bySid = Object.fromEntries(doc.sections.map((s) => [s.id, s]));
      const seen = new Set();
      const reordered = [];
      order.forEach((id) => { if (bySid[id] && !seen.has(id)) { reordered.push(bySid[id]); seen.add(id); } });
      doc.sections.forEach((s) => { if (!seen.has(s.id)) reordered.push(s); });
      doc.sections = reordered;
      scheduleSave({});
      return;
    }

    pushUndo();
    if (kind === 'move-section-up' || kind === 'move-section-down') {
      const i = sIdx(sid);
      const j = kind === 'move-section-up' ? i - 1 : i + 1;
      if (i < 0 || j < 0 || j >= doc.sections.length) { undoStack.pop(); return; }
      [doc.sections[i], doc.sections[j]] = [doc.sections[j], doc.sections[i]];
      sendBridge({ type: 'move-section-dom', sid, dir: kind.endsWith('up') ? 'up' : 'down' });
      scheduleSave({});
      return;
    }
    if (kind === 'duplicate-section') {
      const i = sIdx(sid);
      if (i < 0) { undoStack.pop(); return; }
      const copy = clone(doc.sections[i]);
      copy.id = uid('s');
      (copy.blocks || []).forEach((b) => { b.id = uid('b'); });
      doc.sections.splice(i + 1, 0, copy);
      const res = await save({ renderSection: copy.id });
      if (res && res.section_html) sendBridge({ type: 'insert-section', afterSid: sid, html: res.section_html });
      return;
    }
    if (kind === 'delete-section') {
      const i = sIdx(sid);
      if (i < 0) { undoStack.pop(); return; }
      doc.sections.splice(i, 1);
      sendBridge({ type: 'remove-section', sid });
      scheduleSave({});
      return;
    }
    // block ops
    const found = findBlock(bid);
    if (!found) { undoStack.pop(); return; }
    const { section, block, index } = found;
    if (kind === 'move-block-up' || kind === 'move-block-down') {
      // In a columns section, reorder WITHIN the block's own column — a flat-
      // array neighbor may belong to a different column (every neighbor does in
      // the one-block-per-column card layout), which would look like a dead
      // button.
      const isCols = section.type === 'columns';
      const myCol = block.col || 0;
      let j = -1;
      const step = kind === 'move-block-up' ? -1 : 1;
      for (let k = index + step; k >= 0 && k < section.blocks.length; k += step) {
        if (!isCols || (section.blocks[k].col || 0) === myCol) { j = k; break; }
      }
      if (j < 0) { undoStack.pop(); return; }
      [section.blocks[index], section.blocks[j]] = [section.blocks[j], section.blocks[index]];
    } else if (kind === 'duplicate-block') {
      const copy = clone(section.blocks[index]);
      copy.id = uid('b');
      section.blocks.splice(index + 1, 0, copy);
    } else if (kind === 'delete-block') {
      section.blocks.splice(index, 1);
    } else { undoStack.pop(); return; }
    const res = await save({ renderSection: section.id });
    if (res && res.section_html) sendBridge({ type: 'swap-section', sid: section.id, html: res.section_html });
  }

  // ---------- text sync (no DOM swap — the bridge keeps the live editor) ----
  function onTextChange(bid, html) {
    const found = findBlock(bid);
    if (!found) return;
    if (found.block.html === html) return;
    found.block.html = html;
    scheduleSave({});
  }

  // ---------- undo / redo ----------
  async function undo() {
    if (!undoStack.length) return;
    redoStack.push(clone(doc));
    doc = undoStack.pop();
    await save({});
    sendBridge({ type: 'refresh-page' });
  }
  async function redo() {
    if (!redoStack.length) return;
    undoStack.push(clone(doc));
    doc = redoStack.pop();
    await save({});
    sendBridge({ type: 'refresh-page' });
  }

  // ---------- publish ----------
  async function publish() {
    await flushSave();
    const changed = doc.sections.length;
    const go = window.Swal
      ? (await window.Swal.fire({
          title: 'Publish this page?',
          text: `The live site will update immediately (${changed} sections).`,
          icon: 'question', showCancelButton: true, confirmButtonText: 'Publish',
        })).isConfirmed
      : window.confirm('Publish this page? The live site updates immediately.');
    if (!go) return;
    const { status, data } = await jfetch(api('/publish'), { base_rev: draftRev });
    if (status === 409) {
      toast('Draft changed elsewhere — reloading before publish.', 'warning');
      await loadState();
      sendBridge({ type: 'refresh-page' });
      return;
    }
    if (data.success) {
      publishBtn && publishBtn.classList.remove('animate-pulse');
      // Close the editor after publishing — the natural "I'm done" flow. With
      // Swal, offer to stay; without it, exit to the live page.
      const exitUrl = root.getAttribute('data-exit-url');
      if (window.Swal) {
        const r = await window.Swal.fire({
          title: 'Published! 🎉', text: 'Your changes are live.',
          icon: 'success', showCancelButton: true,
          confirmButtonText: 'View live page', cancelButtonText: 'Keep editing',
        });
        if (r.isConfirmed && exitUrl) { window.location.href = exitUrl; return; }
      } else {
        toast('Published — the change is live.', 'success');
        if (exitUrl) window.location.href = exitUrl;
      }
    } else {
      toast(data.error === 'empty_draft' ? 'Nothing to publish yet.' : 'Publish failed.', 'error');
    }
  }

  // ---------- panels (settings / pickers) ----------
  const panel = document.getElementById('pse-panel');
  const panelBody = document.getElementById('pse-panel-body');
  const panelTitle = document.getElementById('pse-panel-title');

  function openPanel(title) {
    panelTitle.textContent = title;
    panelBody.innerHTML = '';
    panel.classList.remove('translate-x-full');
  }
  function closePanel() { panel.classList.add('translate-x-full'); }
  document.getElementById('pse-panel-close').addEventListener('click', closePanel);

  const FIELD = {
    select: (f, v) => `<select data-k="${f.key}" class="w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm">${
      f.options.map((o) => `<option value="${o}" ${o === v ? 'selected' : ''}>${o}</option>`).join('')}</select>`,
    text: (f, v) => `<input data-k="${f.key}" type="text" value="${escAttr(v)}" class="w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm">`,
    // Multi-line text (card body copy). Holds sanitized HTML; plain typed text
    // is fine too — the server sanitizer normalizes either way.
    textarea: (f, v) => `<textarea data-k="${f.key}" rows="4" class="w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm">${escAttr(v)}</textarea>`,
    number: (f, v) => `<input data-k="${f.key}" type="number" min="${f.min || 1}" max="${f.max || 12}" value="${escAttr(v || f.def || '')}" class="w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm">`,
    color: (f, v) => `<input data-k="${f.key}" type="color" value="${escAttr(v || '#40b050')}" class="h-10 w-full rounded-lg border-gray-300">`,
    toggle: (f, v) => `<label class="inline-flex items-center gap-2 text-sm"><input data-k="${f.key}" type="checkbox" ${v ? 'checked' : ''} class="rounded"> ${f.label}</label>`,
  };

  const SECTION_FIELDS = {
    hero: [
      { key: 'size', label: 'Height', type: 'select', options: ['sm', 'md', 'lg', 'xl'] },
      { key: 'align', label: 'Text alignment', type: 'select', options: ['left', 'center', 'right'] },
      { key: 'overlay', label: 'Image overlay', type: 'select', options: ['none', 'light', 'medium', 'heavy'] },
      { key: 'image', label: 'Background image', type: 'image' },
    ],
    content: [
      { key: 'width', label: 'Width', type: 'select', options: ['narrow', 'normal', 'wide'] },
      { key: 'align', label: 'Alignment', type: 'select', options: ['left', 'center', 'right'] },
      { key: 'padding', label: 'Vertical padding', type: 'select', options: ['sm', 'md', 'lg', 'xl'] },
      { key: 'bg_color', label: 'Background fill', type: 'coloropt' },
      { key: 'text_color', label: 'Text color', type: 'coloropt', def: '#141a15' },
    ],
    columns: [
      { key: 'layout', label: 'Layout', type: 'select', options: ['50-50', '33-67', '67-33', '3col'] },
      { key: 'padding', label: 'Vertical padding', type: 'select', options: ['sm', 'md', 'lg', 'xl'] },
    ],
    band: [
      { key: 'align', label: 'Alignment', type: 'select', options: ['left', 'center', 'right'] },
      { key: 'bg_color', label: 'Background fill', type: 'coloropt' },
      { key: 'text_color', label: 'Text color', type: 'coloropt' },
    ],
  };
  const THEME_FIELD = { key: '__theme', label: 'Color theme', type: 'select',
    options: ['inherit', 'light', 'dark', 'brand'] };

  // Mirrors SOCIAL_KINDS in app/services/section_schema.py — keep in sync.
  const SOCIAL_KINDS = ['discord', 'instagram', 'facebook', 'bluesky', 'twitter',
                        'youtube', 'tiktok', 'email'];

  const BLOCK_FIELDS = {
    image: [
      { key: 'image', label: 'Image', type: 'image' },
      { key: 'size', label: 'Size', type: 'select', options: ['s', 'm', 'l', 'full'] },
      { key: 'align', label: 'Alignment', type: 'select', options: ['left', 'center', 'right'] },
      { key: 'aspect', label: 'Crop', type: 'select', options: ['natural', '16:9', '4:3', '1:1'] },
      { key: 'caption', label: 'Caption', type: 'text' },
    ],
    button: [
      { key: 'label', label: 'Label', type: 'text' },
      { key: 'link', label: 'Link', type: 'link' },
      { key: 'style', label: 'Style', type: 'select', options: ['primary', 'secondary', 'outline'] },
      { key: 'align', label: 'Alignment', type: 'select', options: ['left', 'center', 'right'] },
    ],
    cta_live: [
      { key: 'kind', label: 'Action', type: 'select',
        options: ['waitlist_or_register', 'division_classic', 'division_premier', 'how_to_join', 'contact'] },
      { key: 'style', label: 'Style', type: 'select', options: ['primary', 'secondary', 'outline'] },
      { key: 'align', label: 'Alignment', type: 'select', options: ['left', 'center', 'right'] },
    ],
    card: [
      { key: 'title', label: 'Title', type: 'text' },
      // Card bodies have no inline-edit surface (data-editable covers only
      // heading/richtext/quote), so the body copy MUST be editable here or
      // seeded placeholder text is a dead end.
      { key: 'html', label: 'Text', type: 'textarea' },
      { key: 'icon', label: 'Icon (tabler name, optional)', type: 'text' },
      { key: 'image', label: 'Image (optional)', type: 'image' },
      { key: 'link', label: 'Link (optional)', type: 'link' },
      { key: 'link_label', label: 'Link label', type: 'text' },
    ],
    video: [{ key: 'url', label: 'YouTube / Vimeo URL', type: 'text' },
            { key: 'caption', label: 'Caption', type: 'text' }],
    map: [{ key: 'url', label: 'Google Maps embed URL', type: 'text' },
          { key: 'caption', label: 'Caption', type: 'text' }],
    news_latest: [{ key: 'count', label: 'How many posts', type: 'number', min: 1, max: 12, def: 3 },
                  { key: 'category', label: 'Only this category (optional)', type: 'text' }],
    faq_list: [{ key: 'category', label: 'Only this category (optional)', type: 'text' }],
    calendar_teaser: [{ key: 'count', label: 'How many events', type: 'number', min: 1, max: 10, def: 4 }],
    form: [{ key: 'form', label: 'Form name', type: 'text' }],
    quote: [{ key: 'attribution', label: 'Attribution', type: 'text' }],
    spacer: [{ key: 'size', label: 'Size', type: 'select', options: ['sm', 'md', 'lg', 'xl'] }],
    heading: [{ key: 'level', label: 'Level', type: 'select', options: [1, 2, 3, 4] },
              { key: 'align', label: 'Alignment', type: 'select', options: ['left', 'center', 'right'] }],
    gallery: [
      { key: 'items', label: 'Photos', type: 'items', addLabel: 'Add photo',
        item: [{ key: 'image', label: 'Photo', type: 'image' },
               { key: 'caption', label: 'Caption (optional)', type: 'text' },
               { key: 'link', label: 'Link (optional)', type: 'link' }] },
      { key: 'layout', label: 'Layout', type: 'select', options: ['grid-2', 'grid-3', 'grid-4', 'carousel'] },
      { key: 'crop', label: 'Crop to squares', type: 'toggle' },
    ],
    stats: [
      { key: 'items', label: 'Stats', type: 'items', addLabel: 'Add stat',
        item: [{ key: 'value', label: 'Value (e.g. 100+)', type: 'text' },
               { key: 'label', label: 'Label (e.g. Players)', type: 'text' }] },
    ],
    social_links: [
      { key: 'items', label: 'Links', type: 'items', addLabel: 'Add link',
        item: [{ key: 'kind', label: 'Platform', type: 'select', options: SOCIAL_KINDS },
               { key: 'url', label: 'URL (https://…)', type: 'text' }] },
    ],
  };

  function renderFields(fields, values, container) {
    // Each field wires its own controls within its own `wrap` element (not via a
    // post-loop querySelectorAll on the container) so nested repeater rows — which
    // reuse the same data-* keys — don't cross-wire or collide.
    fields.forEach((f) => {
      const wrap = document.createElement('div');
      wrap.className = 'mb-4';
      if (f.type === 'toggle') {
        wrap.innerHTML = FIELD.toggle(f, values[f.key]);
      } else if (f.type === 'coloropt') {
        // Optional color: a checkbox expresses "no custom color" (fall back to
        // the theme); the picker holds the value. Plain type:'color' can't be
        // unset, which would force a color onto every section.
        const cval = values[f.key];
        const on = !!cval;
        wrap.innerHTML = `<label class="block text-sm font-medium mb-1.5">${f.label}</label>
          <div class="flex items-center gap-2">
            <input data-coloropt-on="${f.key}" type="checkbox" ${on ? 'checked' : ''} class="rounded">
            <input data-coloropt-val="${f.key}" type="color" value="${escAttr(cval || f.def || '#40b050')}" class="h-9 w-14 rounded border-gray-300 ${on ? '' : 'opacity-40'}">
            <span class="text-xs text-gray-400">use a custom color</span>
          </div>`;
        const cb = wrap.querySelector('[data-coloropt-on]');
        const cv = wrap.querySelector('[data-coloropt-val]');
        cb.addEventListener('change', () => cv.classList.toggle('opacity-40', !cb.checked));
        cv.addEventListener('input', () => { cb.checked = true; cv.classList.remove('opacity-40'); });
      } else if (f.type === 'image') {
        const ref = values[f.key] || {};
        const focal = (Array.isArray(ref.focal) && ref.focal.length === 2) ? ref.focal : [0.5, 0.5];
        wrap.innerHTML = `<label class="block text-sm font-medium mb-1.5">${f.label}</label>
          <div data-focal-box class="relative mb-2 hidden cursor-crosshair overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-900" style="aspect-ratio:16/9;">
            <img data-preview src="" class="h-full w-full object-cover" style="object-position:${Math.round(focal[0]*100)}% ${Math.round(focal[1]*100)}%;">
            <span data-focal-dot class="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-ecs-green shadow-md" style="left:${focal[0]*100}%;top:${focal[1]*100}%;"></span>
          </div>
          <p data-focal-hint class="mb-1.5 hidden text-xs text-gray-400">Click the image to set the focal point — what stays in view when it's cropped.</p>
          <button type="button" data-pick-image="${f.key}" class="px-3 py-2 text-sm font-medium rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200">Choose image…</button>`;
        const btn = wrap.querySelector('[data-pick-image]');
        const box = wrap.querySelector('[data-focal-box]');
        const preview = wrap.querySelector('[data-preview]');
        const dot = wrap.querySelector('[data-focal-dot]');
        const hint = wrap.querySelector('[data-focal-hint]');
        // Preserve an already-chosen asset + its focal so re-applying settings
        // WITHOUT re-picking doesn't silently drop the image (the old code did).
        btn.dataset.focalX = focal[0];
        btn.dataset.focalY = focal[1];
        const showImg = (url) => {
          if (!url) return;
          preview.src = url;
          box.classList.remove('hidden');
          hint.classList.remove('hidden');
        };
        const setFocal = (fx, fy) => {
          fx = Math.min(1, Math.max(0, fx)); fy = Math.min(1, Math.max(0, fy));
          btn.dataset.focalX = fx; btn.dataset.focalY = fy;
          preview.style.objectPosition = `${Math.round(fx * 100)}% ${Math.round(fy * 100)}%`;
          dot.style.left = `${fx * 100}%`; dot.style.top = `${fy * 100}%`;
        };
        box.addEventListener('click', (ev) => {
          const r = box.getBoundingClientRect();
          setFocal((ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height);
        });
        if (typeof ref.asset_id === 'number') {
          btn.dataset.assetId = ref.asset_id;
          if (ref.url) showImg(ref.url); else mediaUrl(ref.asset_id).then(showImg);
        }
        btn.addEventListener('click', async () => {
          const picked = await pickImage();
          if (picked) { btn.dataset.assetId = picked.id; showImg(picked.url); }
        });
      } else if (f.type === 'link') {
        const link = values[f.key] || {};
        wrap.innerHTML = `<label class="block text-sm font-medium mb-1.5">${f.label}</label>
          <div class="flex gap-2">
            <select data-linkkind="${f.key}" class="rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm">
              <option value="builtin" ${link.kind === 'builtin' ? 'selected' : ''}>Page</option>
              <option value="url" ${link.kind === 'url' ? 'selected' : ''}>URL</option>
            </select>
            <select data-linkbuiltin="${f.key}" class="flex-1 rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm ${link.kind === 'url' ? 'hidden' : ''}">
              ${['home', 'about', 'faqs', 'news', 'calendar', 'register', 'contact', 'guide', 'guests']
                .map((o) => `<option ${link.value === o ? 'selected' : ''}>${o}</option>`).join('')}
            </select>
            <input data-linkurl="${f.key}" type="url" placeholder="https://…" value="${escAttr(link.url || '')}"
                   class="flex-1 rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm ${link.kind === 'url' ? '' : 'hidden'}">
          </div>`;
        const sel = wrap.querySelector('[data-linkkind]');
        sel.addEventListener('change', () => {
          wrap.querySelector('[data-linkbuiltin]').classList.toggle('hidden', sel.value === 'url');
          wrap.querySelector('[data-linkurl]').classList.toggle('hidden', sel.value !== 'url');
        });
      } else if (f.type === 'items') {
        // Repeater for gallery photos / stats / social links: a list of rows,
        // each rendered by a nested renderFields(f.item, …), plus add/remove/reorder.
        wrap.innerHTML = `<label class="block text-sm font-medium mb-1.5">${f.label}</label>
          <div data-items="${f.key}"></div>
          <button type="button" data-items-add class="mt-1 w-full rounded-lg border border-dashed border-gray-300 dark:border-gray-600 px-3 py-2 text-sm text-gray-600 dark:text-gray-300 hover:border-ecs-green">+ ${f.addLabel || 'Add item'}</button>`;
        const listEl = wrap.querySelector(`[data-items="${f.key}"]`);
        const addRow = (itemValues) => {
          const row = document.createElement('div');
          row.dataset.itemRow = '';
          row.className = 'relative mb-2 rounded-lg border border-gray-200 dark:border-gray-700 p-3 pr-8';
          const body = document.createElement('div');
          body.dataset.itemBody = '';
          renderFields(f.item, itemValues || {}, body);
          row.appendChild(body);
          const tools = document.createElement('div');
          tools.className = 'absolute top-1 right-0.5 flex flex-col text-xs';
          tools.innerHTML = `<button type="button" data-item-up title="Move up" class="text-gray-400 hover:text-ecs-green leading-none p-0.5"><i class="ti ti-chevron-up"></i></button>
            <button type="button" data-item-down title="Move down" class="text-gray-400 hover:text-ecs-green leading-none p-0.5"><i class="ti ti-chevron-down"></i></button>
            <button type="button" data-item-del title="Remove" class="text-gray-400 hover:text-red-500 leading-none p-0.5"><i class="ti ti-x"></i></button>`;
          tools.querySelector('[data-item-up]').addEventListener('click', () => { const p = row.previousElementSibling; if (p) listEl.insertBefore(row, p); });
          tools.querySelector('[data-item-down]').addEventListener('click', () => { const n = row.nextElementSibling; if (n) listEl.insertBefore(n, row); });
          tools.querySelector('[data-item-del]').addEventListener('click', () => row.remove());
          row.appendChild(tools);
          listEl.appendChild(row);
        };
        (values[f.key] || []).forEach(addRow);
        wrap.querySelector('[data-items-add]').addEventListener('click', () => addRow({}));
      } else {
        wrap.innerHTML = `<label class="block text-sm font-medium mb-1.5">${f.label}</label>${FIELD[f.type](f, values[f.key])}`;
      }
      container.appendChild(wrap);
    });
  }

  function collectFields(fields, container, into) {
    fields.forEach((f) => {
      if (f.type === 'coloropt') {
        const on = container.querySelector(`[data-coloropt-on="${f.key}"]`);
        const val = container.querySelector(`[data-coloropt-val="${f.key}"]`);
        into[f.key] = (on && on.checked && val) ? val.value : null;  // null clears it
        return;
      }
      if (f.type === 'items') {
        const listEl = container.querySelector(`[data-items="${f.key}"]`);
        const arr = [];
        if (listEl) {
          listEl.querySelectorAll(':scope > [data-item-row]').forEach((row) => {
            const body = row.querySelector(':scope > [data-item-body]');
            const item = {};
            collectFields(f.item, body, item);
            arr.push(item);
          });
        }
        // Send every row; the server schema drops items missing required content
        // (gallery needs an image, stats needs value+label, social needs kind+url).
        into[f.key] = arr;
        return;
      }
      if (f.type === 'image') {
        const btn = container.querySelector(`[data-pick-image="${f.key}"]`);
        if (btn && btn.dataset.assetId) {
          const out = { asset_id: parseInt(btn.dataset.assetId, 10) };
          const fx = parseFloat(btn.dataset.focalX), fy = parseFloat(btn.dataset.focalY);
          if (!isNaN(fx) && !isNaN(fy)) out.focal = [fx, fy];
          into[f.key] = out;
        }
        return;
      }
      if (f.type === 'link') {
        const kind = container.querySelector(`[data-linkkind="${f.key}"]`).value;
        into[f.key] = kind === 'url'
          ? { kind: 'url', url: container.querySelector(`[data-linkurl="${f.key}"]`).value }
          : { kind: 'builtin', value: container.querySelector(`[data-linkbuiltin="${f.key}"]`).value };
        return;
      }
      const el = container.querySelector(`[data-k="${f.key}"]`);
      if (!el) return;
      if (f.type === 'toggle') into[f.key] = el.checked;
      else if (f.type === 'number' || (f.key === 'level')) into[f.key] = parseInt(el.value, 10);
      else into[f.key] = el.value;
    });
  }

  function settingsForm(fields, values, onApply) {
    const formEl = document.createElement('div');
    renderFields(fields, values, formEl);
    const apply = document.createElement('button');
    apply.type = 'button';
    apply.className = 'w-full mt-2 rounded-lg bg-ecs-green px-4 py-2.5 text-sm font-semibold text-white hover:bg-ecs-green-dark';
    apply.textContent = 'Apply';
    apply.addEventListener('click', () => onApply(formEl));
    formEl.appendChild(apply);
    panelBody.appendChild(formEl);
  }

  function openSectionSettings(sid) {
    const i = sIdx(sid);
    if (i < 0) return;
    const section = doc.sections[i];
    openPanel('Section settings');
    const fields = [THEME_FIELD, ...(SECTION_FIELDS[section.type] || [])];
    const values = { __theme: section.theme, ...(section.settings || {}) };
    settingsForm(fields, values, async (formEl) => {
      pushUndo();
      const out = {};
      collectFields(fields, formEl, out);
      section.theme = out.__theme || section.theme;
      delete out.__theme;
      section.settings = { ...(section.settings || {}), ...out };
      closePanel();
      const res = await save({ renderSection: sid });
      if (res && res.section_html) sendBridge({ type: 'swap-section', sid, html: res.section_html });
    });
  }

  function openBlockSettings(bid) {
    const found = findBlock(bid);
    if (!found) return;
    const { section, block } = found;
    const fields = BLOCK_FIELDS[block.type];
    if (!fields) { toast('Click the text to edit it in place.', 'info'); return; }
    openPanel(`${block.type.replace('_', ' ')} settings`);
    settingsForm(fields, block, async (formEl) => {
      pushUndo();
      collectFields(fields, formEl, block);
      closePanel();
      const res = await save({ renderSection: section.id });
      if (res && res.section_html) sendBridge({ type: 'swap-section', sid: section.id, html: res.section_html });
    });
  }

  // ---------- add section / block ----------
  const PRESETS = [
    { label: 'Text section', make: () => ({ id: uid('s'), type: 'content', theme: 'inherit',
      settings: { width: 'narrow' }, blocks: [
        { id: uid('b'), type: 'heading', level: 2, html: 'New section' },
        { id: uid('b'), type: 'richtext', html: '<p>Write something…</p>' }] }) },
    { label: 'Hero banner', make: () => ({ id: uid('s'), type: 'hero', theme: 'dark',
      settings: { size: 'md', align: 'center', overlay: 'medium' }, blocks: [
        { id: uid('b'), type: 'heading', level: 1, html: 'Headline' },
        { id: uid('b'), type: 'richtext', html: '<p>Supporting copy.</p>' },
        { id: uid('b'), type: 'cta_live', kind: 'waitlist_or_register', style: 'primary' }] }) },
    { label: '3 cards', make: () => ({ id: uid('s'), type: 'columns', theme: 'inherit',
      settings: { layout: '3col' }, blocks: [0, 1, 2].map((c) => (
        { id: uid('b'), type: 'card', col: c, icon: 'star', title: `Card ${c + 1}`,
          html: '<p>Card copy.</p>' })) }) },
    { label: 'Image + text', make: () => ({ id: uid('s'), type: 'columns', theme: 'inherit',
      settings: { layout: '50-50' }, blocks: [
        { id: uid('b'), type: 'image', col: 0, image: {}, size: 'full', aspect: '4:3' },
        { id: uid('b'), type: 'heading', col: 1, level: 2, html: 'About this' },
        { id: uid('b'), type: 'richtext', col: 1, html: '<p>Say more…</p>' }] }) },
    { label: 'Photo gallery', make: () => ({ id: uid('s'), type: 'content', theme: 'inherit',
      settings: { width: 'wide' }, blocks: [
        { id: uid('b'), type: 'heading', level: 2, html: 'Gallery' },
        { id: uid('b'), type: 'gallery', layout: 'grid-3', crop: true, items: [] }] }) },
    { label: 'Call-to-action band', make: () => ({ id: uid('s'), type: 'band', theme: 'brand',
      settings: { align: 'center' }, blocks: [
        { id: uid('b'), type: 'heading', level: 2, html: 'Ready to play?' },
        { id: uid('b'), type: 'cta_live', kind: 'waitlist_or_register', style: 'primary', align: 'center' }] }) },
    { label: 'Latest news', make: () => ({ id: uid('s'), type: 'content', theme: 'light',
      settings: { width: 'wide' }, blocks: [
        { id: uid('b'), type: 'heading', level: 2, html: 'Latest news' },
        { id: uid('b'), type: 'news_latest', count: 3 }] }) },
    { label: 'Video', make: () => ({ id: uid('s'), type: 'content', theme: 'inherit',
      settings: { width: 'normal' }, blocks: [
        { id: uid('b'), type: 'video', url: '' }] }) },
    { label: 'FAQ list', make: () => ({ id: uid('s'), type: 'content', theme: 'inherit',
      settings: { width: 'narrow' }, blocks: [{ id: uid('b'), type: 'faq_list' }] }) },
    { label: 'Contact form', make: () => ({ id: uid('s'), type: 'content', theme: 'inherit',
      settings: { width: 'narrow' }, blocks: [{ id: uid('b'), type: 'form', form: 'contact' }] }) },
  ];

  function openSectionPicker(afterSid) {
    openPanel('Add a section');
    PRESETS.forEach((p) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'w-full mb-2 rounded-xl border border-gray-200 dark:border-gray-700 px-4 py-3 text-left text-sm font-medium hover:border-ecs-green hover:bg-ecs-green/5';
      btn.textContent = p.label;
      btn.addEventListener('click', async () => {
        pushUndo();
        const fresh = p.make();
        const i = afterSid ? sIdx(afterSid) + 1 : doc.sections.length;
        doc.sections.splice(i, 0, fresh);
        closePanel();
        const res = await save({ renderSection: fresh.id });
        if (res && res.section_html) {
          sendBridge({ type: 'insert-section', afterSid: afterSid || null, html: res.section_html });
        } else {
          sendBridge({ type: 'refresh-page' });
        }
      });
      panelBody.appendChild(btn);
    });
  }

  const BLOCK_DEFAULTS = {
    heading: { level: 2, html: 'Heading' },
    richtext: { html: '<p>Write something…</p>' },
    image: { image: {}, size: 'l', align: 'center', aspect: 'natural' },
    button: { label: 'Learn more', link: { kind: 'builtin', value: 'about' }, style: 'primary' },
    cta_live: { kind: 'waitlist_or_register', style: 'primary' },
    card: { title: 'Card', html: '<p>Card copy.</p>', icon: 'star' },
    gallery: { layout: 'grid-3', crop: true, items: [] },
    video: { url: '' }, map: { url: '' },
    news_latest: { count: 3 }, faq_list: {}, registration_status: {},
    calendar_teaser: { count: 4 }, form: { form: 'contact' },
    quote: { html: '<p>Quote…</p>' }, divider: {}, spacer: { size: 'md' },
    stats: { items: [{ value: '100+', label: 'Players' }] },
    social_links: { items: [{ kind: 'discord', url: 'https://discord.gg/weareecs' }] },
  };

  // Grouped, labelled catalog for the add-block menu so widgets are discoverable
  // (the raw type names — news_latest, cta_live — read like jargon otherwise).
  const BLOCK_CATALOG = [
    { group: 'Basic', items: [
      { t: 'heading', label: 'Heading', icon: 'ti-heading' },
      { t: 'richtext', label: 'Text', icon: 'ti-align-left' },
      { t: 'image', label: 'Image', icon: 'ti-photo' },
      { t: 'button', label: 'Button', icon: 'ti-square-rounded-plus' },
      { t: 'cta_live', label: 'Live button (Register/Waitlist)', icon: 'ti-hand-click' },
      { t: 'quote', label: 'Quote', icon: 'ti-quote' },
    ] },
    { group: 'Layout', items: [
      { t: 'card', label: 'Card', icon: 'ti-cards' },
      { t: 'divider', label: 'Divider', icon: 'ti-separator-horizontal' },
      { t: 'spacer', label: 'Spacer', icon: 'ti-arrows-vertical' },
    ] },
    { group: 'Widgets', items: [
      { t: 'news_latest', label: 'Latest news', icon: 'ti-news' },
      { t: 'calendar_teaser', label: 'Upcoming events', icon: 'ti-calendar' },
      { t: 'faq_list', label: 'FAQ list', icon: 'ti-help' },
      { t: 'registration_status', label: 'Registration status', icon: 'ti-user-check' },
      { t: 'form', label: 'Form', icon: 'ti-forms' },
      { t: 'stats', label: 'Stats', icon: 'ti-chart-bar' },
      { t: 'social_links', label: 'Social links', icon: 'ti-brand-instagram' },
      { t: 'video', label: 'Video (YouTube/Vimeo)', icon: 'ti-brand-youtube' },
      { t: 'map', label: 'Map', icon: 'ti-map-pin' },
      { t: 'gallery', label: 'Photo gallery', icon: 'ti-photo-plus' },
    ] },
  ];

  function openBlockMenu(afterBid) {
    const found = findBlock(afterBid);
    if (found) {
      openBlockMenuAt(found.section, found.index + 1,
        found.block.col !== undefined ? found.block.col : undefined);
    }
  }
  // Add a block/widget at the END of a section — the "＋ Add block" bar path.
  function openBlockMenuForSection(section) {
    openBlockMenuAt(section, (section.blocks || []).length,
      section.type === 'columns' ? 0 : undefined);
  }
  function openBlockMenuAt(section, index, col) {
    openPanel('Add a block or widget');
    const addBlock = async (t) => {
      pushUndo();
      const fresh = { id: uid('b'), type: t, ...clone(BLOCK_DEFAULTS[t]) };
      if (col !== undefined) fresh.col = col;
      section.blocks.splice(index, 0, fresh);
      // image/gallery/video/map validate to nothing until configured, so a blind
      // save would drop them — open their settings so the first save has content.
      const needsContentFirst = ['image', 'video', 'map', 'gallery'].includes(t);
      closePanel();
      if (needsContentFirst) {
        openBlockSettings(fresh.id);
      } else {
        const res = await save({ renderSection: section.id });
        if (res && res.section_html) sendBridge({ type: 'swap-section', sid: section.id, html: res.section_html });
      }
    };
    BLOCK_CATALOG.forEach((grp) => {
      const h = document.createElement('div');
      h.className = 'mt-3 mb-1 px-1 text-xs font-semibold uppercase tracking-wide text-gray-400';
      h.textContent = grp.group;
      panelBody.appendChild(h);
      const wrap = document.createElement('div');
      wrap.className = 'grid grid-cols-2 gap-1.5';
      grp.items.forEach((it) => {
        if (!BLOCK_DEFAULTS[it.t]) return;  // only creatable blocks
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-700 px-2.5 py-2 text-left text-sm hover:border-ecs-green hover:bg-gray-50 dark:hover:bg-gray-700/50';
        btn.innerHTML = `<i class="ti ${it.icon} text-gray-400"></i><span>${escAttr(it.label)}</span>`;
        btn.addEventListener('click', () => addBlock(it.t));
        wrap.appendChild(btn);
      });
      panelBody.appendChild(wrap);
    });
  }

  // ---------- media picker ----------
  // Stored image refs carry only asset_id; resolve the URL (once, cached) from
  // the media list so an already-chosen image shows its preview + focal editor.
  let mediaUrlCache = null;
  async function mediaUrl(assetId) {
    if (!mediaUrlCache) {
      mediaUrlCache = {};
      try {
        const r = await fetch('/admin-panel/public-site/media/list');
        const { assets } = await r.json();
        (assets || []).forEach((a) => { mediaUrlCache[a.id] = a.url; });
      } catch (e) { /* leave empty — preview just won't show */ }
    }
    return mediaUrlCache[assetId] || null;
  }

  function pickImage() {
    return new Promise((resolve) => {
      openPanel('Choose an image');
      const up = document.createElement('label');
      up.className = 'block mb-3 cursor-pointer rounded-xl border-2 border-dashed border-gray-300 dark:border-gray-600 p-4 text-center text-sm text-gray-500 hover:border-ecs-green';
      up.innerHTML = 'Upload a new image<input type="file" accept="image/*" class="hidden">';
      up.querySelector('input').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append('file', file);
        let data = {};
        try {
          const r = await fetch('/admin-panel/public-site/upload-image',
            { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd });
          data = await r.json();
        } catch (err) {
          toast('Upload failed — the file may be too large.', 'error');
          return;
        }
        if (data.url) { await renderGrid(); toast('Uploaded.', 'success'); }
        else toast(data.error || 'Upload failed', 'error');
      });
      panelBody.appendChild(up);
      const grid = document.createElement('div');
      grid.className = 'grid grid-cols-3 gap-2';
      panelBody.appendChild(grid);
      async function renderGrid() {
        const r = await fetch('/admin-panel/public-site/media/list');
        const { assets } = await r.json();
        grid.innerHTML = '';
        (assets || []).forEach((a) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'aspect-square overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700 hover:ring-2 hover:ring-ecs-green';
          btn.innerHTML = `<img src="${escAttr(a.url)}" alt="" class="h-full w-full object-cover">`;
          btn.addEventListener('click', () => {
            if (!a.alt) {
              const alt = window.prompt('Describe this image for screen readers (alt text):', '');
              if (alt) {
                const fd = new FormData();
                fd.append('alt_text', alt);
                fetch(`/admin-panel/public-site/media/${a.id}/save`,
                  { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd });
              }
            }
            closePanel();
            resolve(a);
          });
          grid.appendChild(btn);
        });
      }
      renderGrid();
    });
  }

  // ---------- messaging / boot ----------
  window.addEventListener('message', (e) => {
    if (e.origin !== ORIGIN || !e.data || !e.data.__siteEditor) return;
    const msg = e.data;
    if (msg.type === 'op') applyOp(msg);
    else if (msg.type === 'text-change') onTextChange(msg.bid, msg.html);
  });

  async function loadState() {
    const r = await fetch(api('/state'));
    const data = await r.json();
    if (data.success) {
      doc = data.doc;
      draftRev = data.draft_rev;
      setStatus(data.page.has_unpublished_changes ? 'Unpublished changes' : 'Up to date');
      if (data.page.has_unpublished_changes && publishBtn) publishBtn.classList.add('animate-pulse');
    }
  }

  // edit lock: acquire + heartbeat; takeover flow on conflict
  async function lock(force) {
    const { data } = await jfetch(api('/lock'), { force: !!force });
    if (!data.success && data.holder) {
      const take = window.Swal
        ? (await window.Swal.fire({
            title: `${data.holder} is editing this page`,
            text: 'Take over? Their unsaved changes may be lost.',
            icon: 'warning', showCancelButton: true, confirmButtonText: 'Take over',
          })).isConfirmed
        : window.confirm(`${data.holder} is editing this page. Take over?`);
      if (take) await lock(true);
      else window.location.href = document.referrer || '/admin-panel/public-site/pages';
    }
  }
  setInterval(() => lock(false), 30000);

  window.addEventListener('beforeunload', (e) => {
    if (dirty || saving) { e.preventDefault(); e.returnValue = ''; }
    // sendBeacon can't set an X-CSRFToken header, so pass the token as a form
    // field — Flask-WTF reads csrf_token from request.form. A JSON-body beacon
    // is rejected (400 CSRF) and the edit lock then lingers on its 60s TTL
    // instead of releasing the moment the tab closes.
    navigator.sendBeacon && navigator.sendBeacon(api('/unlock'),
      new URLSearchParams({ csrf_token: csrf }));
  });

  // top-bar wiring
  document.getElementById('pse-undo').addEventListener('click', undo);
  document.getElementById('pse-redo').addEventListener('click', redo);
  publishBtn.addEventListener('click', publish);
  document.getElementById('pse-add-section').addEventListener('click', () => openSectionPicker(
    doc.sections.length ? doc.sections[doc.sections.length - 1].id : null));
  document.querySelectorAll('[data-device]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const w = btn.getAttribute('data-device');
      iframe.style.width = w === 'mobile' ? '390px' : (w === 'tablet' ? '768px' : '100%');
      document.querySelectorAll('[data-device]').forEach((b) => b.classList.remove('bg-gray-200', 'dark:bg-gray-600'));
      btn.classList.add('bg-gray-200', 'dark:bg-gray-600');
    });
  });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
    if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); redo(); }
  });

  lock(false);
  loadState();
}
