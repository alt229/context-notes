// ---------------------------------------------------------------- VLC and folders
async function openVlc(v) {
  const r = await api("/api/vlc/open", { path: v.path });
  if (!r.ok) note("left", "VLC", r.message || r.error || "Couldn't open VLC.");
  else if (info && !info.vlc.some((x) => x.installed)) note("left", "VLC", "Opening it in VLC. To see the notes there, install the VLC extension in Settings.");
}
async function reveal(v) {
  const r = await api("/api/reveal", { path: v.path });
  if (!r.ok) note("left", "Folder", r.message || r.error || "Couldn't open the folder.");
}

