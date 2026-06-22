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
      p = post('/admin-panel/api/surveys/' + sid + '/send/discord-embed',
               { channel_id: document.getElementById('embed-channel').value.trim() })
        .then(function (res) { done(res, 'Embed posted'); });
    } else if (channel === 'native-poll') {
      p = post('/admin-panel/api/surveys/' + sid + '/send/native-poll',
               { channel_id: document.getElementById('poll-channel').value.trim(),
                 duration_hours: parseInt(document.getElementById('poll-duration').value, 10) || 48 })
        .then(function (res) { done(res, 'Poll posted'); });
    }
    if (p) p.finally(function () { send.disabled = false; });
  });

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
