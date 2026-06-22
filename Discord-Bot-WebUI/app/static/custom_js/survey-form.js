/* survey-form.js — live branching (show/hide) on the public survey form.
 *
 * A question wrapper with data-showif-q / data-showif-eq is shown only when the
 * controlling question's current value equals the expected value. Hidden
 * questions get their inputs disabled so the browser won't block submission on
 * a hidden "required" field (the server applies the same visibility rule).
 */
(function () {
  'use strict';

  var form = document.querySelector('form[action*="/s/"]');
  if (!form) return;

  var conditional = Array.prototype.slice.call(form.querySelectorAll('.survey-q[data-showif-q]'));
  if (!conditional.length) return;

  // Current value(s) for question q_<id>: radio/select scalar, checkboxes array.
  function currentValue(qid) {
    var checks = form.querySelectorAll('input[type="checkbox"][name="q_' + qid + '"]');
    if (checks.length) {
      return Array.prototype.filter.call(checks, function (c) { return c.checked; })
        .map(function (c) { return c.value; });
    }
    var radios = form.querySelectorAll('input[type="radio"][name="q_' + qid + '"]');
    if (radios.length) {
      var picked = Array.prototype.filter.call(radios, function (r) { return r.checked; })[0];
      return picked ? picked.value : '';
    }
    var field = form.querySelector('[name="q_' + qid + '"]');
    return field ? field.value : '';
  }

  function matches(actual, expected) {
    if (Array.isArray(actual)) return actual.indexOf(expected) !== -1;
    return String(actual) === String(expected);
  }

  function apply() {
    conditional.forEach(function (wrap) {
      var ctrl = wrap.getAttribute('data-showif-q');
      var eq = wrap.getAttribute('data-showif-eq');
      var visible = matches(currentValue(ctrl), eq);
      wrap.classList.toggle('hidden', !visible);
      // Disable inputs while hidden so required + values don't submit.
      wrap.querySelectorAll('input, select, textarea').forEach(function (el) {
        el.disabled = !visible;
      });
    });
  }

  form.addEventListener('change', apply);
  apply();
})();
