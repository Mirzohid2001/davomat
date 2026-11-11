/**
 * Tezkor davomat statusi — asosiy 3 + Yana dropdown, modal siz.
 */
(function () {
  'use strict';

  var MORE = { vacation: true, business: true, offday: true };

  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function closeAllMenus(except) {
    document.querySelectorAll('.qs-more.is-open').forEach(function (box) {
      if (except && box === except) return;
      box.classList.remove('is-open');
      var toggle = box.querySelector('.qs-more__toggle');
      var menu = box.querySelector('.qs-more__menu');
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
      if (menu) menu.hidden = true;
    });
  }

  function syncSiblingRoots(root, status, label, attendanceId) {
    var empId = root.dataset.employeeId;
    if (!empId) return;
    document.querySelectorAll('[data-quick-status][data-employee-id="' + empId + '"]').forEach(function (other) {
      if (other === root) return;
      if (other.dataset.date && root.dataset.date && other.dataset.date !== root.dataset.date) return;
      applyStatus(other, status, label, attendanceId);
    });
  }

  function setBusy(root, busy) {
    root.classList.toggle('is-busy', !!busy);
    root.querySelectorAll('.qs-btn, .qs-more__toggle').forEach(function (btn) {
      btn.disabled = !!busy;
    });
  }

  function applyStatus(root, status, label, attendanceId) {
    root.dataset.status = status || '';
    if (attendanceId) root.dataset.attendanceId = String(attendanceId);
    root.querySelectorAll('.qs-btn').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.status === status);
    });

    var more = root.querySelector('.qs-more');
    if (more) {
      var isMore = !!(status && MORE[status]);
      more.classList.toggle('is-active-more', isMore);
      var moreLabel = more.querySelector('.qs-more__label');
      if (moreLabel) {
        moreLabel.textContent = isMore && label
          ? label
          : (moreLabel.getAttribute('data-default-yana') || 'Yana');
      }
      more.classList.remove('is-open');
      var menu = more.querySelector('.qs-more__menu');
      var toggle = more.querySelector('.qs-more__toggle');
      if (menu) menu.hidden = true;
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
    }

    var card = root.closest('[data-floor-row]');
    var badge = root.querySelector('[data-qs-label]') || (card && card.querySelector('[data-qs-label]'));
    if (badge && label) {
      badge.hidden = false;
      badge.removeAttribute('hidden');
      badge.textContent = label;
      badge.className = 'attlist-status attlist-status--' + status;
    }
    if (card) {
      card.dataset.status = status || '';
      card.classList.toggle('is-done', !!status);
      card.classList.toggle('is-pending', !status);
      var tag = card.querySelector('.attlist-pending-tag');
      if (tag) tag.style.display = status ? 'none' : '';
    }
  }

  async function postStatus(root, status) {
    var url = root.dataset.url;
    if (!url) return;
    var body = new URLSearchParams();
    body.set('status', status);
    if (root.dataset.attendanceId) body.set('attendance_id', root.dataset.attendanceId);
    if (root.dataset.employeeId) body.set('employee_id', root.dataset.employeeId);
    if (root.dataset.date) body.set('date', root.dataset.date);

    setBusy(root, true);
    try {
      var res = await fetch(url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken(),
          'X-Requested-With': 'XMLHttpRequest',
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: body.toString(),
        credentials: 'same-origin',
      });
      var data = await res.json();
      if (!data.success) {
        window.alert(data.message || 'Xato');
        return;
      }
      applyStatus(root, data.status, data.status_label, data.attendance_id);
      syncSiblingRoots(root, data.status, data.status_label, data.attendance_id);
      root.classList.add('is-flash');
      setTimeout(function () { root.classList.remove('is-flash'); }, 450);
    } catch (err) {
      window.alert('Tarmoq xatosi');
    } finally {
      setBusy(root, false);
    }
  }

  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('.qs-more__toggle');
    if (toggle) {
      e.preventDefault();
      e.stopPropagation();
      var box = toggle.closest('.qs-more');
      var menu = box && box.querySelector('.qs-more__menu');
      if (!box || !menu) return;
      var willOpen = !box.classList.contains('is-open');
      closeAllMenus(box);
      box.classList.toggle('is-open', willOpen);
      toggle.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      menu.hidden = !willOpen;
      if (willOpen) {
        // Joy yetmasa pastga, aks holda yuqoriga (jadval kesmasin)
        menu.classList.remove('is-drop-down');
        var rect = toggle.getBoundingClientRect();
        var spaceAbove = rect.top;
        var spaceBelow = window.innerHeight - rect.bottom;
        if (spaceAbove < 160 && spaceBelow > spaceAbove) {
          menu.classList.add('is-drop-down');
        }
      }
      return;
    }

    var btn = e.target.closest('.qs-btn');
    if (btn) {
      var root = btn.closest('[data-quick-status]');
      if (!root) return;
      e.preventDefault();
      if (root.classList.contains('is-busy')) return;
      postStatus(root, btn.dataset.status);
      return;
    }

    if (!e.target.closest('.qs-more')) {
      closeAllMenus();
    }
  });

})();
