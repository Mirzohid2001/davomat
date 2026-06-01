/**
 * Scroll-reveal va raqam hisoblagich (app-page)
 */
(function () {
  'use strict';

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.querySelectorAll('.app-reveal-on-scroll').forEach(function (el) {
      el.classList.add('is-visible');
    });
    return;
  }

  /* Jadval qatorlari animatsiyasi */
  document.querySelectorAll('.app-page .app-panel').forEach(function (panel) {
    panel.classList.add('app-panel-animated');
  });

  /* Intersection Observer — scroll paytida */
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.06, rootMargin: '0px 0px -32px 0px' }
    );

    document.querySelectorAll('.app-reveal-on-scroll').forEach(function (el) {
      observer.observe(el);
    });

    document.querySelectorAll('.stats-page .stats-chart-card').forEach(function (el) {
      el.classList.add('app-reveal-on-scroll');
      observer.observe(el);
    });
  } else {
    document.querySelectorAll('.app-reveal-on-scroll').forEach(function (el) {
      el.classList.add('is-visible');
    });
  }

  /* Dashboard raqamlar — yumshoq count-up */
  function animateValue(el, end, duration) {
    var start = 0;
    var startTime = null;
    end = parseInt(end, 10);
    if (isNaN(end)) return;

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.floor(eased * (end - start) + start);
      if (progress < 1) {
        window.requestAnimationFrame(step);
      } else {
        el.textContent = end;
      }
    }
    window.requestAnimationFrame(step);
  }

  document.querySelectorAll('.app-stat-number[data-count]').forEach(function (el, i) {
    var target = el.getAttribute('data-count') || el.textContent.trim();
    setTimeout(function () {
      animateValue(el, target, 700);
    }, 200 + i * 80);
  });

  document.querySelectorAll('.app-stat-number:not([data-count])').forEach(function (el, i) {
    var text = el.textContent.trim();
    if (/^\d+$/.test(text)) {
      el.setAttribute('data-count', text);
      el.textContent = '0';
      setTimeout(function () {
        animateValue(el, text, 700);
      }, 200 + i * 80);
    }
  });
})();
