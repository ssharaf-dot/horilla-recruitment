/* Accessible navigation for compact recruitment workspaces. */
document.querySelectorAll('.wx-menu-toggle').forEach(function (button) {
  var sidebar = button.closest('.wx-sidebar');
  function setOpen(open) {
    button.setAttribute('aria-expanded', String(open));
    sidebar.classList.toggle('wx-nav-open', open);
  }
  button.addEventListener('click', function () {
    setOpen(button.getAttribute('aria-expanded') !== 'true');
  });
  sidebar.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { setOpen(false); button.focus(); }
  });
});

/* Keep the selected phase visible inside the compact horizontal navigation. */
document.querySelectorAll('.wx-phase-nav').forEach(function (nav) {
  function revealPhase() {
    var current = nav.querySelector('[aria-current="page"]');
    if (current && nav.scrollWidth > nav.clientWidth) {
      nav.scrollLeft = Math.max(0, current.offsetLeft - nav.offsetLeft - 16);
    }
  }
  revealPhase();
  window.addEventListener('resize', revealPhase);
});
document.querySelectorAll('.wx-tools').forEach(function (details) {
  details.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { details.open = false; details.querySelector('summary').focus(); }
  });
  document.addEventListener('click', function (event) {
    if (!details.contains(event.target)) details.open = false;
  });
});
