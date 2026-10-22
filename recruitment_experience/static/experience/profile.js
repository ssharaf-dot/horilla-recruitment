/* Copy selected, escaped CV text into an editable draft; saving remains explicit. */
document.querySelectorAll('[data-profile-target]').forEach(function (button) {
  button.addEventListener('click', function () {
    var target = document.getElementById(button.dataset.profileTarget);
    var source = button.parentElement.querySelector('template');
    if (!target || !source) return;
    target.value = source.content.textContent;
    target.dispatchEvent(new Event('input', {bubbles:true}));
    button.textContent = 'Added to draft · review before saving';
    target.focus();
  });
});
