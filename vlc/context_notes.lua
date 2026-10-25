--[[
  Context Notes for VLC (alpha)
  ---------------------------------
  When a video starts, looks for "<video name>.notes.ass" next to it and loads
  it as a subtitle track, keeping only the kinds of notes you've switched on
  (British English, IT in-jokes, visual gags, ...).

  Install (macOS): copy this file to
      ~/Library/Application Support/org.videolan.vlc/lua/extensions/
  then restart VLC and choose VLC > Extensions > Context Notes.
  The extension stays on until you quit VLC; turn it on again after a restart.

  The .notes.ass file is made by make_ass.py. Each note carries its tags in the
  ASS "Name" field as  kind/category/confidence  e.g.  visual/prop/medium
  The file also plays fine without this extension (everything shown).
]]

local NOTES_SUFFIX = ".notes.ass"

-- Topic checkboxes, and the note categories each one covers.
local TOPICS = {
  { key = "british",   label = "Language, slang & wordplay",
    cats = { "british english", "british slang", "idiom", "wordplay", "archaic word",
             "translation", "register", "slang", "dialect" } },
  { key = "bawdy",     label = "Bawdy jokes",            cats = { "bawdy" } },
  { key = "culture",   label = "History & culture",      cats = { "cultural reference", "historical context" } },
  { key = "it",        label = "IT in-jokes",            cats = { "it in-joke" } },
  { key = "character", label = "Character & delivery",   cats = { "character", "delivery", "theme" } },
  { key = "gags",      label = "Running gags & payoffs", cats = { "running gag", "setup", "payoff" } },
  { key = "sight",     label = "Sight gags, staging & on-screen text",
    cats = { "visual gag", "staging", "on-screen text" } },
  { key = "set",       label = "Props, sets & costume", cats = { "prop", "background", "costume" } },
  { key = "trivia",    label = "Trivia & play-vs-film",  cats = { "trivia", "about these notes", "adaptation" } },
}

local OPTIONS = {
  { key = "speech",     label = "Notes about what's said (left)",      default = true },
  { key = "visual",     label = "Notes about what's on screen (right)", default = true },
  { key = "less_sure",  label = "Include notes marked (less sure)",    default = true },
  { key = "one_column", label = "Put every note in one column (left)", default = false },
  { key = "dialogue",   label = "Show the dialogue subtitles",         default = true },
}

local settings = {}      -- key -> boolean
local widgets = {}       -- key -> checkbox
local dlg, status_label
local last_uri           -- video we last loaded notes for
local temp_counter = 0
local last_temp

---------------------------------------------------------------- descriptor
function descriptor()
  return {
    title = "Context Notes",
    version = "0.2.4",
    author = "Great Scott CS + Claude",
    shortdesc = "Context Notes",
    description = "Loads <video>.notes.ass and lets you choose which kinds of "
               .. "context notes (British English, IT jokes, visual gags...) to show.",
    capabilities = { "menu", "input-listener" },
  }
end

local function log(msg) vlc.msg.info("[Context Notes] " .. msg) end

---------------------------------------------------------------- file helpers
local function open_file(path, mode)
  if vlc.io and vlc.io.open then return vlc.io.open(path, mode) end
  return io.open(path, mode)
end

local function read_all(path)
  local f = open_file(path, "rb")
  if not f then return nil end
  local data = f:read("*a")
  f:close()
  return data
end

local function write_all(path, data)
  local f = open_file(path, "wb")
  if not f then return false end
  f:write(data)
  f:close()
  return true
end

local function file_exists(path)
  local f = open_file(path, "rb")
  if f then f:close() return true end
  return false
end

local function list_dir(dir)
  local ok, entries = pcall(function()
    if vlc.io and vlc.io.readdir then return vlc.io.readdir(dir) end
    return vlc.net.opendir(dir)
  end)
  if ok and type(entries) == "table" then return entries end
  return {}
end

local function ends_with(s, suffix)
  return suffix == "" or s:sub(-#suffix) == suffix
end

---------------------------------------------------------------- settings
local function settings_path()
  return vlc.config.userdatadir() .. "/context-notes-settings.txt"
end

local function load_settings()
  for _, t in ipairs(TOPICS) do settings[t.key] = true end
  for _, o in ipairs(OPTIONS) do settings[o.key] = o.default end
  local data = read_all(settings_path())
  if not data then return end
  for key, value in data:gmatch("([%w_]+)=(%a+)") do
    if settings[key] ~= nil then settings[key] = (value == "true") end
  end
end

local function save_settings()
  local lines = {}
  for key, value in pairs(settings) do
    lines[#lines + 1] = key .. "=" .. tostring(value)
  end
  table.sort(lines)
  write_all(settings_path(), table.concat(lines, "\n") .. "\n")
end

local function read_widgets()
  for key, w in pairs(widgets) do settings[key] = w:get_checked() end
end

---------------------------------------------------------------- filtering
-- NOTE: VLC 3 scans extensions with Lua's standard library switched off, so
-- nothing may run at load time except plain assignments and function
-- definitions. This table is therefore built on first use, not at load.
local CAT_TO_TOPIC

local function cat_to_topic()
  if not CAT_TO_TOPIC then
    CAT_TO_TOPIC = {}
    for _, t in ipairs(TOPICS) do
      for _, c in ipairs(t.cats) do CAT_TO_TOPIC[c] = t.key end
    end
  end
  return CAT_TO_TOPIC
end

-- Should a note tagged "kind/category/confidence" be shown?
local function keep_note(tag, opts)
  local kind, cat, conf = tag:match("^([^/]*)/([^/]*)/([^/]*)$")
  if not kind then return true end                    -- untagged: always show
  if kind == "visual" then
    if not opts.visual then return false end
  elseif not opts.speech then
    return false
  end
  if (conf == "medium" or conf == "low") and not opts.less_sure then return false end
  local topic = cat_to_topic()[cat]
  if topic and not opts[topic] then return false end  -- unknown categories stay on
  return true
end

-- Returns the filtered ASS text plus how many notes were kept / found.
function filter_ass(text, opts)
  local out, kept, total = {}, 0, 0
  for line in (text .. "\n"):gmatch("([^\n]*)\n") do
    line = line:gsub("\r$", "")
    local layer, s, e, style, name, rest =
      line:match("^Dialogue:%s*([^,]*),([^,]*),([^,]*),([^,]*),([^,]*),(.*)$")
    if not layer then
      out[#out + 1] = line                            -- header, styles, comments
    elseif style == "Dialogue" then
      if opts.dialogue then out[#out + 1] = line end
    else
      total = total + 1
      if keep_note(name, opts) then
        kept = kept + 1
        if opts.one_column and style == "NoteR" then style = "NoteL" end
        out[#out + 1] = "Dialogue: " .. layer .. "," .. s .. "," .. e .. "," ..
                        style .. "," .. name .. "," .. rest
      end
    end
  end
  return table.concat(out, "\n"), kept, total
end

---------------------------------------------------------------- finding notes
local function current_video_path()
  local item = vlc.input.item()
  if not item then return nil end
  local uri = item:uri()
  if not uri or not uri:match("^file://") then return nil, uri end
  local path = vlc.strings.make_path and vlc.strings.make_path(uri)
  if not path then
    path = (vlc.strings.decode_uri(uri):gsub("^file://", ""))
  end
  return path, uri
end

local function find_notes_file(video_path)
  local base = video_path:match("^(.*)%.[^./\\]+$") or video_path
  local candidate = base .. NOTES_SUFFIX
  if file_exists(candidate) then return candidate end
  -- fall back to the only *.notes.ass in the same folder, if there is one
  local dir = video_path:match("^(.*)[/\\]") or "."
  local found
  for _, name in ipairs(list_dir(dir)) do
    if ends_with(name, NOTES_SUFFIX) then
      if found then return nil end                    -- ambiguous
      found = dir .. "/" .. name
    end
  end
  return found
end

local function set_status(text)
  log(text)
  if status_label then status_label:set_text(text) end
end

---------------------------------------------------------------- loading
function load_for_current(force)
  local video, uri = current_video_path()
  if not video then
    set_status("Nothing playing (or not a local file).")
    return
  end
  if uri == last_uri and not force then return end
  last_uri = uri

  local notes_path = find_notes_file(video)
  if not notes_path then
    set_status("No notes for this video. Looking for: "
               .. ((video:match("([^/\\]+)$") or video):gsub("%.[^.]+$", "")) .. NOTES_SUFFIX)
    return
  end
  local text = read_all(notes_path)
  if not text then
    set_status("Couldn't read " .. notes_path)
    return
  end

  local filtered, kept, total = filter_ass(text, settings)
  local dir = vlc.config.userdatadir() .. "/context-notes"
  pcall(vlc.io.mkdir, dir, "0700")
  temp_counter = temp_counter + 1
  local temp = dir .. "/current-" .. temp_counter .. ".ass"
  if not write_all(temp, filtered) then
    set_status("Couldn't write " .. temp)
    return
  end
  if last_temp and vlc.io and vlc.io.unlink then pcall(vlc.io.unlink, last_temp) end
  last_temp = temp

  vlc.input.add_subtitle(temp, true)
  set_status(string.format("Showing %d of %d notes from %s", kept, total,
                           notes_path:match("([^/\\]+)$") or notes_path))
end

---------------------------------------------------------------- dialog
local function apply_clicked()
  read_widgets()
  save_settings()
  load_for_current(true)
end

local function show_dialog()
  if dlg then dlg:show() return end
  dlg = vlc.dialog("Context Notes")
  widgets = {}
  local row = 1
  dlg:add_label("SHOW", 1, row, 2, 1); row = row + 1
  for i = 1, 2 do
    local o = OPTIONS[i]
    widgets[o.key] = dlg:add_check_box(o.label, settings[o.key], 1, row, 2, 1); row = row + 1
  end
  dlg:add_label("TOPICS", 1, row, 2, 1); row = row + 1
  for i, t in ipairs(TOPICS) do
    local col = (i % 2 == 1) and 1 or 2
    widgets[t.key] = dlg:add_check_box(t.label, settings[t.key], col, row, 1, 1)
    if col == 2 then row = row + 1 end
  end
  if #TOPICS % 2 == 1 then row = row + 1 end
  dlg:add_label("OPTIONS", 1, row, 2, 1); row = row + 1
  for i = 3, #OPTIONS do
    local o = OPTIONS[i]
    widgets[o.key] = dlg:add_check_box(o.label, settings[o.key], 1, row, 2, 1); row = row + 1
  end
  dlg:add_button("Apply to this video", apply_clicked, 1, row, 1, 1)
  dlg:add_button("Hide", function() dlg:hide() end, 2, row, 1, 1); row = row + 1
  status_label = dlg:add_label("", 1, row, 2, 1)
  dlg:show()
end

---------------------------------------------------------------- VLC callbacks
function activate()
  load_settings()
  show_dialog()
  if vlc.input.item() then load_for_current(true) end
end

function deactivate()
  if dlg then dlg:delete() end
  dlg, status_label, widgets = nil, nil, {}
end

-- Closing the window just hides it, so notes keep loading for the next video.
function close()
  if dlg then dlg:hide() end
end

function menu()
  return { "Settings..." }
end

function trigger_menu(id)
  show_dialog()
end

function input_changed()
  load_for_current(false)
end
