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
$s.TargetPath       = (Get-Command uv).Source
$s.Arguments        = 'run --no-sync pythonw -m whisper_dictate.gui'
$s.WorkingDirectory = $repo
$s.Description      = 'whisper-dictate'
$s.Save()
```

Then sign out and back in to prove it. The pill should appear; no console
window, no main window.

## Why each part

- **`pythonw`** rather than `python`: no console window. A console would sit in
  the taskbar for the life of the session and close the app if dismissed.
- **`--no-sync`**: `uv run` normally checks and updates the environment first,
  which adds seconds to every login and can fail if the network is down. The
  environment is already correct; just use it.
- **Working directory is the repo**: `uv run` finds the project from the working
  directory, not from the script path.

## Removing it

Delete the shortcut:

```powershell
Remove-Item ([Environment]::GetFolderPath('Startup') + '\whisper-dictate.lnk')
```

Or use Task Manager → Startup apps to disable it without deleting it.

## What you should see

- A small pill, by default near the bottom-right. Drag it anywhere; double-click
  resets it. Its position is remembered.
- **Right-click the pill** for Show window, Cleanup settings and Quit. With the
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
- **`uv` is not on PATH for the login session.** `(Get-Command uv).Source` in
  the snippet above bakes in the full path, so re-run it rather than editing the
  shortcut by hand.
