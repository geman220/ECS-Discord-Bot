/* survey-distribute.js — lifecycle (open/close), copy link, and channel sends. */
(function () {
  'use strict';
  var root = document.getElementById('distribute-root');
  if (!root) return;
  var sid = root.getAttribute('data-survey-id');

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  }
  function post(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json(); });
  }

  // "league:5" -> {type:'by_league', league_ids:[5]} (email-broadcast filter shape)
  function emailFilter(value) {
    if (value.indexOf(':') === -1) return { type: value };
    var parts = value.split(':'), kind = parts[0], id = parts[1];
    if (kind === 'league') return { type: 'by_league', league_ids: [parseInt(id, 10)] };
    if (kind === 'team') return { type: 'by_team', team_ids: [parseInt(id, 10)] };
    if (kind === 'role') return { type: 'by_role', role_names: [id] };
    return { type: 'all_active' };
  }
  // "league:5" -> {target_type:'league', target_ids:[5]} (push targeting shape)
  function pushTarget(value) {
    if (value.indexOf(':') === -1) return { target_type: value };
    var parts = value.split(':');
    return { target_type: parts[0], target_ids: [parseInt(parts[1], 10)] };
  }

  function done(res, okMsg) {
    if (res.success) {
      window.Swal.fire({ icon: 'success', title: okMsg, timer: 1500, showConfirmButton: false })
        .then(function () { window.location.reload(); });
    } else {
      window.Swal.fire('Could not send', res.error || 'Unknown error', 'error');
    }
  }

  function setStatus(s) { var b = document.getElementById('survey-status'); if (b) b.textContent = s; }

  // Resolve a channel picker (select with optional "custom ID" text field).
  function channelValue(selectId) {
    var sel = document.getElementById(selectId);
    if (!sel) return '';
    if (sel.value === '__custom__') {
      var custom = document.getElementById(sel.getAttribute('data-custom'));
      return custom ? custom.value.trim() : '';
    }
    return sel.value.trim();
  }

  // Reveal the custom-ID text field when "Custom channel ID…" is chosen.
  document.addEventListener('change', function (e) {
    var sel = e.target.closest('select[data-custom]');
    if (!sel) return;
    var custom = document.getElementById(sel.getAttribute('data-custom'));
    if (custom) custom.classList.toggle('hidden', sel.value !== '__custom__');
  });

  document.addEventListener('click', function (e) {
    // Lifecycle
    var life = e.target.closest('[data-lifecycle]');
    if (life) {
      post('/admin-panel/api/surveys/' + sid + '/status', { action: life.getAttribute('data-lifecycle') })
        .then(function (res) { if (res.success) setStatus(res.status); else window.Swal.fire('Error', res.error || 'Failed', 'error'); });
      return;
    }
    // Copy link
    if (e.target.closest('#copy-url-btn')) {
      var input = document.getElementById('public-url');
      input.select();
      navigator.clipboard.writeText(input.value).then(function () {
        window.Swal.fire({ icon: 'success', title: 'Link copied', timer: 900, showConfirmButton: false });
      });
      return;
    }
    // Channel sends
    var send = e.target.closest('[data-send]');
    if (!send) return;
    var channel = send.getAttribute('data-send');
    send.disabled = true;
    var p;
    if (channel === 'email') {
      p = post('/admin-panel/api/surveys/' + sid + '/send/email',
               { filter_criteria: emailFilter(document.getElementById('email-audience').value) })
        .then(function (res) { done(res, res.success ? ('Queued ' + res.recipients + ' emails') : ''); });
    } else if (channel === 'push') {
      p = post('/admin-panel/api/surveys/' + sid + '/send/push',
               pushTarget(document.getElementById('push-audience').value))
        .then(function (res) { done(res, 'Push sent'); });
    } else if (channel === 'discord-embed') {
      var ec = channelValue('embed-channel');
      if (!ec) { window.Swal.fire('Pick a channel', 'Choose a Discord channel first.', 'warning'); send.disabled = false; return; }
      p = post('/admin-panel/api/surveys/' + sid + '/send/discord-embed', { channel_id: ec })
        .then(function (res) { done(res, 'Embed posted'); });
    } else if (channel === 'native-poll') {
      var allTeams = !!(document.getElementById('poll-all-teams') || {}).checked;
      var payload = { duration_hours: parseInt(document.getElementById('poll-duration').value, 10) || 48 };
      if (allTeams) {
        payload.all_team_channels = true;
      } else {
        var pc = channelValue('poll-channel');
        if (!pc) { window.Swal.fire('Pick a channel', 'Choose a Discord channel, or tick "every team\'s channel".', 'warning'); send.disabled = false; return; }
        payload.channel_id = pc;
      }
      p = post('/admin-panel/api/surveys/' + sid + '/send/native-poll', payload)
        .then(function (res) {
          var msg = 'Poll posted';
          if (res && res.success && typeof res.sent === 'number' && allTeams) {
            msg = 'Poll posted to ' + res.sent + ' team channel' + (res.sent === 1 ? '' : 's');
            if (res.failed && res.failed.length) msg += ' (' + res.failed.length + ' failed — see server log)';
          }
          done(res, msg);
        });
    }
    if (p) p.finally(function () { send.disabled = false; });
  });

  // "Every team's channel" toggle hides the single-channel picker.
  var allTeamsToggle = document.getElementById('poll-all-teams');
  if (allTeamsToggle) {
    allTeamsToggle.addEventListener('change', function () {
      var single = document.getElementById('poll-single-channel');
      if (single) single.classList.toggle('hidden', this.checked);
    });
  }

  // Populate Discord channel pickers from the live (Pub League) channel list.
  (function loadChannelPickers() {
    var pickers = document.querySelectorAll('select[data-channel-picker]');
    if (!pickers.length) return;
    var saved = root.getAttribute('data-discord-channel') || '';
    fetch('/admin-panel/api/surveys/discord-channels')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var chans = (data && data.channels) || [];
        var opts = '<option value="">— Select a channel —</option>' +
          chans.map(function (c) {
            return '<option value="' + c.id + '">#' + c.name +
              (c.category ? ' (' + c.category + ')' : '') + '</option>';
          }).join('') +
          '<option value="__custom__">Custom channel ID…</option>';
        pickers.forEach(function (sel) {
          sel.innerHTML = opts;
          if (saved) sel.value = saved;
        });
      })
      .catch(function () {
        pickers.forEach(function (sel) {
          sel.innerHTML = '<option value="">— Select —</option><option value="__custom__">Custom channel ID…</option>';
        });
      });
  })();

  // Live email audience preview
  var emailSel = document.getElementById('email-audience');
  if (emailSel) {
    var preview = function () {
      post('/admin-panel/api/surveys/' + sid + '/preview-audience', { filter_criteria: emailFilter(emailSel.value) })
        .then(function (res) {
          var el = document.getElementById('email-preview');
          if (el && res.success) el.textContent = res.count + ' recipient' + (res.count === 1 ? '' : 's') + ' · ' + res.description;
        });
    };
    emailSel.addEventListener('change', preview);
    preview();
  }
})();
