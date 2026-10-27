// ---------------------------------------------------------------- embed (embed.py)
const sizeText = (n) => n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.round(n / 1e3)} KB`;
const minsText = (s) => s < 60 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;
function embedTarget() {
  return { path: $("path").value.trim(), recursive: $("recursive").checked, convert: $("embedConvert").checked };
}
