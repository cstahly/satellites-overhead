# Desktop sat-pass tools

Surface upcoming satellite passes on the desktop, fed by the SDR scheduler's own
predictor so they match what the scheduler will actually capture.

## Data producer — `sat_passes_json.py`
Reads enabled `satellite_*` rules from `~/sdr_scheduler_rules.json`, predicts the
next passes for each NORAD via `~/src/satellites-overhead/predict.py`
(observer 40.42, -86.88, 180 m), merges/sorts them, and writes
`~/.local/share/sat-passes/passes.json`. Refreshed every 10 min by the systemd
user timer **`sat-passes.timer`** (`~/.config/systemd/user/sat-passes.{service,timer}`).

## GNOME top-bar extension — `sat-passes@cstahly/`
GNOME Shell 45+ (ESM). Adds a top-bar indicator showing the **next pass + a live
countdown** (`🛰 M2-4 54° 5:48`); click it for a dropdown of the next 12 passes.
Reads `passes.json` (ticks every 1 s, re-reads every 2 min).

Deployed at `~/.local/share/gnome-shell/extensions/sat-passes@cstahly` (a symlink
to this dir). Enable: `gnome-extensions enable sat-passes@cstahly`.
**Wayland caveat:** a running gnome-shell only discovers a *new* extension at
login — so after first install you must **log out / back in**. It's pre-enabled in
dconf (`org.gnome.shell enabled-extensions`) so it auto-loads then.

## Floating widget — `sat_widget.py` (alternative)
Standalone Tkinter always-on-top window, same data but computed live. Run
`python3 ~/sat_widget.py`. On GNOME/Wayland it must be launched from inside the
session (needs `DISPLAY=:0` + the `/run/user/<uid>/.mutter-Xwaylandauth.*` cookie,
not `~/.Xauthority`).

## Notes
- `~/sat_passes_json.py`, `~/sat_widget.py`, and the live extension dir are
  **symlinks into this repo** — edit here, changes are live (extension needs a
  relog to reload).
- Capture gain is 30: daytime in-band 60 Hz RFI overloads the RTL ADC (~3% clipping)
  at gain 40. See `project_rfi_60hz` notes.
