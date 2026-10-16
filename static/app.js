// AI News — 前端交互
(function() {
  // 暗色/亮色切换
  var saved = localStorage.getItem('ai-news-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  else if (window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.setAttribute('data-theme', 'dark');

  window.toggleTheme = function() {
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? '' : 'dark';
    if (next) document.documentElement.setAttribute('data-theme', next);
    else document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('ai-news-theme', next);
    var btn = document.querySelector('.theme-toggle');
    if (btn) btn.textContent = next === 'dark' ? '☀' : '🌙';
  };

  // 初始化按钮文本
  document.addEventListener('DOMContentLoaded', function() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    var btn = document.querySelector('.theme-toggle');
    if (btn) btn.textContent = isDark ? '☀' : '🌙';
  });
})();
