# satellites-overhead — agent context

Hardware: HackRF One (serial 14d463dc2f209de1), V-dipole 54cm arms outdoor.
Location: Lafayette IN, 40.42°N 86.88°W, 180m alt.
OS: Kali Linux, bare-metal. Full sudo. `bypassPermissions` mode enabled.

## Services

```bash
systemctl --user status satellites-overhead.service   # web UI on :8723
systemctl --user status sdr-scheduler.service         # SDR scheduler
systemctl --user restart <service>
```

Both are enabled and should always be running. The scheduler is authoritative
for hardware. The web server and MCP enqueue work; they do not run HackRF or
satdump directly.

## File map

| File | Purpose |
|------|---------|
| `~/sdr_scheduler.py` | Live scheduler (the real one) |
| `scheduler/sdr_scheduler.py` | Repo backup — keep in sync with live |
| `~/sdr_scheduler_rules.json` | Recurring satellite rules |
| `~/sdr_scheduler_commands.json` | One-shot queue (scan-now etc.) |
| `~/sdr_scheduler_status.json` | Scheduler heartbeat + current job |
| `~/sdr_capture_history.json` | Capture history log |
| `~/sdr_scheduler.log` | Scheduler log |
| `serve.py` | Web server on :8723 |
| `scheduler_mcp.py` | MCP server (sdr-scheduler) |
| `monitor_capture.py` | Capture monitor/diagnostic script |
| `predict.py` | Headless pass predictor (uses PyEphem) |

After changing `scheduler/sdr_scheduler.py`, sync it:
```bash
cp scheduler/sdr_scheduler.py ~/sdr_scheduler.py
systemctl --user restart sdr-scheduler.service
```

## Current target: METEOR-M2 4 (NORAD 59051)

LRPT status page (check before every session):
`https://ub8qbd.satdump.org/wx_report_new.html`

As of June 3 2026:
- **M2-4 LRPT ON at 137.1 MHz** ← the target
- M2-3 LRPT OFF (beacon only 137.9 MHz)

Confirmed working gains (23 dB SNR, BER 0.000):
- LNA=16, VGA=36, amp=1 for passes < 60° elevation
- LNA=16, VGA=24, amp=1 for passes ≥ 60° elevation (auto-applied by scheduler)

Pipeline: `meteor_m2-x_lrpt`
Samplerate: `1e6` (pipeline expects 1 MSPS, not 2)
IQ swap: `True` (HackRF I/Q orientation; `--iq_swap` flag required)

The scheduler's `build_rule_jobs` applies VGA-12 automatically for ≥60° passes.
The `satdump_capture()` function defaults to `samplerate="1e6"` and `iq_swap=True`.

## Queuing a capture

Via MCP (preferred):
```
mcp: run_scheduler_rule_now(rule_id="sat-59051-meteor_lrpt_hackrf", confirm=True, duration_s=<N>)
```

Via web endpoint:
```bash
curl -s http://localhost:8723/scheduler/status   # check state first
# POST /scheduler/scan-now — see serve.py for payload shape
```

**Do not run satdump or hackrf_transfer directly.** Always enqueue through the
scheduler so the single-device lock is respected.

## Monitoring a capture — DO THIS EVERY TIME

When you queue a capture, immediately schedule a monitoring check for T+90s
using `ScheduleWakeup` (if the session will stay open) or `/schedule` (for
unattended operation). The monitor:

1. Reads the satdump log at `<capdir>.log`
2. Checks SNR, Viterbi BER, and Deframer SYNC status
3. Kills satdump and writes a diagnostic report if intervention is needed
4. Writes `<capdir>/diagnostic_report.md` (shown in the web UI capture list)

Run the monitor script directly:
```bash
python3 monitor_capture.py ~/noaa_captures/<capdir>
```

Or call it inside your monitoring loop — it exits 0 if healthy, 1 if it
intervened or found a problem, 2 if the log isn't there yet.

### Decision tree

| Condition | Action |
|-----------|--------|
| SNR > 10, BER < 0.05, Deframer SYNCED | Healthy — let it run, check at LOS |
| SNR > 10, BER ≈ 0, Deframer NOSYNC | Kill, retry with different pipeline/flags (see below) |
| SNR > 28, BER climbing | Saturated — kill, retry with amp=0 or VGA-12 |
| SNR < 5 | Signal too weak — check frequency, antenna, gains |

### NOSYNC troubleshooting order

The persistent `Viterbi SYNCED + BER 0.000 + Deframer NOSYNC` issue has been
seen on every capture so far. Root cause is OQPSK phase ambiguity or IQ swap.
Try in this order, killing and requeuing after ~60s of NOSYNC with good SNR:

1. `--iq_swap --samplerate 1e6 --pipeline meteor_m2-x_lrpt` (current default)
2. No `--iq_swap`, `--samplerate 1e6`
3. `--iq_swap`, `--samplerate 2e6`
4. Pipeline `meteor_m2_lrpt` (older QPSK decoder, different decode chain)

SatDump v1.2.3 is installed. The pre-1.0 Viterbi padding bug is not present.
The CCSDS ASM (0x1ACFFC1D) repeats every frame — NOSYNC is not caused by
joining mid-pass. It is a pipeline configuration issue.

## Scheduler known bugs / quirks

**Fire-time boundary bug (FIXED June 3 2026):** `job_fire_dt("HH:MM")` used to
wrap to the next day if a poll landed at exactly `HH:MM:00.xxx`. Fixed with a
90-second grace window. If a pass is missed, check whether the scheduler log
shows `Next: <satellite> at HH:MM (in 0s)` followed by a jump to the next pass
without a `Running:` line — that's the symptom.

**Completed set is in-memory:** The scheduler's `completed` set is reset on
restart. Restarting the scheduler will re-evaluate all jobs including ones that
already fired this session. Avoid restarting unnecessarily during a pass window.

## Web endpoints

```
GET  /scheduler/status          — scheduler heartbeat + queue count
GET  /scheduler/rules           — list rules
POST /scheduler/rules           — create/update rule
DEL  /scheduler/rules/<id>      — delete rule
POST /scheduler/scan-now        — enqueue immediate capture
GET  /captures?norad=NNN        — capture history for a satellite
GET  /captures/<id>/report      — diagnostic report (markdown)
GET  /captures/<id>/download    — tar.gz of output directory or IQ file
GET  /capture-settings?norad=N  — suggested frequency/gain from SatNOGS
GET  /passes?...                — upcoming pass predictions
```

## Verification after code changes

```bash
python3 -m py_compile serve.py scheduler_mcp.py scheduler/sdr_scheduler.py ~/sdr_scheduler.py monitor_capture.py

node - <<'NODE'
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
for (const src of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Function(src[1]);
console.log('inline scripts ok');
NODE

curl -fsS http://localhost:8723/scheduler/status
curl -fsS 'http://localhost:8723/capture-settings?norad=59051'
curl -fsS 'http://localhost:8723/captures?norad=59051'
```

## Rollback

Each major change is committed. To undo: `git revert <commit>` or
`git checkout <commit> -- <file>`. See `SDR_MANAGER_HANDOFF.md` for manual
rollback instructions for the queue/status architecture.

Do not commit `.tlecache/active.tle` — it is updated at runtime by CelesTrak
fetches and is intentionally gitignored.
