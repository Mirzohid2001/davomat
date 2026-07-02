/**
 * Mobil UX: menyu yopish, jadval scroll ko'rsatkichi
 */
(function () {
  'use strict';

  function closeNavbarOnNavigate() {
    var collapse = document.getElementById('navbarNav');
    if (!collapse || !window.bootstrap) return;
    collapse.querySelectorAll('.nav-link:not(.dropdown-toggle), .dropdown-item').forEach(function (link) {
      link.addEventListener('click', function () {
        if (window.innerWidth < 992 && collapse.classList.contains('show')) {
          var instance = bootstrap.Collapse.getInstance(collapse);
          if (instance) instance.hide();
        }
      });
    });
  }

  function setupTableScrollHints() {
    document.querySelectorAll('main .table-responsive').forEach(function (wrap) {
      if (wrap.closest('.salary-table-section')) return;
      if (wrap.dataset.scrollHint === '1') return;
      wrap.dataset.scrollHint = '1';

      var hint = document.createElement('div');
      hint.className = 'app-table-scroll-hint';
      hint.setAttribute('aria-hidden', 'true');
      hint.innerHTML = '<i class="bi bi-arrows-expand"></i> Jadvalni gorizontal suring';
      wrap.insertAdjacentElement('afterend', hint);

      function update() {
        var scrollable = wrap.scrollWidth > wrap.clientWidth + 2;
        wrap.classList.toggle('is-scrollable', scrollable);
        hint.style.display = scrollable && window.innerWidth < 768 ? 'flex' : 'none';
      }

      update();
      wrap.addEventListener('scroll', update, { passive: true });
      window.addEventListener('resize', update, { passive: true });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      closeNavbarOnNavigate();
      setupTableScrollHints();
    });
  } else {
    closeNavbarOnNavigate();
    setupTableScrollHints();
  }
})();
