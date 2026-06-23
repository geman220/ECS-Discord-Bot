/* surveys-list.js — duplicate / delete actions on the Surveys & Polls list. */
(function () {
  'use strict';

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  }

  function api(url, method) {
    return fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
    }).then(function (r) { return r.json(); });
  }

  function duplicate(id) {
    api('/admin-panel/api/surveys/' + id + '/duplicate', 'POST').then(function (data) {
      if (data.success) {
        window.location.href = data.redirect || window.location.href;
      } else {
        window.Swal.fire('Error', data.error || 'Could not duplicate survey', 'error');
      }
    });
  }

  function useTemplate(id) {
    api('/admin-panel/api/surveys/' + id + '/use-template', 'POST').then(function (data) {
      if (data.success) {
        window.location.href = data.redirect || window.location.href;
      } else {
        window.Swal.fire('Error', data.error || 'Could not create survey from template', 'error');
      }
    });
  }

  function del(id, title) {
    window.Swal.fire({
      title: 'Delete survey?',
      html: 'This permanently deletes <strong>' + (title || 'this survey') +
            '</strong> and all of its responses. This cannot be undone.',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#dc2626',
      confirmButtonText: 'Delete',
    }).then(function (res) {
      if (!res.isConfirmed) return;
      api('/admin-panel/api/surveys/' + id, 'DELETE').then(function (data) {
        if (data.success) {
          window.location.reload();
        } else {
          window.Swal.fire('Error', data.error || 'Could not delete survey', 'error');
        }
      });
    });
  }

  document.addEventListener('click', function (e) {
    // Templates dropdown toggle (close when clicking elsewhere).
    var toggle = e.target.closest('[data-action="toggle-template-menu"]');
    var dd = document.getElementById('template-dropdown');
    if (toggle) { if (dd) dd.classList.toggle('hidden'); return; }
    if (dd && !e.target.closest('#template-menu')) dd.classList.add('hidden');

    var btn = e.target.closest('[data-survey-action]');
    if (!btn) return;
    var action = btn.getAttribute('data-survey-action');
    var id = btn.getAttribute('data-survey-id');
    if (action === 'duplicate') duplicate(id);
    else if (action === 'use') useTemplate(id);
    else if (action === 'delete') del(id, btn.getAttribute('data-survey-title'));
  });
})();
