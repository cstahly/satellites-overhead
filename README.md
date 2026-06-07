# Satellites Overhead

Real-time satellite tracker, pass predictor, SDR capture scheduler, and MCP
server for AI agents. Built around a single V-dipole + RTL-SDR v3 setup
receiving METEOR LRPT weather imagery, but the web UI and scheduler support
both RTL-SDR and HackRF One and are hardware-agnostic at the rule level.

---

## What's in here

| File | Purpose |
|------|---------|
| `index.html` | Full frontend: sky plot, overhead list, pass prediction, scheduler rules UI |
| `serve.py` | Web server + TLE proxy + scheduler API on port 8723 |
| `predict.py` | Headless pass predictor (PyEphem, used by scheduler and `/passes` endpoint) |
| `scheduler_mcp.py` | Stdio MCP server exposing all scheduler/prediction tools to AI agents |
| `scheduler/sdr_scheduler.py` | SDR pass scheduler (symlinked from `~/sdr_scheduler.py`) |
| `monitor_capture.py` | Capture monitor: parses satdump logs, kills bad runs, writes diagnostic reports |
| `sat_iq_summary.py` | Post-process raw IQ captures: FM demod, burst detection, Whisper transcription, Claude narrative |
| `satdump_pass_summary.py` | Post-decode summary for satdump captures: reads log, extracts metrics, calls Claude |
| `schedule_windows.py` | Utility: list upcoming pass windows across all enabled rules |
| `sdr-cli/` | Rust CLI (`sdr`): dashboard showing current job, last capture, and upcoming passes |
| `CLAUDE.md` | Full context file for AI agents working in this repo |
| `systemd/` | Systemd user service unit files |
| `.tlecache/` | TLE disk cache (auto-created, safe to delete) |
| `.txcache/` | SatNOGS transmitter cache (auto-created) |
| `.satcache/` | SatNOGS satellite metadata cache (auto-created) |

---

## Requirements

- Python 3.9+
- `ephem` (PyEphem) — `pip install ephem` or your distro package
- `rtl-sdr` — `sudo apt install rtl-sdr` — provides `rtl_sdr` for IQ capture
- `satdump` — for LRPT image decoding (offline decode pipeline)
- `hackrf_transfer` — optional, HackRF IQ capture only
- Rust toolchain — `curl https://sh.rustup.rs | sh` — for `sdr-cli`
- `faster-whisper` — `pip install faster-whisper` — for `sat_iq_summary.py` voice transcription
- Internet access — CelesTrak TLEs, SatNOGS DB

---

## Installation

### 1. Clone and set up

```bash
git clone <repo> /home/<user>/src/satellites-overhead
cd /home/<user>/src/satellites-overhead
```

### 2. Python dependencies

The web server and predictor use only stdlib + ephem:

```bash
pip install ephem
# or: sudo apt install python3-ephem
```

The MCP server needs its own venv (to isolate the `mcp` package):

```bash
python3 -m venv .venv-mcp
.venv-mcp/bin/pip install mcp ephem
```

### 3. Build the `sdr` CLI

```bash
cd sdr-cli
cargo build --release
sudo cp target/release/sdr /usr/local/bin/sdr
```

### 4. Symlink the live scheduler

The scheduler runs from `~/sdr_scheduler.py` so systemd can find it. Symlink
it to the source-controlled copy so edits and git history stay in one place:

```bash
ln -sf /home/<user>/src/satellites-overhead/scheduler/sdr_scheduler.py \
       ~/sdr_scheduler.py
```

### 5. Configure your location

Edit `scheduler/sdr_scheduler.py` and update:

```python
LAT = 40.42    # degrees north
LON = -86.88   # degrees east (negative = west)
ALT_M = 180    # meters above sea level
```

These are also used by the MCP server via `predict.py`.

### 6. Systemd user services

```bash
mkdir -p ~/.config/systemd/user
cp systemd/satellites-overhead.service ~/.config/systemd/user/
cp systemd/sdr-scheduler.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now satellites-overhead.service sdr-scheduler.service
```

Enable lingering so services start on boot without a login session:

```bash
loginctl enable-linger <user>
```

Check status:

```bash
systemctl --user status satellites-overhead.service
systemctl --user status sdr-scheduler.service
```

### 7. MCP server registration (Codex / Claude Code)

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.sdr-scheduler]
command = "/home/<user>/src/satellites-overhead/.venv-mcp/bin/python"
args = ["-u", "/home/<user>/src/satellites-overhead/scheduler_mcp.py"]
```

---

## Running without systemd

```bash
# Web server
python3 serve.py             # port 8723
python3 serve.py 8080        # custom port

# Scheduler (foreground)
python3 ~/sdr_scheduler.py

# MCP server (stdio, normally launched by the agent host)
.venv-mcp/bin/python scheduler_mcp.py
```

---

## Web UI

Open `http://localhost:8723`. On the same LAN, browse to `http://<host-ip>:8723`
from a phone — geolocation requires HTTPS on mobile, so grant it manually or use
the coordinate inputs.

**Overhead now** — satellites above your horizon at this moment, updated every 3
seconds. Click a row to open satellite details (SatNOGS image, metadata,
transmitters, pass info, and capture history). Overhead rows with a scheduled
rule show a **Scan now** button.

**Predict passes** — scans the next N hours for upcoming passes above a minimum
elevation. Filter by name/NORAD or equipment band (V-dipole VHF, amateur,
L-band, ADS-B). Click a row to open details. Click **Track** to create a
recurring scheduler rule for that satellite.

**Scheduler rules** — live view of all rules. Edit gains, frequency, minimum
elevation, and enabled state inline. Click **Engaged** to remove a rule.

**Captures** — the satellite details popup includes a history of all past
captures for that satellite: timestamp, profile, duration, size, CADU bytes, and
links to download the output or view the diagnostic report.

---

## SDR Scheduler

The scheduler (`scheduler/sdr_scheduler.py`) is a single Python process that:

1. Loads recurring satellite rules from `~/sdr_scheduler_rules.json`
2. Predicts upcoming passes using `predict.py` (re-runs every 60 s)
3. Fires captures at the right time (30 s before AOS by default)
4. Polls `~/sdr_scheduler_commands.json` for immediate scan-now commands
5. Runs one capture at a time (single-device model)
6. Writes status to `~/sdr_scheduler_status.json` every 30 s
7. Appends a record to `~/sdr_capture_history.json` after every job
8. Spawns a monitoring thread 90 s into every satdump capture

### Runtime files

| File | Written by | Read by |
|------|-----------|---------|
| `~/sdr_scheduler_rules.json` | Web UI / MCP | Scheduler |
| `~/sdr_scheduler_commands.json` | Web UI / MCP | Scheduler |
| `~/sdr_scheduler_status.json` | Scheduler | Web UI / MCP |
| `~/sdr_capture_history.json` | Scheduler | Web UI |
| `~/sdr_scheduler.log` | Scheduler | You / monitor |
| `~/sdr_scheduler_events.jsonl` | Scheduler / Web API | Mobile API |
| `~/sdr_notification_outbox.jsonl` | Scheduler / Web API | Future push worker |
| `~/sdr_api_tokens.json` | Token CLI / Web API | Web API |
| `~/sdr_mobile_devices.json` | Mobile API | Future push worker |

### Rule fields

```json
{
  "id": "sat-59051-meteor_lrpt_rtlsdr",
  "enabled": true,
  "type": "satellite_recurring",
  "name": "METEOR-M2 4",
  "norad": 59051,
  "group": "radio",
  "frequency_hz": 137100000,
  "profile": "meteor_lrpt_rtlsdr",
  "lna_gain": 40,
  "vga_gain": 36,
  "amp": 0,
  "min_peak_el": 20,
  "start_offset_s": -30,
  "end_offset_s": 60,
  "samplerate": "2e6",
  "iq_swap": true,
  "pipeline": "meteor_m2-x_lrpt"
}
```

Profiles ending in `_rtlsdr` use `rtl_sdr` for capture; `_hackrf` use
`hackrf_transfer`. `lna_gain` is repurposed as the single RTL-SDR gain knob
when using an RTL-SDR profile. `start_offset_s` is applied before AOS
(negative = start early). `end_offset_s` is added after predicted LOS. For
passes ≥ 60° elevation the scheduler automatically reduces VGA by 12 dB to
avoid ADC saturation.

### Scan-now command queue

The web server and MCP write commands to `~/sdr_scheduler_commands.json`. The
scheduler removes a command when it starts executing it. Neither the web server
nor the MCP ever runs HackRF or satdump directly.

### Capture monitoring and auto-retry

Every satdump capture spawns a background monitoring thread that wakes at T+90 s
and runs `monitor_capture.py`. The monitor reads the satdump log and classifies
signal state:

| Status | Action |
|--------|--------|
| Deframer SYNCED | Healthy — let it run |
| NOSYNC with good SNR | Kill, queue retry with next variant |
| ADC saturation | Kill, queue retry with reduced gains |
| All retry variants exhausted | Spawn `claude --print -p ...` for diagnosis |
| Novel/unknown failure | Spawn Claude immediately |

The retry sequence for LRPT NOSYNC (tries in order):

1. `--iq_swap --samplerate 2e6 --dc_block` pipeline `meteor_m2-x_lrpt` (default)
2. no `--iq_swap`, `--samplerate 2e6 --dc_block`
3. `--iq_swap --samplerate 1e6 --dc_block`
4. `--samplerate 2e6 --dc_block` pipeline `meteor_m2_lrpt` (older decoder)

Each capture produces a `<capdir>/diagnostic_report.md` viewable from the web UI.

### Pass manager (Claude at AOS)

For LRPT captures the scheduler spawns a Claude pass manager subprocess at AOS.
The pass manager monitors satdump output in real time, classifies sync state,
kills bad runs, injects retry variants, and writes a final pass report. The lock
file `~/sdr_scheduler.lock` prevents the background monitoring thread from
conflicting with a running pass manager.

---

## `sdr` CLI

The `sdr` command (built from `sdr-cli/`) provides a quick terminal dashboard:

```
sdr              # NOW / LAST / next 10 upcoming passes
sdr -c 20        # show 20 upcoming passes
sdr passes       # upcoming passes only
sdr rules        # list scheduler rules
sdr status       # raw scheduler status JSON
```

**NOW** shows the running job (satellite, elevation, time remaining) or "idle".
**LAST** shows the most recent completed capture (satellite, duration, size).
Upcoming passes are sorted by AOS across all enabled rules in a 48-hour window.

---

## Pass post-processing

### `sat_iq_summary.py` — FM/SSB IQ analysis

Processes raw CU8 IQ captures from `raw_iq_rtlsdr` rules (SO-50, AO-73, linear
transponder birds):

```bash
python3 sat_iq_summary.py <capdir.iq> [--force-summary]
```

1. FM demodulates the IQ file
2. Detects activity bursts (10th-percentile noise floor, 3× threshold)
3. Transcribes voice bursts with Whisper (CPU-only, `base.en` model)
4. Calls Claude to produce a narrative pass summary

Skips the Claude call if no bursts are detected (no activity = nothing to
summarise). Use `--force-summary` to override.

**Gain/noise reference:**

| Bird type | Typical noise RMS | Notes |
|-----------|-------------------|-------|
| FM (no carrier) | ~6500 | AGC-normalized noise hash — correct, not a failure |
| FM (carrier present) | ~200–400 | FM quieting when satellite is transmitting |
| SSB/linear transponder | ~74 | Different demod path, different scale |

### `satdump_pass_summary.py` — LRPT decode summary

Generates a Claude narrative for a completed satdump decode:

```bash
python3 satdump_pass_summary.py <capdir>
```

Reads the satdump `.log` file, extracts Viterbi SNR, lock percentage, frame
counts, and image file list, then calls Claude for a one-paragraph summary.
Useful for automated post-pass reporting from the scheduler pipeline.

---

## API endpoints

All endpoints are served by `serve.py` on port 8723. Existing paths remain
supported. New clients should use the equivalent `/api/v1/...` paths listed by
`GET /api/v1`. Every `/api/v1` request requires a revocable bearer token;
legacy browser routes do not. Create and revoke tokens locally with
`manage_api_tokens.py`.

### Scheduler

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/scheduler/status` | Scheduler heartbeat, current job, queue count |
| `GET` | `/scheduler/rules` | List all rules |
| `POST` | `/scheduler/rules` | Create or update a rule |
| `DELETE` | `/scheduler/rules/<id>` | Delete a rule |
| `POST` | `/scheduler/scan-now` | Queue an immediate capture |
| `GET` | `/api/v1/audit?limit=100` | Recent rule/scan mutation audit records |
| `GET` | `/api/v1/events?after=ID&limit=100` | Append-only scheduler/web event stream |
| `GET` | `/api/v1/notifications?status=pending` | Pending notification outbox |
| `GET/POST/DELETE` | `/api/v1/devices[/<id>]` | Mobile push-device registry |
| `GET/POST/DELETE` | `/api/v1/tokens[/<id>]` | Revocable bearer-token management |

### Captures

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/captures?norad=NNN` | Capture history for a satellite (all if no norad) |
| `GET` | `/captures/<id>/report` | Diagnostic report markdown |
| `GET` | `/captures/<id>/download` | Output directory as `.tar.gz` or raw IQ file |

### Satellites / TLEs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tle?group=NAME` | Cached TLE data from CelesTrak |
| `GET` | `/passes?lat=&lon=&...` | Pass predictions (see below) |
| `GET` | `/capture-settings?norad=NNN` | Suggested frequency/gain from SatNOGS |
| `GET` | `/transmitters?norad=NNN` | SatNOGS transmitter records |
| `GET` | `/satellite?norad=NNN` | SatNOGS satellite metadata |

`/passes` parameters: `group`, `lat` (required), `lon` (required), `alt_m`,
`hours`, `min_el`, `min_duration_s`, `track_step_s`, `limit`, `start`, `norad`
(repeatable), `name` (repeatable).

Public website access at `https://sdr.sadbabyrabbit.com` is protected by nginx
Basic Auth. The `/api/v1` subtree instead uses application bearer auth so native
mobile clients do not store the website password. Mutating requests are
recorded in `~/sdr_web_audit.jsonl`; scheduler and web lifecycle events are
recorded in `~/sdr_scheduler_events.jsonl`. See `MOBILE_API_HANDOFF.md` and
`HOSTING_RUNBOOK.md` for deployment and rollback details.

---

## MCP server

`scheduler_mcp.py` exposes all scheduler and prediction functionality to AI
agents via the Model Context Protocol (stdio transport).

### Tools

| Tool | Description |
|------|-------------|
| `get_scheduler_status` | Scheduler heartbeat, paths, log tail |
| `list_scheduler_rules` | All SDR scheduler rules |
| `get_scheduler_rule` | Single rule by id |
| `add_satellite_rule` | Create a recurring satellite rule |
| `update_scheduler_rule` | Update rule fields |
| `enable_scheduler_rule` | Enable a rule |
| `disable_scheduler_rule` | Disable a rule |
| `delete_scheduler_rule` | Delete a rule |
| `list_upcoming_scheduler_runs` | Jobs the scheduler will fire in the next N hours |
| `dry_run_scheduler_rule` | Preview jobs a rule would generate without saving |
| `run_scheduler_rule_now` | Queue an immediate capture (`confirm=true` required) |
| `predict_satellite_passes` | Predict passes for any NORAD ID(s) |
| `list_overhead_now` | Satellites above the horizon right now |
| `list_radio_targets` | Common radio/weather targets from the TLE catalog |
| `suggest_capture_settings` | Recommended frequency/gains from SatNOGS transmitters |
| `get_satellite_details` | SatNOGS satellite metadata |
| `list_satellite_transmitters` | SatNOGS transmitter records |

### Important: hardware safety

`run_scheduler_rule_now` queues a command through
`~/sdr_scheduler_commands.json`. The MCP server never runs HackRF or satdump
directly. The scheduler enforces one active capture at a time.

---

## Headless pass prediction

```bash
python3 predict.py \
  --lat 40.42 --lon -86.88 --alt-m 180 \
  --hours 24 --min-el 10 \
  --norad 59051 \
  --track-step-s 60 \
  --limit 4
```

Output is a JSON array of pass objects with `norad`, `name`, `aos`, `los`,
`max_t`, `max_el`, `max_az`, `aos_az`, `los_az`, `duration_s`, and a `track`
array of `{t, az, el, range, range_rate}` samples.

---

## Monitor script

```bash
python3 monitor_capture.py ~/noaa_captures/<capdir>
# --check-only  : analyse and report without killing anything
```

Reads `<capdir>.log`, classifies signal state, optionally kills satdump, and
writes `<capdir>/diagnostic_report.md`. Exits 0 if healthy, 1 if it intervened
or found a problem, 2 if the log isn't there yet. JSON summary printed to stdout
for programmatic use.

---

## Data sources

- **TLEs**: CelesTrak GP data, cached 2 h per group. Do not fetch directly from
  the browser — the proxy exists to avoid CelesTrak's HTTP 403 rate limit.
- **Satellite metadata / transmitters**: SatNOGS DB API, cached 7 days.
- **LRPT status** (Meteor satellites): check before each session —
  `https://ub8qbd.satdump.org/wx_report_new.html`

---

## After code changes

```bash
# Syntax check everything
python3 -m py_compile serve.py scheduler_mcp.py scheduler/sdr_scheduler.py monitor_capture.py

# Check inline JS
node - <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
for (const src of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Function(src[1]);
console.log('ok');
NODE

# Rebuild sdr CLI after Rust changes
cd sdr-cli && cargo build --release && sudo cp target/release/sdr /usr/local/bin/sdr && cd ..

# Restart services
systemctl --user restart satellites-overhead.service sdr-scheduler.service

# Verify
curl -fsS http://localhost:8723/scheduler/status
curl -fsS 'http://localhost:8723/captures?norad=59051'
```
