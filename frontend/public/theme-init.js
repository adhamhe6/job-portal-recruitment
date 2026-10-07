// Runs synchronously from <head>: sets the theme class before first paint so there is no flash.
// Keep in sync with src/lib/theme.ts (storage key + semantics: 'light' | 'dark' | 'system').
;(function () {
  try {
    var pref = localStorage.getItem('talentlens.theme')
    var dark =
      pref === 'dark' ||
      ((pref === null || pref === 'system') && window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  } catch (e) {
    /* storage blocked: fall back to the light theme */
  }
})()
