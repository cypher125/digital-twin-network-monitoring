// Applies a saved light/dark choice before the first paint, so the page never flashes.
try {
  var theme = localStorage.getItem("dt-theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch (e) {
  // storage blocked: follow the operating system
}
