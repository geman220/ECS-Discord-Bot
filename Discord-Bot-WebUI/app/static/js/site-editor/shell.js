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
  function scheduleSave(opts) {
    dirty = true;
    setStatus('Editing…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save(opts), 700);
  }

  async function save(opts = {}) {
    if (saving) { scheduleSave(opts); return null; }
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
    if (dirty || saving) return save();
    return null;
  }

  // ---------- structural ops (from bridge toolbar or panels) ----------
  async function applyOp(msg) {
    const { kind, sid, bid } = msg;
    if (kind === 'edit-section') return openSectionSettings(sid);
    if (kind === 'edit-block') return openBlockSettings(bid);
    if (kind === 'add-section') return openSectionPicker(sid);
    if (kind === 'add-block') return openBlockMenu(bid);

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
      toast('Published — the change is live.', 'success');
      publishBtn && publishBtn.classList.remove('animate-pulse');
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
    ],
    columns: [
      { key: 'layout', label: 'Layout', type: 'select', options: ['50-50', '33-67', '67-33', '3col'] },
      { key: 'padding', label: 'Vertical padding', type: 'select', options: ['sm', 'md', 'lg', 'xl'] },
    ],
    band: [
      { key: 'align', label: 'Alignment', type: 'select', options: ['left', 'center', 'right'] },
    ],
  };
  const THEME_FIELD = { key: '__theme', label: 'Color theme', type: 'select',
    options: ['inherit', 'light', 'dark', 'brand'] };

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
    gallery: [{ key: 'layout', label: 'Layout', type: 'select', options: ['grid-2', 'grid-3', 'grid-4', 'carousel'] },
              { key: 'crop', label: 'Crop to squares', type: 'toggle' }],
  };

  function renderFields(fields, values, container) {
    fields.forEach((f) => {
      const wrap = document.createElement('div');
      wrap.className = 'mb-4';
      if (f.type === 'toggle') {
        wrap.innerHTML = FIELD.toggle(f, values[f.key]);
      } else if (f.type === 'image') {
        const ref = values[f.key];
        wrap.innerHTML = `<label class="block text-sm font-medium mb-1.5">${f.label}</label>
          <div class="flex items-center gap-3">
            <img data-preview="${f.key}" src="${escAttr(ref && ref.url ? ref.url : '')}" class="h-14 w-20 object-cover rounded-lg border border-gray-200 dark:border-gray-700 ${ref ? '' : 'hidden'}">
            <button type="button" data-pick-image="${f.key}" class="px-3 py-2 text-sm font-medium rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200">Choose image…</button>
          </div>`;
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
      } else {
        wrap.innerHTML = `<label class="block text-sm font-medium mb-1.5">${f.label}</label>${FIELD[f.type](f, values[f.key])}`;
      }
      container.appendChild(wrap);
    });
    container.querySelectorAll('[data-linkkind]').forEach((sel) => {
      sel.addEventListener('change', () => {
        const k = sel.getAttribute('data-linkkind');
        container.querySelector(`[data-linkbuiltin="${k}"]`).classList.toggle('hidden', sel.value === 'url');
        container.querySelector(`[data-linkurl="${k}"]`).classList.toggle('hidden', sel.value !== 'url');
      });
    });
    container.querySelectorAll('[data-pick-image]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const picked = await pickImage();
        if (picked) {
          btn.dataset.assetId = picked.id;
          const img = container.querySelector(`[data-preview="${btn.getAttribute('data-pick-image')}"]`);
          img.src = picked.url;
          img.classList.remove('hidden');
        }
      });
    });
  }

  function collectFields(fields, container, into) {
    fields.forEach((f) => {
      if (f.type === 'image') {
        const btn = container.querySelector(`[data-pick-image="${f.key}"]`);
        if (btn && btn.dataset.assetId) into[f.key] = { asset_id: parseInt(btn.dataset.assetId, 10) };
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

  function openBlockMenu(afterBid) {
    const found = findBlock(afterBid);
    if (!found) return;
    openPanel('Add a block');
    Object.keys(BLOCK_DEFAULTS).forEach((t) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'inline-flex m-1 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2 text-sm hover:border-ecs-green';
      btn.textContent = t.replace('_', ' ');
      btn.addEventListener('click', async () => {
        pushUndo();
        const fresh = { id: uid('b'), type: t, ...clone(BLOCK_DEFAULTS[t]) };
        if (found.block.col !== undefined) fresh.col = found.block.col;
        found.section.blocks.splice(found.index + 1, 0, fresh);
        // image/gallery/video/map validate to nothing until configured, so a
        // blind save would drop them. Add to the doc, open their settings, and
        // let the settings-apply do the first save once there's real content.
        const needsContentFirst = ['image', 'video', 'map', 'gallery'].includes(t);
        closePanel();
        if (needsContentFirst) {
          openBlockSettings(fresh.id);
        } else {
          const res = await save({ renderSection: found.section.id });
          if (res && res.section_html) sendBridge({ type: 'swap-section', sid: found.section.id, html: res.section_html });
        }
      });
      panelBody.appendChild(btn);
    });
  }

  // ---------- media picker ----------
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
    navigator.sendBeacon && navigator.sendBeacon(api('/unlock'),
      new Blob([JSON.stringify({})], { type: 'application/json' }));
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
