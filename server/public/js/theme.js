try {
  var m = localStorage.getItem('xg-theme') || 'system';
  var d = m === 'dark' || (m === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = d ? 'dark' : 'light';
} catch (e) {
  document.documentElement.dataset.theme = 'light';
}
