/* Section toggle & progress bar navigation */

function toggleSection(header) {
  const section = header.closest('.demo-section');
  const wasCollapsed = section.classList.contains('collapsed');
  section.classList.toggle('collapsed');
  const id = section.id;
  document.querySelectorAll('.progress-seg').forEach(s => s.classList.remove('active'));
  if (!wasCollapsed) return;
  const sSeg = document.querySelector('.progress-seg[data-target="' + id + '"]');
  if (sSeg) sSeg.classList.add('active');
}

document.querySelectorAll('.progress-seg').forEach(el => {
  el.addEventListener('click', function() {
    const target = this.dataset.target;
    if (!target) return;
    const section = document.getElementById(target);
    if (!section) return;
    document.querySelectorAll('.demo-section').forEach(s => {
      if (s.id === target) s.classList.remove('collapsed');
      else s.classList.add('collapsed');
    });
    document.querySelectorAll('.progress-seg').forEach(s => s.classList.remove('active'));
    const sSeg = document.querySelector('.progress-seg[data-target="' + target + '"]');
    if (sSeg) sSeg.classList.add('active');
    setTimeout(() => section.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  });
});
