/**
 * Tezkor davomat statusi — modal siz, bitta bosish.
 */
(function () {
  'use strict';

  function csrfToken() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el && el.value) return el.value;
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
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
    root.querySelectorAll('.qs-btn').forEach(function (btn) {
      btn.disabled = !!busy;
    });
  }

  function applyStatus(root, status, label, attendanceId) {
    root.dataset.status = status || '';
    if (attendanceId) root.dataset.attendanceId = String(attendanceId);
    root.querySelectorAll('.qs-btn').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.status === status);
    });
    var badge = root.querySelector('[data-qs-label]');
    if (badge && label) {
      badge.textContent = label;
      badge.className = badge.className.replace(/attlist-status--\w+/g, '');
      badge.classList.add('attlist-status--' + status);
    }
    var card = root.closest('[data-floor-row]');
    if (card) {
      card.dataset.status = status || '';
      card.classList.toggle('is-done', !!status);
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
    var btn = e.target.closest('.qs-btn');
    if (!btn) return;
    var root = btn.closest('[data-quick-status]');
    if (!root) return;
    e.preventDefault();
    if (root.classList.contains('is-busy')) return;
    postStatus(root, btn.dataset.status);
  });
})();
