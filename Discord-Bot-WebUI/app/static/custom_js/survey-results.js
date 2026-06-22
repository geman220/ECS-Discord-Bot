/* survey-results.js — render the survey results dashboard with Chart.js.
 *
 * Reads two embedded JSON blobs (#survey-summary, #survey-trend) and draws a
 * chart per question into the matching <canvas data-qindex>. Text and matrix
 * questions are rendered server-side and skipped here.
 */
(function () {
  'use strict';

  if (typeof window.Chart === 'undefined') return;

  var GREEN = '#1a472a';
  var PALETTE = ['#1a472a', '#2e7d4f', '#4caf7d', '#8bc7a8', '#c7a008',
                 '#e0b93d', '#3b6ea5', '#7b9cc4', '#9c4f4f', '#c98b8b'];

  function parse(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }

  function isDark() { return document.documentElement.classList.contains('dark'); }
  function gridColor() { return isDark() ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'; }
  function tickColor() { return isDark() ? '#a1a1aa' : '#6b7280'; }

  function baseOpts(extra) {
    var o = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: tickColor() } } },
    };
    return Object.assign(o, extra || {});
  }

  function makeChart(canvas, type, data, opts) {
    return new window.Chart(canvas.getContext('2d'), { type: type, data: data, options: opts });
  }

  function renderChoiceDoughnut(canvas, agg) {
    var labels = agg.counts.map(function (c) { return c.label; });
    var values = agg.counts.map(function (c) { return c.count; });
    makeChart(canvas, 'doughnut', {
      labels: labels,
      datasets: [{ data: values, backgroundColor: PALETTE, borderWidth: 0 }],
    }, baseOpts());
  }

  function renderBar(canvas, agg, valueKey) {
    valueKey = valueKey || 'count';
    var labels = agg.counts.map(function (c) { return c.label; });
    var values = agg.counts.map(function (c) { return c[valueKey]; });
    makeChart(canvas, 'bar', {
      labels: labels,
      datasets: [{ data: values, backgroundColor: GREEN, borderRadius: 4 }],
    }, baseOpts({
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: { beginAtZero: true, grid: { color: gridColor() }, ticks: { color: tickColor(), precision: 0 } },
        y: { grid: { display: false }, ticks: { color: tickColor() } },
      },
    }));
  }

  function renderNumericHistogram(canvas, agg) {
    var dist = agg.distribution || {};
    var labels = Object.keys(dist);
    var values = labels.map(function (k) { return dist[k]; });
    makeChart(canvas, 'bar', {
      labels: labels,
      datasets: [{ data: values, backgroundColor: GREEN, borderRadius: 4 }],
    }, baseOpts({
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: tickColor() } },
        y: { beginAtZero: true, grid: { color: gridColor() }, ticks: { color: tickColor(), precision: 0 } },
      },
    }));
  }

  function renderNps(canvas, agg) {
    var dist = agg.distribution || {};
    var det = 0, pas = 0, pro = 0;
    Object.keys(dist).forEach(function (k) {
      var v = parseFloat(k), n = dist[k];
      if (v <= 6) det += n; else if (v <= 8) pas += n; else pro += n;
    });
    makeChart(canvas, 'doughnut', {
      labels: ['Detractors (0-6)', 'Passives (7-8)', 'Promoters (9-10)'],
      datasets: [{ data: [det, pas, pro], backgroundColor: ['#c0392b', '#d4a017', GREEN], borderWidth: 0 }],
    }, baseOpts());
  }

  function renderQuestion(q, agg, canvas) {
    var t = q.question_type;
    if (t === 'single_choice' || t === 'dropdown' || t === 'yes_no') {
      renderChoiceDoughnut(canvas, agg);
    } else if (t === 'multi_choice') {
      renderBar(canvas, agg, 'count');
    } else if (t === 'ranking') {
      renderBar(canvas, agg, 'rank_score');
    } else if (t === 'nps') {
      renderNps(canvas, agg);
    } else if (t === 'rating' || t === 'scale' || t === 'number') {
      renderNumericHistogram(canvas, agg);
    }
  }

  function renderTrend(trend) {
    var canvas = document.getElementById('survey-trend-chart');
    if (!canvas || !trend || trend.length < 2) return;
    makeChart(canvas, 'line', {
      labels: trend.map(function (t) { return t.title; }),
      datasets: [{
        label: 'Completed responses',
        data: trend.map(function (t) { return t.completed; }),
        borderColor: GREEN, backgroundColor: 'rgba(26,71,42,0.1)',
        fill: true, tension: 0.3, pointRadius: 4,
      }],
    }, baseOpts({
      scales: {
        x: { grid: { display: false }, ticks: { color: tickColor() } },
        y: { beginAtZero: true, grid: { color: gridColor() }, ticks: { color: tickColor(), precision: 0 } },
      },
    }));
  }

  function csrf() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  }

  function wireContactButton() {
    var btn = document.getElementById('contact-respondents-btn');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var sid = btn.getAttribute('data-survey-id');
      window.Swal.fire({
        title: 'Email respondents',
        html:
          '<input id="cr-subject" class="swal2-input" placeholder="Subject">' +
          '<textarea id="cr-body" class="swal2-textarea" placeholder="Message (HTML allowed)"></textarea>',
        showCancelButton: true,
        confirmButtonText: 'Send',
        confirmButtonColor: '#1a472a',
        preConfirm: function () {
          var subject = document.getElementById('cr-subject').value.trim();
          var body = document.getElementById('cr-body').value.trim();
          if (!subject || !body) { window.Swal.showValidationMessage('Subject and message are required.'); return false; }
          return { subject: subject, body_html: body };
        },
      }).then(function (res) {
        if (!res.isConfirmed) return;
        fetch('/admin-panel/api/surveys/' + sid + '/contact', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
          body: JSON.stringify(res.value),
        }).then(function (r) { return r.json(); }).then(function (d) {
          if (d.success) window.Swal.fire('Sent', 'Queued ' + d.recipients + ' emails.', 'success');
          else window.Swal.fire('Error', d.error || 'Could not send', 'error');
        });
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    wireContactButton();
    var summary = parse('survey-summary');
    if (summary && summary.questions) {
      summary.questions.forEach(function (item, i) {
        var canvas = document.querySelector('canvas[data-qindex="' + i + '"]');
        if (canvas) {
          try { renderQuestion(item.question, item.aggregate, canvas); } catch (e) { /* skip */ }
        }
      });
    }
    renderTrend(parse('survey-trend'));
  });
})();
