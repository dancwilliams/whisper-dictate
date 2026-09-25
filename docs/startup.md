# Starting whisper-dictate at login

The app is meant to be always there: you hold the chord, speak, and the text
lands. That only works if it is already running, so put a shortcut in the
Startup folder.

## Create the shortcut

Run this once in PowerShell, from anywhere. Adjust `$repo` if your clone is
somewhere else.

```powershell
$repo = "$HOME\git\whisper-dictate"
$lnk  = [Environment]::GetFolderPath('Startup') + '\whisper-dictate.lnk'
$s    = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath       = "$repo\.venv\Scripts\pythonw.exe"
$s.Arguments        = '-m whisper_dictate.gui'
$s.WorkingDirectory = $repo
$s.Description      = 'whisper-dictate'
$s.Save()
```

Then sign out and back in to prove it. The pill should appear; no console
window, no main window.

## Why each part

- **`pythonw.exe` from the venv**, not `uv run`: `uv.exe` is a console program,
  so Windows opens a console for it and keeps it there for as long as the app
  runs — running `pythonw` *through* `uv` does not help, because the console
  belongs to `uv`, not to Python. `pythonw.exe` is a GUI-subsystem binary, so no
  console is ever created. Going straight to the venv also skips `uv run`'s
  environment check, which adds seconds to every login and can fail if the
  network is down.
- **Working directory is the repo**: not needed to find the interpreter, but the
  app resolves project-relative paths from it.

## Removing it

Delete the shortcut:

```powershell
Remove-Item ([Environment]::GetFolderPath('Startup') + '\whisper-dictate.lnk')
```

Or use Task Manager → Startup apps to disable it without deleting it.

## What you should see

- A small pill, by default near the bottom-right. Drag it anywhere; double-click
  resets it. Its position is remembered.
- **Right-click the pill** for Show window, Fix last dictation, Cleanup settings
  and Quit. With the
  main window hidden this menu is the only way into the app, and Quit is the
  only way out — closing the main window just hides it again.
- Exactly one instance. Launching a second time does nothing: the app takes a
  named mutex at startup and a second copy exits immediately, because two
  keyboard hooks would mean two pastes per dictation.

## If nothing appears

`~\.whisper_dictate\logs\whisper_dictate.log` gets a line for every state
change. A login-time failure will be at the top of the newest run. Common
causes:

- **Auto-load is off.** The window only hides itself when both "Auto-load model
  on startup" and "Auto-register hotkey after model loads" are on, in
  Settings → Automation. With either off, the app starts with its window
  visible so you have something to click.
- **The venv moved or was rebuilt elsewhere.** The shortcut names
  `.venv\Scripts\pythonw.exe` by absolute path, so re-run the snippet after
  moving the clone rather than editing the shortcut by hand.
