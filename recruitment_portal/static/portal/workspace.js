(() => {
  const toggle = document.querySelector('.rp-nav-toggle');
  if (!toggle) return;
  const close = () => { document.body.classList.remove('rp-nav-open'); toggle.setAttribute('aria-expanded', 'false'); };
  toggle.addEventListener('click', () => {
    const opened = document.body.classList.toggle('rp-nav-open');
    toggle.setAttribute('aria-expanded', String(opened));
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  document.addEventListener('click', event => {
    if (!event.target.closest('#sidebar') && !event.target.closest('.rp-nav-toggle')) close();
  });
})();
