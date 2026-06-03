# SDR Manager handoff - June 3 2026

This note covers the current web-app/scheduler/MCP integration work so another
agent can continue or undo it.

## Current intent

- The web app is a controller/viewer, not the hardware runner.
- The Python scheduler owns hardware execution.
- The scheduler runs one capture at a time for the current single-device setup.
- Multiple devices should be added later by adding device ids and per-device
  locks to the command/status records.

## New scheduler files

Runtime files in the user's home directory:

- `~/sdr_scheduler_rules.json` - persistent recurring satellite rules.
- `~/sdr_scheduler_commands.json` - queued one-shot commands such as
  `scan_now`.
- `~/sdr_scheduler_status.json` - scheduler heartbeat and live/idle state.
- `~/sdr_scheduler.log` - scheduler log.

The web server and MCP write commands. The scheduler polls and consumes them.
The web server and MCP read status. The scheduler writes status.

## Queue contract

`scan_now` command shape:

```json
{
  "id": "scan-59051-1780490000",
  "type": "scan_now",
  "queued_at": "2026-06-03T09:00:00Z",
  "name": "METEOR-M2 4",
  "norad": 59051,
  "group": "radio",
  "profile": "meteor_lrpt_hackrf",
  "frequency_hz": 137100000,
  "lna_gain": 16,
  "vga_gain": 24,
  "amp": 1,
  "duration_s": 300,
  "source": "web"
}
```

The scheduler removes the command when it starts running it. Since the scheduler
loop blocks while `satdump` or `hackrf_transfer` runs, no second capture can
start until the first capture finishes.

## Status contract

`~/sdr_scheduler_status.json` shape:

```json
{
  "state": "idle",
  "live": false,
  "pid": 1234,
  "updated_at": "2026-06-03T09:00:00Z",
  "current_job": null,
  "message": "next capture pending"
}
```

When running, `state` is `running`, `live` is true, and `current_job` includes
label, output path, frequency, duration, gains, amp, and command id if it came
from the queue. Idle heartbeat is updated roughly every 30 seconds.

## Web endpoints

- `GET /scheduler/status` reads scheduler status and queue count.
- `POST /scheduler/scan-now` validates an overhead target, calls the same
  capture-settings lookup as Track, applies the high-elevation VGA reduction,
  and queues a `scan_now` command.
- `GET /capture-settings?norad=NNN&band=vdipole` suggests frequency/profile/gain
  from SatNOGS transmitters. If `band` is omitted, band priority is
  `vdipole`, `amateur`, `lband`, `adsb`.

## UI changes

- The upcoming-pass `pass band` select filters visible rows only.
- The separate `capture band` select controls new rule/scan capture settings.
  `Auto` lets `/capture-settings` choose from SatNOGS transmitter records.
- `Track` flow:
  `capture-settings -> populate fields -> if pass.maxEl >= 60 reduce VGA by 12 -> save rule`.
- Overhead rows now include `Scan now`, which queues a 300 second immediate
  scheduler command. It does not launch hardware from the web process.
- Scheduler rules section shows live/idle/stale status from
  `/scheduler/status`.

## Files changed

- `index.html`
- `serve.py`
- `scheduler_mcp.py`
- `scheduler/sdr_scheduler.py`
- `/home/cstahly/sdr_scheduler.py`
- `README.md`
- `SDR_MANAGER_HANDOFF.md`

Runtime-generated cache file `.tlecache/active.tle` may be dirty from CelesTrak
refreshes and should not be committed as part of this change.

## Services

User services should be active:

```bash
systemctl --user status satellites-overhead.service
systemctl --user status sdr-scheduler.service
```

After code changes:

```bash
systemctl --user restart satellites-overhead.service
systemctl --user restart sdr-scheduler.service
```

## Verification commands

```bash
python3 -m py_compile serve.py scheduler_mcp.py scheduler/sdr_scheduler.py ~/sdr_scheduler.py
node - <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
for (const src of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Function(src[1]);
console.log('inline scripts ok');
NODE
curl -fsS http://localhost:8723/scheduler/status
curl -fsS 'http://localhost:8723/capture-settings?norad=59051'
```

Do not test `POST /scheduler/scan-now` casually unless you are ready for the
scheduler to start HackRF/SatDump.

## Rollback

To undo this change from git once committed, revert the commit(s) that mention
scan-now/status/capture-band separation. If manual rollback is needed:

1. Remove `/scheduler/status` and `/scheduler/scan-now` from `serve.py`.
2. Remove `COMMANDS_PATH`, `STATUS_PATH`, queue helpers, `command_jobs`, and
   `write_scheduler_status` from both scheduler copies.
3. Restore MCP `run_scheduler_rule_now` only if direct process launch is desired;
   otherwise keep it queue-based.
4. Remove `Scan now`, scheduler status UI, and `captureBand` state from
   `index.html`.
5. Restart both user services.

