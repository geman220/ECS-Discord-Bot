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
  // Once responses exist the PUT route rejects any payload carrying a
  // "questions" key (409). Since collectSurvey() always builds one, a locked
  // survey could not save its settings at all — so the client drops the key and
  // locks the question editor to match.
  var responseCount = parseInt(root.getAttribute('data-response-count') || '0', 10) || 0;
  var structureLocked = responseCount > 0;

  var CHOICE_TYPES = ['single_choice', 'multi_choice', 'dropdown', 'ranking'];
  // Question types offered when building a quick "poll" (vs the full survey set).
  var POLL_TYPES = ['single_choice', 'multi_choice', 'yes_no'];
  // The only shapes Discord's native poll API can represent. Kept in sync with
  // the server check in admin_panel/routes/surveys/distribute.py.
  var NATIVE_POLL_TYPES = ['single_choice', 'multi_choice'];
  var NATIVE_POLL_MAX_OPTIONS = 10;

  // Everything that visibly differs between the two modes, in one place, so the
  // page can re-skin itself the instant the type changes instead of looking
  // identical whether you're building a survey or a poll.
  var MODES = {
    survey: {
      noun: 'Survey',
      heading: 'Survey builder',
      icon: 'ti-clipboard-list',
      banner: 'border-ecs-green/40 bg-green-50/60 dark:border-ecs-green/50 dark:bg-ecs-green/10',
      iconWrap: 'bg-ecs-green/15 text-ecs-green',
      chipOn: 'bg-ecs-green text-white',
      blurb: 'As many questions as you like — ratings, scales, free text, branching — answered on a <strong>web form</strong>. Share it by link, email, push, or a Discord button that opens the site.',
      addLabel: 'Add question',
      titlePlaceholder: 'e.g. End of Season 2026 Survey',
      descPlaceholder: 'Shown at the top of the survey (optional)',
      previewCaption: 'Live preview — the web form members fill out. Updates as you edit.',
    },
    poll: {
      noun: 'Poll',
      heading: 'Poll builder',
      icon: 'ti-chart-bar',
      banner: 'border-indigo-400/60 bg-indigo-50 dark:border-indigo-500/50 dark:bg-indigo-500/10',
      iconWrap: 'bg-indigo-500/15 text-indigo-600 dark:text-indigo-300',
      chipOn: 'bg-indigo-600 text-white',
      blurb: '<strong>One</strong> choice question with 2–10 options. It can be posted as a real <strong>Discord poll</strong> that members vote on without leaving Discord — those votes sync back into the results here.',
      addLabel: 'Add the poll question',
      titlePlaceholder: 'e.g. Which kickoff time works best?',
      descPlaceholder: 'Optional context shown above the question',
      previewCaption: 'Live preview — how the poll looks in Discord and on the web.',
    },
  };
  var BANNER_BASE = 'rounded-xl border-2 p-4 sm:p-5 mb-5';
  var ICONWRAP_BASE = 'shrink-0 w-11 h-11 rounded-lg flex items-center justify-center';
  var CHIP_BASE = 'type-switch inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-sm font-medium transition-colors';
  var CHIP_OFF = 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200';
  var ALL_TYPES = (function () {
    var el = document.getElementById('question-types');
    try { return el ? JSON.parse(el.textContent) : []; } catch (e) { return []; }
  })();
  var BOOL_FIELDS = [
    'is_template',
    'require_login', 'is_anonymous', 'one_per_player', 'allow_multiple_submissions',
    'allow_edit_after_submit', 'show_progress_bar', 'randomize_questions',
    'randomize_options', 'show_results_to_respondents', 'notify_email',
    'notify_discord', 'notify_push',
  ];

  var bootstrapSettings = null;   // settings JSONB loaded from the survey
  var discordChannelsLoaded = false;

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
    // Branching is meaningless in a one-question poll — don't show the tip.
    var pollMode = isPoll();
    Array.prototype.forEach.call(listEl.querySelectorAll('.survey-question'), function (card) {
      var box = card.querySelector('.q-logic');
      box.classList.toggle('hidden', pollMode);
      if (pollMode) {
        // Emptied, not just hidden: a hidden <select> still holds its value and
        // collectQuestions() would keep serializing a branching rule the admin
        // can no longer see. card._showif still carries it back if they switch
        // to Survey again.
        box.innerHTML = '';
        return;
      }
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
    refreshAddQuestion();
    refreshPollReadiness();
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

    // Preserve any existing settings + merge the chosen Discord channel.
    var settings = bootstrapSettings ? JSON.parse(JSON.stringify(bootstrapSettings)) : {};
    var dch = $('sv-discord_channel');
    if (dch && dch.value) {
      settings.discord_channel_id = dch.value;
      settings.discord_channel_name = dch.options[dch.selectedIndex] ? dch.options[dch.selectedIndex].text : '';
    } else {
      delete settings.discord_channel_id;
      delete settings.discord_channel_name;
    }
    data.settings = settings;
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
      // New-template flow (?as_template=1): pre-check "Save as template".
      if (root.getAttribute('data-as-template')) $('sv-is_template').checked = true;
      return;
    }
    var s = JSON.parse(el.textContent);
    bootstrapSettings = s.settings || {};
    $('sv-title').value = s.title || '';
    $('sv-description').value = s.description || '';
    // Only an explicit type overrides the server-chosen mode — a starter
    // template with no survey_type must not silently drag ?type=poll back to
    // "survey".
    if (s.survey_type) $('sv-survey_type').value = s.survey_type;
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
    var noun = MODES[currentType()].noun.toLowerCase();
    if (!data.title) {
      window.Swal.fire('Title required', 'Give your ' + noun + ' a title before saving.', 'warning');
      return;
    }
    if (structureLocked) {
      // Settings/schedule only — sending "questions" would 409 the whole save.
      delete data.questions;
    } else if (isPoll() && data.questions.length > 1) {
      window.Swal.fire('A poll is one question',
        'This has ' + data.questions.length + ' questions. Remove the extras, or switch the type back to Survey.',
        'warning');
      return;
    }
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
    var types = isPoll() ? POLL_TYPES : (ALL_TYPES.length ? ALL_TYPES : POLL_TYPES);
    sel.innerHTML = types.map(function (t) {
      return '<option value="' + t + '">' + titleCase(t) + '</option>';
    }).join('');
    if (types.indexOf(prev) !== -1) sel.value = prev;
  }

  // ----- survey/poll mode ------------------------------------------------ //
  function currentType() { return $('sv-survey_type').value === 'poll' ? 'poll' : 'survey'; }
  function isPoll() { return currentType() === 'poll'; }
  function questionCards() {
    return Array.prototype.slice.call(listEl.querySelectorAll('.survey-question'));
  }

  /** Re-skin the whole page for the active type. Called on load and on every
   *  type change, so a poll never looks like a survey with a flag flipped. */
  function applyTypeMode() {
    var m = MODES[currentType()];

    var banner = $('mode-banner');
    if (banner) banner.className = BANNER_BASE + ' ' + m.banner;
    var iconWrap = $('mode-icon-wrap');
    if (iconWrap) iconWrap.className = ICONWRAP_BASE + ' ' + m.iconWrap;
    var icon = $('mode-icon');
    if (icon) icon.className = 'ti ' + m.icon + ' text-xl';
    var noun = $('mode-noun');
    if (noun) noun.textContent = m.noun;
    var blurb = $('mode-blurb');
    if (blurb) blurb.innerHTML = m.blurb;

    var heading = document.querySelector('h1 span.truncate');
    if (heading) heading.textContent = m.heading;

    // Segmented switcher state
    document.querySelectorAll('.type-switch').forEach(function (btn) {
      var on = btn.getAttribute('data-type-switch') === currentType();
      btn.className = CHIP_BASE + ' ' + (on ? m.chipOn : CHIP_OFF);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });

    // Settings that only make sense for one of the two modes. Clear the hidden
    // ones too — a checked-but-invisible toggle that still saves is exactly the
    // kind of phantom setting that makes this page confusing.
    document.querySelectorAll('[data-survey-only]').forEach(function (el) {
      el.classList.toggle('hidden', isPoll());
    });
    if (isPoll()) {
      ['sv-show_progress_bar', 'sv-randomize_questions'].forEach(function (id) {
        if ($(id)) $(id).checked = false;
      });
    }
    document.querySelectorAll('[data-poll-only]').forEach(function (el) {
      el.classList.toggle('hidden', !isPoll());
    });

    var titleEl = $('sv-title'), descEl = $('sv-description');
    if (titleEl) titleEl.placeholder = m.titlePlaceholder;
    if (descEl) descEl.placeholder = m.descPlaceholder;
    var cap = $('preview-caption');
    if (cap) cap.innerHTML = '<i class="ti ti-eye"></i> ' + m.previewCaption;

    populateTypeDropdown();
    refreshAddQuestion();
    refreshPollReadiness();
    // Branching visibility is mode-dependent, so it has to re-run on a type
    // switch and not only when questions are added or reordered.
    refreshLogicControls();
    if (previewOn) renderPreview();
  }

  /** In poll mode a second question is never valid — say so instead of letting
   *  the admin build one and find out at send time. */
  function refreshAddQuestion() {
    var btn = $('add-question-btn'), label = $('add-question-label'), note = $('add-question-note');
    if (!btn) return;
    var count = questionCards().length;
    var blocked = structureLocked || (isPoll() && count >= 1);
    btn.disabled = blocked;
    if (label) label.textContent = MODES[currentType()].addLabel;
    if (note) {
      if (structureLocked) {
        note.textContent = 'Questions are locked because responses have already come in. Duplicate this to make an editable new version.';
        note.classList.remove('hidden');
      } else if (blocked) {
        note.textContent = 'A poll is one question. Remove this one to ask something else, or switch to Survey for a multi-question form.';
        note.classList.remove('hidden');
      } else {
        note.classList.add('hidden');
      }
    }
  }

  /** Live "can this actually be posted to Discord?" checklist. Mirrors the
   *  server-side rule in the native-poll send route. */
  function refreshPollReadiness() {
    var box = $('poll-readiness'), list = $('poll-readiness-list');
    if (!box || !list) return;
    if (!isPoll()) { box.classList.add('hidden'); return; }
    box.classList.remove('hidden');

    var cards = questionCards();
    var nativeCards = cards.filter(function (c) {
      return NATIVE_POLL_TYPES.indexOf(c.getAttribute('data-qtype')) !== -1;
    });
    var checks = [];

    if (nativeCards.length === 1) {
      checks.push([true, 'One ' + titleCase(nativeCards[0].getAttribute('data-qtype')) + ' question']);
    } else if (!cards.length) {
      checks.push([false, 'Add one Single choice or Multiple choice question']);
    } else if (!nativeCards.length) {
      checks.push([false, 'Discord polls need a Single choice or Multiple choice question — ' +
        titleCase(cards[0].getAttribute('data-qtype')) + ' works on the web only']);
    } else {
      checks.push([false, nativeCards.length + ' choice questions — a Discord poll takes exactly one']);
    }

    if (nativeCards.length === 1) {
      var labels = [];
      nativeCards[0].querySelectorAll('.option-row .opt-label').forEach(function (i) {
        if (i.value.trim()) labels.push(i.value.trim());
      });
      if (labels.length < 2) {
        checks.push([false, 'At least 2 filled-in options (' + labels.length + ' so far)']);
      } else if (labels.length > NATIVE_POLL_MAX_OPTIONS) {
        checks.push([false, labels.length + ' options — Discord only shows the first ' + NATIVE_POLL_MAX_OPTIONS]);
      } else {
        checks.push([true, labels.length + ' options']);
      }
      var longOnes = labels.filter(function (l) { return l.length > 55; }).length;
      if (longOnes) {
        checks.push([false, longOnes + ' option label' + (longOnes === 1 ? '' : 's') + ' over 55 characters — Discord will cut them off']);
      }
    }

    var ok = checks.every(function (c) { return c[0]; });
    list.innerHTML = checks.map(function (c) {
      return '<li class="flex items-start gap-2 ' +
        (c[0] ? 'text-gray-600 dark:text-gray-300' : 'text-amber-700 dark:text-amber-300') + '">' +
        '<i class="ti ' + (c[0] ? 'ti-circle-check text-green-600 dark:text-green-400' : 'ti-alert-circle') +
        ' mt-0.5 shrink-0"></i><span>' + escapeHtml(c[1]) + '</span></li>';
    }).join('') +
      '<li class="flex items-start gap-2 pt-1 ' +
      (ok ? 'text-green-700 dark:text-green-400' : 'text-gray-500 dark:text-gray-400') + '">' +
      '<i class="ti ' + (ok ? 'ti-brand-discord' : 'ti-info-circle') + ' mt-0.5 shrink-0"></i><span>' +
      (ok ? 'Ready to post as a native Discord poll from the Distribute page.'
          : 'Until the above is fixed this still works as a web poll — just not as a native Discord poll.') +
      '</span></li>';
  }

  /** Switching type is a real change with real consequences — spell them out
   *  rather than silently swapping a dropdown value. */
  function requestTypeSwitch(to) {
    if (to === currentType()) return;
    var cards = questionCards();
    var m = MODES[to];
    var lines = [];

    if (to === 'poll') {
      lines.push('Only <strong>Single choice</strong>, <strong>Multiple choice</strong> and <strong>Yes/No</strong> questions can be added.');
      lines.push('Progress bar and question randomising are hidden — a poll is one question.');
      lines.push('With one choice question (2–10 options) you can post it as a <strong>native Discord poll</strong>.');
      var extra = cards.length - 1;
      if (extra > 0) {
        lines.push('<span class="text-amber-600 dark:text-amber-400">You have ' + cards.length +
          ' questions. Nothing is deleted, but you\'ll need to remove ' + extra +
          ' before this can post to Discord as a poll.</span>');
      }
      var nonPoll = cards.filter(function (c) {
        return POLL_TYPES.indexOf(c.getAttribute('data-qtype')) === -1;
      });
      if (nonPoll.length) {
        lines.push('<span class="text-amber-600 dark:text-amber-400">' + nonPoll.length +
          ' existing question' + (nonPoll.length === 1 ? ' is' : 's are') +
          ' not a poll type. They stay put and still work on the web.</span>');
      }
    } else {
      lines.push('All question types become available again, including ratings, scales, free text and branching.');
      lines.push('Progress bar and randomising come back.');
      lines.push('<span class="text-amber-600 dark:text-amber-400">It can no longer be posted as a native Discord poll — Discord gets a link button instead.</span>');
    }

    window.Swal.fire({
      icon: 'question',
      title: 'Switch to ' + m.noun + '?',
      html: '<ul style="text-align:left;padding-left:1.1em;list-style:disc">' +
            lines.map(function (l) { return '<li style="margin:.35em 0">' + l + '</li>'; }).join('') +
            '</ul>',
      showCancelButton: true,
      confirmButtonText: 'Switch to ' + m.noun,
      cancelButtonText: 'Keep ' + MODES[currentType()].noun,
      confirmButtonColor: to === 'poll' ? '#4f46e5' : '#166534',
    }).then(function (res) {
      if (!res.isConfirmed) return;
      $('sv-survey_type').value = to;
      applyTypeMode();
      window.Swal.fire({
        icon: 'success',
        title: 'Now building a ' + m.noun,
        text: 'Save to keep the change.',
        timer: 1600,
        showConfirmButton: false,
      });
    });
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

  /** The Discord-side view of a poll — the whole reason "poll" is a distinct
   *  type, so the builder shows it rather than describing it. */
  function renderDiscordPollCard(data) {
    var q = (data.questions || []).filter(function (x) {
      return NATIVE_POLL_TYPES.indexOf(x.question_type) !== -1;
    })[0];
    var parts = ['<div class="mb-4">'];
    parts.push('<p class="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">In Discord — members vote here</p>');

    if (!q) {
      parts.push('<div class="rounded-lg border border-dashed border-gray-300 dark:border-gray-600 p-4 text-xs text-gray-500 dark:text-gray-400">' +
        'Add a Single choice or Multiple choice question to see the Discord poll.</div></div>');
      return parts.join('');
    }

    var opts = (q.options || []).filter(function (o) { return o.label; }).slice(0, NATIVE_POLL_MAX_OPTIONS);
    parts.push('<div class="rounded-lg bg-[#313338] p-3 text-left">' +
      '<div class="flex items-start gap-2.5">' +
      '<div class="w-8 h-8 rounded-full bg-ecs-green flex items-center justify-center text-white text-xs font-bold shrink-0">ECS</div>' +
      '<div class="min-w-0 flex-1">' +
      '<p class="text-xs"><span class="font-semibold text-white">ECS Bot</span> <span class="ml-1 px-1 rounded bg-indigo-500 text-white text-[9px] uppercase">App</span></p>' +
      '<div class="mt-1 rounded bg-[#2b2d31] p-2.5">' +
      '<p class="text-sm font-semibold text-white">' + escapeHtml(q.prompt || 'Your question') + '</p>' +
      '<div class="mt-2 space-y-1.5">' +
      (opts.length
        ? opts.map(function (o) {
            return '<div class="rounded border border-[#4e5058] px-2.5 py-1.5 text-xs text-gray-200">' +
              escapeHtml(o.label.slice(0, 55)) + '</div>';
          }).join('')
        : '<p class="text-[11px] text-gray-400">No options yet</p>') +
      '</div>' +
      '<p class="mt-2 text-[10px] text-gray-400"><i class="ti ti-clock text-[10px]"></i> Poll · ' +
      (q.question_type === 'multi_choice' ? 'multiple answers allowed' : 'one answer each') + '</p>' +
      '</div></div></div></div></div>');
    return parts.join('');
  }

  function renderPreview() {
    var data = collectSurvey();
    var surface = $('preview-surface');
    var parts = [];
    if (isPoll()) {
      parts.push(renderDiscordPollCard(data));
      parts.push('<p class="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">On the web — the same poll as a page</p>');
    }
    parts.push('<div class="bg-white dark:bg-gray-800 rounded-2xl shadow border border-gray-200 dark:border-gray-700 overflow-hidden">');
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

  // ----- Discord channel selector (live, Pub League only) --------------- //
  function loadDiscordChannels(selectedId) {
    var sel = $('sv-discord_channel');
    if (!sel || discordChannelsLoaded) {
      if (sel && selectedId) sel.value = selectedId;
      return;
    }
    discordChannelsLoaded = true;
    fetch('/admin-panel/api/surveys/discord-channels')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var chans = (data && data.channels) || [];
        if (!chans.length) {
          sel.innerHTML = '<option value="">No channels found — pick one at send time</option>';
          return;
        }
        sel.innerHTML = '<option value="">— Select a channel —</option>' +
          chans.map(function (c) {
            return '<option value="' + c.id + '">#' + escapeHtml(c.name) +
              (c.category ? ' (' + escapeHtml(c.category) + ')' : '') + '</option>';
          }).join('');
        if (selectedId) sel.value = selectedId;
      })
      .catch(function () {
        sel.innerHTML = '<option value="">Couldn\'t reach Discord — pick at send time</option>';
      });
  }

  function toggleDiscordChannel() {
    var on = $('sv-notify_discord').checked;
    $('discord-channel-wrap').classList.toggle('hidden', !on);
    if (on) {
      var saved = bootstrapSettings && bootstrapSettings.discord_channel_id;
      loadDiscordChannels(saved);
    }
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
  $('sv-survey_type').addEventListener('change', applyTypeMode);
  document.querySelectorAll('.type-switch').forEach(function (btn) {
    btn.addEventListener('click', function () {
      requestTypeSwitch(btn.getAttribute('data-type-switch'));
    });
  });
  ['sv-require_login', 'sv-is_anonymous', 'sv-one_per_player'].forEach(function (id) {
    $(id).addEventListener('change', updateAccessHint);
  });
  $('sv-notify_discord').addEventListener('change', toggleDiscordChannel);

  // While previewing, reflect settings changes live (edit pane is hidden, so
  // only the still-visible settings inputs fire here).
  root.addEventListener('change', function () { if (previewOn) renderPreview(); });
  root.addEventListener('input', function () { if (previewOn) renderPreview(); });

  // Option labels and question prompts drive the poll readiness checklist, so
  // it has to re-evaluate as they're typed, not just when questions are added.
  listEl.addEventListener('input', refreshPollReadiness);

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
  if (structureLocked) {
    // Read-only, not removed: admins still need to see what they asked before
    // reading the results. Edits here are dropped from the payload anyway, so
    // leaving the fields typable would be a lie.
    listEl.classList.add('opacity-60', 'pointer-events-none');
    listEl.setAttribute('aria-readonly', 'true');
  }
  applyTypeMode();         // re-skins the page for survey vs poll (calls populateTypeDropdown)
  updateAccessHint();
  toggleDiscordChannel();  // reveal + populate the channel select if notify_discord is on
})();
