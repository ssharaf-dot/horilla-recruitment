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
