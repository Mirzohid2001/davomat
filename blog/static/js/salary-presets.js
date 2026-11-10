/**
 * Saqlangan oylik filtrlari — Mening ko'rinishim (localStorage).
 */
(function () {
  'use strict';
  var KEY = 'davomat.salary.myView';

  function currentQuery() {
    return window.location.search.replace(/^\?/, '');
  }

  function activateChips() {
    var qs = currentQuery();
    document.querySelectorAll('[data-preset]').forEach(function (el) {
      var want = el.getAttribute('data-preset-qs') || '';
      var active = false;
      if (el.dataset.preset === 'my') {
        var saved = localStorage.getItem(KEY) || '';
        active = saved && saved === qs;
      } else if (el.dataset.preset === 'debtors') {
        active = /(?:^|&)debtors=1(?:&|$)/.test(qs);
      } else if (want) {
        active = qs === want || qs.indexOf(want) === 0;
      }
      el.classList.toggle('is-active', active);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var saveBtn = document.querySelector('[data-preset-save]');
    if (saveBtn) {
      saveBtn.addEventListener('click', function () {
        localStorage.setItem(KEY, currentQuery());
        saveBtn.classList.add('is-saved');
        saveBtn.textContent = saveBtn.dataset.savedLabel || 'Saqlandi';
        activateChips();
        setTimeout(function () {
          saveBtn.classList.remove('is-saved');
          saveBtn.textContent = saveBtn.dataset.label || 'Saqlash';
        }, 1400);
      });
    }
    var myBtn = document.querySelector('[data-preset="my"]');
    if (myBtn) {
      myBtn.addEventListener('click', function (e) {
        var saved = localStorage.getItem(KEY);
        if (!saved) {
          e.preventDefault();
          window.alert(myBtn.dataset.emptyMsg || 'Avval joriy filterni saqlang.');
          return;
        }
        myBtn.setAttribute('href', '?' + saved);
      });
    }
    activateChips();
  });
})();
