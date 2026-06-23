/* survey-builder.js — drives the admin survey/poll builder.
 *
 * Loads bootstrap data (when editing), lets admins add/remove/reorder/configure
 * questions, then serializes everything to the JSON API (POST new / PUT edit).
 */
(function () {
  'use strict';

  var root = document.getElementById('survey-builder');
  if (!root) return;

  var surveyId = root.getAttribute('data-survey-id') || '';
  var listEl = document.getElementById('questions-list');
  var tpl = document.getElementById('question-card-template');

  var CHOICE_TYPES = ['single_choice', 'multi_choice', 'dropdown', 'ranking'];
  // Question types offered when building a quick "poll" (vs the full survey set).
  var POLL_TYPES = ['single_choice', 'multi_choice', 'yes_no'];
  var ALL_TYPES = (function () {
    var el = document.getElementById('question-types');
    try { return el ? JSON.parse(el.textContent) : []; } catch (e) { return []; }
  })();
  var BOOL_FIELDS = [
    'require_login', 'is_anonymous', 'one_per_player', 'allow_multiple_submissions',
    'allow_edit_after_submit', 'show_progress_bar', 'randomize_questions',
    'randomize_options', 'show_results_to_respondents', 'notify_email',
    'notify_discord', 'notify_push',
  ];

  function $(id) { return document.getElementById(id); }
  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  }
  function titleCase(s) {
    return (s || '').replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  // ----- config + options editors --------------------------------------- //
  function renderConfigEditor(card, type, config) {
    var box = card.querySelector('.q-config');
    box.innerHTML = '';
    config = config || {};
    var fieldCls = 'rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white text-sm focus:ring-ecs-green focus:border-ecs-green';

    function addRow(html) { var d = document.createElement('div'); d.className = 'flex flex-wrap gap-2 items-center'; d.innerHTML = html; box.appendChild(d); }

    if (type === 'rating') {
      addRow('<span class="text-xs text-gray-500">Max stars</span><input type="number" min="2" max="10" class="cfg-max w-20 ' + fieldCls + '" value="' + (config.max || 5) + '">');
    } else if (type === 'scale') {
      addRow('<span class="text-xs text-gray-500">Min</span><input type="number" class="cfg-min w-16 ' + fieldCls + '" value="' + (config.min != null ? config.min : 1) + '">' +
             '<span class="text-xs text-gray-500">Max</span><input type="number" class="cfg-max w-16 ' + fieldCls + '" value="' + (config.max != null ? config.max : 5) + '">');
      addRow('<input type="text" class="cfg-min_label flex-1 ' + fieldCls + '" placeholder="Min label (optional)" value="' + (config.min_label || '') + '">' +
             '<input type="text" class="cfg-max_label flex-1 ' + fieldCls + '" placeholder="Max label (optional)" value="' + (config.max_label || '') + '">');
    } else if (type === 'short_text' || type === 'long_text') {
      addRow('<input type="text" class="cfg-placeholder flex-1 ' + fieldCls + '" placeholder="Placeholder (optional)" value="' + (config.placeholder || '') + '">' +
             '<input type="number" class="cfg-char_limit w-28 ' + fieldCls + '" placeholder="Char limit" value="' + (config.char_limit || '') + '">');
    } else if (type === 'matrix') {
      addRow('<input type="text" class="cfg-rows flex-1 ' + fieldCls + '" placeholder="Rows (comma separated)" value="' + ((config.rows || []).join(', ')) + '">');
      addRow('<input type="text" class="cfg-cols flex-1 ' + fieldCls + '" placeholder="Columns (comma separated)" value="' + ((config.cols || []).join(', ')) + '">');
    } else if (type === 'multi_choice') {
      addRow('<span class="text-xs text-gray-500">Max selections (0 = unlimited)</span><input type="number" min="0" class="cfg-max_selections w-20 ' + fieldCls + '" value="' + (config.max_selections || 0) + '">');
    } else if (type === 'nps') {
      addRow('<span class="text-xs text-gray-400 italic">Net Promoter Score: a 0–10 "how likely to recommend" question. Scored as %promoters (9–10) − %detractors (0–6).</span>');
    }
  }

  function readConfig(card, type) {
    function val(sel) { var el = card.querySelector(sel); return el ? el.value : ''; }
    if (type === 'rating') return { max: parseInt(val('.cfg-max'), 10) || 5 };
    if (type === 'scale') return {
      min: parseInt(val('.cfg-min'), 10), max: parseInt(val('.cfg-max'), 10),
      min_label: val('.cfg-min_label'), max_label: val('.cfg-max_label'),
    };
    if (type === 'short_text' || type === 'long_text') {
      var c = { placeholder: val('.cfg-placeholder') };
      var lim = parseInt(val('.cfg-char_limit'), 10);
      if (lim) c.char_limit = lim;
      return c;
    }
    if (type === 'matrix') return {
      rows: val('.cfg-rows').split(',').map(function (s) { return s.trim(); }).filter(Boolean),
      cols: val('.cfg-cols').split(',').map(function (s) { return s.trim(); }).filter(Boolean),
    };
    if (type === 'multi_choice') {
      var ms = parseInt(val('.cfg-max_selections'), 10);
      return ms ? { max_selections: ms } : {};
    }
    return null;
  }

  function renderOptionsEditor(card, type, options) {
    var box = card.querySelector('.q-options');
    box.innerHTML = '';
    if (CHOICE_TYPES.indexOf(type) === -1) return;
    (options && options.length ? options : [{ label: '' }, { label: '' }]).forEach(function (o) {
      addOptionRow(box, o);
    });
    var add = document.createElement('button');
    add.type = 'button';
    add.className = 'q-add-option text-xs text-ecs-green hover:underline';
    add.innerHTML = '<i class="ti ti-plus"></i> Add option';
    box.appendChild(add);
  }

  function addOptionRow(box, opt) {
    opt = opt || {};
    var row = document.createElement('div');
    row.className = 'option-row flex items-center gap-2';
    if (opt.id) row.setAttribute('data-opt-id', opt.id);
    row.innerHTML =
      '<input type="text" class="opt-label flex-1 rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white text-sm focus:ring-ecs-green focus:border-ecs-green" placeholder="Option" value="' +
      String(opt.label || '').replace(/"/g, '&quot;') + '">' +
      '<button type="button" class="opt-remove text-gray-400 hover:text-red-600 p-1"><i class="ti ti-x"></i></button>';
    var addBtn = box.querySelector('.q-add-option');
    if (addBtn) box.insertBefore(row, addBtn); else box.appendChild(row);
  }

  // ----- branching (show-if) editor ------------------------------------ //
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  // Questions that can drive a condition: saved (have an id) and of a type
  // with discrete values.
  function controllableCards() {
    return Array.prototype.filter.call(listEl.querySelectorAll('.survey-question'), function (c) {
      var t = c.getAttribute('data-qtype');
      return c.getAttribute('data-qid') && (t === 'single_choice' || t === 'dropdown' || t === 'yes_no');
    });
  }

  function controllerValueOptions(ctrlCard) {
    if (ctrlCard.getAttribute('data-qtype') === 'yes_no') {
      return [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }];
    }
    var out = [];
    ctrlCard.querySelectorAll('.option-row').forEach(function (row) {
      var oid = row.getAttribute('data-opt-id');  // only saved options are referenceable
      if (oid) out.push({ value: oid, label: row.querySelector('.opt-label').value || ('Option ' + oid) });
    });
    return out;
  }

  function readLogicSelection(card) {
    var c = card.querySelector('.q-logic-ctrl'), v = card.querySelector('.q-logic-val');
    if (!c || !c.value || !v || !v.value) return null;
    return { question_id: parseInt(c.value, 10), equals: v.value };
  }

  function populateValueSelect(card, current) {
    var valSel = card.querySelector('.q-logic-val');
    var ctrlId = card.querySelector('.q-logic-ctrl').value;
    if (!ctrlId) { valSel.innerHTML = '<option value="">—</option>'; valSel.disabled = true; return; }
    valSel.disabled = false;
    var ctrlCard = listEl.querySelector('.survey-question[data-qid="' + ctrlId + '"]');
    var html = '<option value="">— value —</option>';
    if (ctrlCard) controllerValueOptions(ctrlCard).forEach(function (o) {
      var sel = current && String(current.question_id) === String(ctrlId) &&
                String(current.equals) === String(o.value) ? ' selected' : '';
      html += '<option value="' + escapeHtml(o.value) + '"' + sel + '>' + escapeHtml(o.label) + '</option>';
    });
    valSel.innerHTML = html;
  }

  function refreshLogicControls() {
    Array.prototype.forEach.call(listEl.querySelectorAll('.survey-question'), function (card) {
      var box = card.querySelector('.q-logic');
      var current = readLogicSelection(card) || card._showif;
      var ctrls = controllableCards().filter(function (c) { return c !== card; });
      if (!ctrls.length) {
        box.innerHTML = '<span class="italic">Tip: save the survey to enable "show only if" branching.</span>';
        return;
      }
      var opts = '<option value="">(always show)</option>';
      ctrls.forEach(function (c) {
        var qid = c.getAttribute('data-qid');
        var prompt = (c.querySelector('.q-prompt').value || ('Question ' + qid)).slice(0, 40);
        var sel = current && String(current.question_id) === String(qid) ? ' selected' : '';
        opts += '<option value="' + qid + '"' + sel + '>' + escapeHtml(prompt) + '</option>';
      });
      box.innerHTML =
        '<span>Show only if</span>' +
        '<select class="q-logic-ctrl rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white text-xs py-1">' + opts + '</select>' +
        '<select class="q-logic-val rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white text-xs py-1"></select>';
      populateValueSelect(card, current);
    });
  }

  // ----- question card -------------------------------------------------- //
  function createCard(q) {
    var card = tpl.content.firstElementChild.cloneNode(true);
    card.setAttribute('data-qtype', q.question_type);
    card.setAttribute('data-qid', q.id || '');
    card.querySelector('.q-prompt').value = q.prompt || '';
    card.querySelector('.q-help').value = q.help_text || '';
    card.querySelector('.q-required').checked = !!q.is_required;
    card.querySelector('.q-type-label').textContent = titleCase(q.question_type);
    // Stash any saved branching condition; rendered by refreshLogicControls().
    card._showif = (q.logic && q.logic.show_if) ? q.logic.show_if : null;
    renderConfigEditor(card, q.question_type, q.config);
    renderOptionsEditor(card, q.question_type, q.options);
    return card;
  }

  function renumber() {
    listEl.querySelectorAll('.survey-question').forEach(function (c, i) {
      c.querySelector('.q-number').textContent = (i + 1);
    });
    refreshLogicControls();
  }

  function addQuestion(type) {
    listEl.appendChild(createCard({ question_type: type }));
    renumber();
  }

  // ----- serialize ------------------------------------------------------ //
  function collectQuestions() {
    var out = [];
    listEl.querySelectorAll('.survey-question').forEach(function (card, i) {
      var type = card.getAttribute('data-qtype');
      var qid = card.getAttribute('data-qid');
      var q = {
        question_type: type,
        order: i,
        prompt: card.querySelector('.q-prompt').value.trim(),
        help_text: card.querySelector('.q-help').value.trim() || null,
        is_required: card.querySelector('.q-required').checked,
        config: readConfig(card, type),
      };
      if (qid) q.id = parseInt(qid, 10);
      var logicSel = readLogicSelection(card);
      q.logic = logicSel ? { show_if: logicSel } : null;
      if (CHOICE_TYPES.indexOf(type) !== -1) {
        q.options = [];
        card.querySelectorAll('.option-row').forEach(function (row, idx) {
          var label = row.querySelector('.opt-label').value.trim();
          if (!label) return;
          var opt = { label: label, order: idx };
          var oid = row.getAttribute('data-opt-id');
          if (oid) opt.id = parseInt(oid, 10);
          q.options.push(opt);
        });
      }
      out.push(q);
    });
    return out;
  }

  function collectSurvey() {
    var data = {
      title: $('sv-title').value.trim(),
      description: $('sv-description').value.trim() || null,
      survey_type: $('sv-survey_type').value,
      category: $('sv-category').value.trim() || null,
      season_id: $('sv-season_id').value ? parseInt($('sv-season_id').value, 10) : null,
      confirmation_message: $('sv-confirmation_message').value.trim() || null,
      open_at: $('sv-open_at').value || null,
      close_at: $('sv-close_at').value || null,
      questions: collectQuestions(),
    };
    BOOL_FIELDS.forEach(function (f) { data[f] = $('sv-' + f).checked; });
    return data;
  }

  // ----- load ----------------------------------------------------------- //
  function loadBootstrap() {
    var el = document.getElementById('survey-bootstrap');
    if (!el) {
      // New survey defaults.
      $('sv-require_login').checked = true;
      $('sv-one_per_player').checked = true;
      $('sv-show_progress_bar').checked = true;
      return;
    }
    var s = JSON.parse(el.textContent);
    $('sv-title').value = s.title || '';
    $('sv-description').value = s.description || '';
    $('sv-survey_type').value = s.survey_type || 'survey';
    $('sv-category').value = s.category || '';
    if (s.season_id) $('sv-season_id').value = s.season_id;
    $('sv-confirmation_message').value = s.confirmation_message || '';
    if (s.open_at) $('sv-open_at').value = s.open_at.slice(0, 16);
    if (s.close_at) $('sv-close_at').value = s.close_at.slice(0, 16);
    // Missing toggles fall back to sensible defaults (e.g. starter templates
    // that only set is_anonymous still want login + one-per-person on).
    var DEFAULTS = { require_login: true, one_per_player: true, show_progress_bar: true };
    BOOL_FIELDS.forEach(function (f) {
      $('sv-' + f).checked = (s[f] !== undefined) ? !!s[f] : !!DEFAULTS[f];
    });
    (s.questions || []).forEach(function (q) { listEl.appendChild(createCard(q)); });
    renumber();
  }

  // ----- save ----------------------------------------------------------- //
  function save() {
    var data = collectSurvey();
    if (!data.title) { window.Swal.fire('Title required', 'Give your survey a title before saving.', 'warning'); return; }
    var method = surveyId ? 'PUT' : 'POST';
    var url = surveyId ? '/admin-panel/api/surveys/' + surveyId : '/admin-panel/api/surveys';
    var btn = $('survey-save-btn');
    btn.disabled = true;
    fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(data),
    }).then(function (r) { return r.json(); }).then(function (res) {
      btn.disabled = false;
      if (res.success) {
        if (res.redirect) { window.location.href = res.redirect; }
        else {
          window.Swal.fire({ icon: 'success', title: 'Saved', timer: 1200, showConfirmButton: false });
          if (!surveyId && res.survey_id) {
            window.location.href = '/admin-panel/surveys/' + res.survey_id + '/edit';
          }
        }
      } else {
        window.Swal.fire('Could not save', res.error || 'Unknown error', 'error');
      }
    }).catch(function (e) {
      btn.disabled = false;
      window.Swal.fire('Error', String(e), 'error');
    });
  }

  // ----- add-question type list (poll = simple subset, survey = full) --- //
  function populateTypeDropdown() {
    var sel = $('add-question-type');
    var prev = sel.value;
    var isPoll = $('sv-survey_type').value === 'poll';
    var types = isPoll ? POLL_TYPES : (ALL_TYPES.length ? ALL_TYPES : POLL_TYPES);
    sel.innerHTML = types.map(function (t) {
      return '<option value="' + t + '">' + titleCase(t) + '</option>';
    }).join('');
    if (types.indexOf(prev) !== -1) sel.value = prev;
  }

  // ----- live preview (respondent's view) ------------------------------- //
  var previewOn = false;

  function previewQuestion(q, idx) {
    var t = q.question_type, name = 'pq_' + idx, html = '';
    var label = '<label class="block text-sm font-semibold text-gray-900 dark:text-white">' +
      escapeHtml(q.prompt || 'Untitled question') +
      (q.is_required ? ' <span class="text-red-500">*</span>' : '') + '</label>';
    var help = q.help_text ? '<p class="text-xs text-gray-500 dark:text-gray-400">' + escapeHtml(q.help_text) + '</p>' : '';
    var opts = (q.options || []);

    function radioList(type) {
      return opts.map(function (o) {
        return '<label class="flex items-center gap-2.5 p-2.5 rounded-lg border border-gray-200 dark:border-gray-700"><input type="' +
          type + '" name="' + name + '" class="text-ecs-green"><span class="text-sm text-gray-700 dark:text-gray-200">' +
          escapeHtml(o.label) + '</span></label>';
      }).join('');
    }
    function numberBtns(lo, hi) {
      var out = '';
      for (var n = lo; n <= hi; n++) {
        out += '<span class="inline-flex w-9 h-9 items-center justify-center rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-300">' + n + '</span>';
      }
      return '<div class="flex flex-wrap gap-1.5">' + out + '</div>';
    }

    if (t === 'single_choice') html = '<div class="space-y-2">' + radioList('radio') + '</div>';
    else if (t === 'multi_choice') html = '<div class="space-y-2">' + radioList('checkbox') + '</div>';
    else if (t === 'dropdown') html = '<select class="block w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm"><option>— Select —</option>' + opts.map(function (o) { return '<option>' + escapeHtml(o.label) + '</option>'; }).join('') + '</select>';
    else if (t === 'yes_no') html = '<div class="flex gap-3"><span class="flex-1 text-center p-2.5 rounded-lg border border-gray-200 dark:border-gray-700 text-sm">Yes</span><span class="flex-1 text-center p-2.5 rounded-lg border border-gray-200 dark:border-gray-700 text-sm">No</span></div>';
    else if (t === 'short_text' || t === 'email' || t === 'number' || t === 'date') html = '<input class="block w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm" placeholder="' + escapeHtml((q.config && q.config.placeholder) || '') + '">';
    else if (t === 'long_text') html = '<textarea rows="3" class="block w-full rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 text-sm"></textarea>';
    else if (t === 'rating') html = numberBtns(1, (q.config && q.config.max) || 5);
    else if (t === 'scale') html = numberBtns((q.config && q.config.min) != null ? q.config.min : 1, (q.config && q.config.max) != null ? q.config.max : 5);
    else if (t === 'nps') html = numberBtns(0, 10);
    else if (t === 'ranking') html = '<div class="space-y-2">' + opts.map(function (o) { return '<div class="flex items-center gap-3 p-2.5 rounded-lg border border-gray-200 dark:border-gray-700"><span class="w-10 h-8 rounded border border-gray-200 dark:border-gray-700 inline-flex items-center justify-center text-xs text-gray-400">#</span><span class="text-sm text-gray-700 dark:text-gray-200">' + escapeHtml(o.label) + '</span></div>'; }).join('') + '</div>';
    else if (t === 'matrix') {
      var rows = (q.config && q.config.rows) || [], cols = (q.config && q.config.cols) || [];
      html = '<table class="min-w-full text-sm border border-gray-200 dark:border-gray-700"><thead><tr><th></th>' + cols.map(function (c) { return '<th class="p-2 text-xs text-gray-600 dark:text-gray-300">' + escapeHtml(c) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.map(function (r) { return '<tr class="border-t border-gray-200 dark:border-gray-700"><td class="p-2 text-gray-700 dark:text-gray-200">' + escapeHtml(r) + '</td>' + cols.map(function () { return '<td class="p-2 text-center"><input type="radio" class="text-ecs-green"></td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table>';
    }
    return '<div class="space-y-2">' + label + help + html + '</div>';
  }

  function renderPreview() {
    var data = collectSurvey();
    var surface = $('preview-surface');
    var parts = ['<div class="bg-white dark:bg-gray-800 rounded-2xl shadow border border-gray-200 dark:border-gray-700 overflow-hidden">'];
    // header
    parts.push('<div class="px-5 pt-5 pb-4 bg-gradient-to-br from-emerald-600 to-emerald-800">');
    parts.push('<h2 class="text-lg font-bold text-white">' + escapeHtml(data.title || 'Untitled survey') + '</h2>');
    if (data.description) parts.push('<p class="text-emerald-100 text-sm mt-1">' + escapeHtml(data.description) + '</p>');
    if (data.is_anonymous) parts.push('<p class="text-xs text-emerald-50/90 mt-2"><i class="ti ti-eye-off"></i> Your responses are anonymous.</p>');
    parts.push('</div>');
    if (data.show_progress_bar) parts.push('<div class="h-1.5 bg-gray-100 dark:bg-gray-700"><div class="h-full bg-ecs-green" style="width:35%"></div></div>');
    // body
    parts.push('<div class="px-5 py-5 space-y-6" style="pointer-events:none">');
    if (!data.questions.length) parts.push('<p class="text-sm text-gray-400">No questions yet — add some to see them here.</p>');
    data.questions.forEach(function (q, i) { parts.push(previewQuestion(q, i)); });
    parts.push('<button class="w-full h-11 rounded-lg bg-ecs-green text-white text-sm font-semibold mt-2">Submit</button>');
    parts.push('</div></div>');
    if (data.confirmation_message) parts.push('<p class="text-xs text-gray-500 dark:text-gray-400 mt-3 text-center"><i class="ti ti-circle-check"></i> After submit: "' + escapeHtml(data.confirmation_message) + '"</p>');
    surface.innerHTML = parts.join('');
  }

  function updateAccessHint() {
    var hint = $('access-hint');
    if (!hint) return;
    var login = $('sv-require_login').checked;
    var anon = $('sv-is_anonymous').checked;
    var onePer = $('sv-one_per_player').checked;
    var msg = '';
    if (anon && login) {
      msg = 'Login-gated + anonymous: members must sign in, but responses are not tied to them.' +
            (onePer ? ' One-per-person is still enforced via a private token.' : '');
    } else if (anon && !login) {
      msg = 'Open + anonymous: anyone with the link can respond.' +
            (onePer ? ' Note: one-per-person can\'t be enforced without login.' : '');
    } else if (login) {
      msg = 'Members must sign in; responses are linked to them.';
    }
    hint.textContent = msg;
  }

  function setPreview(on) {
    previewOn = on;
    $('builder-edit').classList.toggle('hidden', on);
    $('builder-preview').classList.toggle('hidden', !on);
    $('survey-preview-label').textContent = on ? 'Edit' : 'Preview';
    $('survey-preview-btn').querySelector('i').className = on ? 'ti ti-pencil' : 'ti ti-eye';
    if (on) renderPreview();
  }

  // ----- events --------------------------------------------------------- //
  $('add-question-btn').addEventListener('click', function () {
    addQuestion($('add-question-type').value);
  });
  $('survey-save-btn').addEventListener('click', save);
  $('survey-preview-btn').addEventListener('click', function () { setPreview(!previewOn); });
  $('sv-survey_type').addEventListener('change', populateTypeDropdown);
  ['sv-require_login', 'sv-is_anonymous', 'sv-one_per_player'].forEach(function (id) {
    $(id).addEventListener('change', updateAccessHint);
  });

  // While previewing, reflect settings changes live (edit pane is hidden, so
  // only the still-visible settings inputs fire here).
  root.addEventListener('change', function () { if (previewOn) renderPreview(); });
  root.addEventListener('input', function () { if (previewOn) renderPreview(); });

  listEl.addEventListener('change', function (e) {
    if (e.target.classList && e.target.classList.contains('q-logic-ctrl')) {
      var card = e.target.closest('.survey-question');
      if (card) populateValueSelect(card, null);
    }
  });

  listEl.addEventListener('click', function (e) {
    var card = e.target.closest('.survey-question');
    if (!card) return;
    if (e.target.closest('.q-remove')) { card.remove(); renumber(); }
    else if (e.target.closest('.q-move-up') && card.previousElementSibling) {
      listEl.insertBefore(card, card.previousElementSibling); renumber();
    } else if (e.target.closest('.q-move-down') && card.nextElementSibling) {
      listEl.insertBefore(card.nextElementSibling, card); renumber();
    } else if (e.target.closest('.q-add-option')) {
      addOptionRow(card.querySelector('.q-options'), '');
    } else if (e.target.closest('.opt-remove')) {
      e.target.closest('.option-row').remove();
    }
  });

  loadBootstrap();
  populateTypeDropdown();
  updateAccessHint();
})();
