// AI_Guide chatbot removed: the canonical chatbot embed
// (assets/js/chatbot-embed.js) now defines window.AI_Guide itself.
window.AI_Matchmaker = window.AI_Matchmaker || { open: function () {
  const modal = document.getElementById('mm-modal');
  const overlay = document.getElementById('mm-overlay');
  if (modal && overlay) { modal.classList.add('active'); overlay.classList.add('active'); }
} };
