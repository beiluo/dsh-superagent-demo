/* Bostar Pack — small, dependency-free interactions. */
(function () {
  "use strict";

  var header = document.querySelector("[data-header]");
  var nav = document.getElementById("site-nav");
  var navToggle = document.querySelector("[data-nav-toggle]");

  /* Sticky header state -------------------------------------------------- */
  function onScroll() {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 8);
  }
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  /* Mobile navigation ---------------------------------------------------- */
  function closeNav() {
    if (!nav || !navToggle) return;
    nav.classList.remove("is-open");
    navToggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("nav-open");
  }
  if (nav && navToggle) {
    navToggle.addEventListener("click", function () {
      var open = navToggle.getAttribute("aria-expanded") === "true";
      nav.classList.toggle("is-open", !open);
      navToggle.setAttribute("aria-expanded", String(!open));
      document.body.classList.toggle("nav-open", !open);
    });
    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) closeNav();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeNav();
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 860) closeNav();
    });
  }

  /* Product filtering ---------------------------------------------------- */
  var filters = document.querySelectorAll("[data-filter]");
  var cards = document.querySelectorAll("[data-industry]");
  var count = document.querySelector("[data-filter-count]");
  var empty = document.querySelector("[data-filter-empty]");

  function applyFilter(value) {
    var shown = 0;
    cards.forEach(function (card) {
      var industries = (card.getAttribute("data-industry") || "").split(" ");
      var match = value === "all" || industries.indexOf(value) !== -1;
      card.hidden = !match;
      if (match) shown += 1;
    });
    filters.forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-filter") === value));
    });
    if (count) {
      count.textContent = "Showing " + shown + (shown === 1 ? " machine" : " machines");
    }
    if (empty) empty.classList.toggle("is-visible", shown === 0);
  }

  if (filters.length && cards.length) {
    filters.forEach(function (button) {
      button.addEventListener("click", function () {
        applyFilter(button.getAttribute("data-filter"));
      });
    });
    applyFilter("all");
  }

  /* Scroll reveal -------------------------------------------------------- */
  var reveals = document.querySelectorAll(".reveal");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reveals.length) {
    if (reduceMotion || !("IntersectionObserver" in window)) {
      reveals.forEach(function (el) { el.classList.add("is-visible"); });
    } else {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
      reveals.forEach(function (el) { observer.observe(el); });
    }
  }

  /* Copy-to-clipboard for contact details ------------------------------- */
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var value = button.getAttribute("data-copy");
      var done = function () {
        var original = button.textContent;
        button.textContent = "Copied";
        window.setTimeout(function () { button.textContent = original; }, 1600);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(value).then(done).catch(function () {});
      } else {
        var field = document.createElement("textarea");
        field.value = value;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.appendChild(field);
        field.select();
        try { document.execCommand("copy"); done(); } catch (error) { /* ignore */ }
        document.body.removeChild(field);
      }
    });
  });

  /* Static inquiry form -> opens the visitor's email client -------------- */
  var form = document.getElementById("inquiry-form");
  if (form) {
    var status = document.getElementById("form-status");
    var params = new URLSearchParams(window.location.search);
    var preset = params.get("machine");
    var message = form.querySelector("#message");
    if (preset && message && !message.value) {
      message.value = "I am interested in: " + preset + "\n\n";
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!form.reportValidity()) return;
      var data = new FormData(form);
      var lines = [
        "Name: " + (data.get("name") || ""),
        "Company: " + (data.get("company") || ""),
        "Email: " + (data.get("email") || ""),
        "Country: " + (data.get("country") || ""),
        "Interested in: " + (data.get("machine") || ""),
        "",
        "Message:",
        data.get("message") || ""
      ];
      var subject = "Website inquiry — " + (data.get("machine") || "packaging machinery");
      var href = "mailto:bostarpack@163.com?subject=" + encodeURIComponent(subject) +
                 "&body=" + encodeURIComponent(lines.join("\n"));
      window.location.href = href;
      if (status) {
        status.hidden = false;
        status.textContent = "Opening your email app. If nothing happens, email bostarpack@163.com directly.";
      }
    });
  }

  /* Footer year ---------------------------------------------------------- */
  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });
})();
