window.AI_Guide = window.AI_Guide || { open: function () {
  const modal = document.getElementById('ai-modal');
  const overlay = document.getElementById('ai-overlay');
  if (modal && overlay) { modal.classList.add('active'); overlay.classList.add('active'); modal.querySelector('input')?.focus(); }
} };
window.AI_Matchmaker = window.AI_Matchmaker || { open: function () {
  const modal = document.getElementById('mm-modal');
  const overlay = document.getElementById('mm-overlay');
  if (modal && overlay) { modal.classList.add('active'); overlay.classList.add('active'); }
} };
