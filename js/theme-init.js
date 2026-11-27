// Apply the saved theme before the page paints (localStorage, else the OS preference)
(function () {
    var theme = localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    if (theme === 'dark') document.documentElement.classList.add('dark');
})();
