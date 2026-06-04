# satellites-overhead — agent context

Hardware: HackRF One (serial 14d463dc2f209de1), V-dipole 54cm arms outdoor.
Location: Lafayette IN, 40.42°N 86.88°W, 180m alt.
OS: Kali Linux, bare-metal. Full sudo. `bypassPermissions` mode enabled.

## Services

```bash
# Scheduler runs directly (not via systemd):
ps aux | grep sdr_scheduler         # find PID
kill <PID> && python3 ~/src/satellites-overhead/scheduler/sdr_scheduler.py &

# MCP server:
ps aux | grep scheduler_mcp
kill <PID> && python3 ~/src/satellites-overhead/scheduler_mcp.py &

# Web UI on :8723:
ps aux | grep serve.py
```

The scheduler is authoritative for hardware. The web server and MCP enqueue
work; they do not run HackRF or satdump directly.

## File map

| File | Purpose |
|------|---------|
| `scheduler/sdr_scheduler.py` | Live scheduler (symlinked from `~/sdr_scheduler.py`) |
| `~/sdr_scheduler_rules.json` | Recurring satellite rules |
| `~/sdr_scheduler_commands.json` | One-shot queue (scan-now etc.) |
| `~/sdr_scheduler_status.json` | Scheduler heartbeat + current job |
| `~/sdr_capture_history.json` | Capture history log |
| `~/sdr_scheduler.log` | Scheduler log |
| `serve.py` | Web server on :8723 |
| `scheduler_mcp.py` | MCP server (sdr-scheduler) |
| `monitor_capture.py` | Capture monitor/diagnostic script |
| `predict.py` | Headless pass predictor (uses PyEphem) |
| `satdump_pipelines/` | Custom satdump pipelines (copy to /usr/share/satdump/pipelines/) |

After changing `scheduler/sdr_scheduler.py`:
- No copy needed — `~/sdr_scheduler.py` is a symlink to the repo file
- Restart: `kill <PID> && python3 ~/src/satellites-overhead/scheduler/sdr_scheduler.py &`

## CRITICAL: HackRF LO false-lock (discovered June 4 2026)

**The HackRF LO leakage creates a DC spike at the tuned frequency in baseband.**
Without `--dc_block`, the OQPSK PLL locks onto this spike instead of the
satellite signal, producing fake "Viterbi SYNCED BER 0.000 Deframer NOSYNC"
at ~27 dB SNR on EVERY capture regardless of pipeline or gains.

**Every M2-4 capture before June 4 was a false lock.** The "confirmed working
23 dB SNR" previously documented here was the LO spike, not a satellite signal.

Fix: `--dc_block` is now passed to all satdump captures by default.
With dc_block active, noise floor correctly shows SNR=0, Viterbi NOSYNC,
BER≈0.41. A real satellite signal will appear as SNR > 0 above this floor.

## Current target: METEOR-M2 4 (NORAD 59051)

LRPT status: check `https://ub8qbd.satdump.org/wx_report_new.html` before acting.
Last verified ON: June 3 2026. As of June 4 morning: **STATUS UNKNOWN** — two
passes (03:59 26.6°, 05:39 38°) showed SNR=0 throughout with dc_block active.
The signal may be absent (satellite transmitter off?) or genuinely too weak.

**No real M2-4 LRPT lock has ever been achieved on this setup.**

### Current pipeline config (as of June 4 2026)

```
Frequency:  137.1 MHz
Pipeline:   meteor_m2-4_lrpt_nrzl  (NRZ-L hypothesis — front-loaded)
Samplerate: 1,000,000 (integer — satdump rejects "1e6" string)
IQ swap:    True
dc_block:   True  (REQUIRED — see above)
LNA=16, VGA=36, amp=1 for passes < 60°
LNA=16, VGA=24, amp=1 for passes ≥ 60° (auto-applied by scheduler)
```

### LRPT_RETRY_VARIANTS order (by P(success))

When Deframer NOSYNC at T+90s, monitor kills satdump and retries:
1. `nrzl + iq_swap=True + dc_block=True`  ← initial capture uses this
2. `nrzl + iq_swap=False + dc_block=True`
3. `nrzl_nors + iq_swap=True + dc_block=True`  (RS disabled — diagnostic)
4. `m2-x_lrpt + iq_swap=True + dc_block=True`  (NRZ-M, known NOSYNC)
5. `m2-x_lrpt + iq_swap=False + dc_block=True`
6. `m2-x_lrpt + iq_swap=True + dc_block=False`  (last resort — false-locks)

Custom pipelines `meteor_m2-4_lrpt_nrzl` and `meteor_m2-4_lrpt_nrzl_nors`
are in `/usr/share/satdump/pipelines/Meteor-M2-4-custom.json`.

### What a real lock looks like (expected, not yet seen)

```
SNR > 5–15 dB (above 0.000 baseline)
Viterbi: SYNCED  BER: 0.05–0.15 (not 0.000 — that's the false lock)
Deframer: SYNCED
CADU file growing (check with: wc -c <capdir>/*.cadu)
```

### Decision tree

| Condition | Action |
|-----------|--------|
| SNR > 5, BER 0.05–0.15, Deframer SYNCED | Real lock — let it run |
| SNR > 5, BER ≈ 0.000, Deframer NOSYNC | LO false-lock — add/check dc_block |
| SNR = 0, BER ≈ 0.41–0.43 | Correct noise floor with dc_block — no signal yet |
| SNR = 0 persists through max elevation | M2-4 not transmitting or wrong freq |
| SNR > 5, Viterbi SYNCED, Deframer NOSYNC | Wrong pipeline — retry next variant |

## ORBCOMM FM112 (NORAD 41184)

Frequency: 137.663 MHz  
Pipeline: `orbcomm_stx_auto_plotter`  
Samplerate: 1e6, dc_block: **false** (signal at center freq — dc_block kills it)  
VGA=24, LNA=16 (lower gain — strong terrestrial signal)

No successful ORBCOMM decode yet. All previous passes had dc_block=True
(inherited from LRPT defaults) — this was fixed June 4 2026.
Output: `*.frm` file in capdir (not .cadu). Log shows only "Progress inf%"
(normal for this pipeline — no per-frame SNR output).

## Queuing a capture

Via MCP (preferred):
```
mcp: run_scheduler_rule_now(rule_id="sat-59051-meteor_lrpt_hackrf", confirm=True, duration_s=<N>)
```

Via curl:
```bash
curl -s http://localhost:8723/scheduler/status
curl -s -X POST http://localhost:8723/scheduler/scan-now \
  -H "Content-Type: application/json" \
  -d '{"norad":59051,"frequency_hz":137100000,"duration_s":300,...}'
```

**Do not run satdump or hackrf_transfer directly.** Always enqueue through the
scheduler so the single-device lock is respected.

## Monitoring a capture

```bash
python3 monitor_capture.py ~/noaa_captures/<capdir>
# exits 0=healthy, 1=intervened/problem, 2=log not ready
```

Check `<capdir>.log` for SNR/Viterbi/Deframer lines (appear every 10s).
Check `<capdir>/*.cadu` size for lock confirmation.
PID of running satdump: `cat <capdir>.pid`
Kill satdump: `kill $(cat <capdir>.pid)`

## Web endpoints

```
GET  /scheduler/status          — scheduler heartbeat + queue count
GET  /scheduler/rules           — list rules
POST /scheduler/rules           — create/update rule
POST /scheduler/scan-now        — enqueue immediate capture
GET  /captures?norad=NNN        — capture history for a satellite
GET  /captures/<id>/report      — diagnostic report (markdown)
GET  /passes?...                — upcoming pass predictions
GET  /api/v1                    — versioned API endpoint index
```

## Verification after code changes

```bash
python3 -m py_compile serve.py scheduler_mcp.py scheduler/sdr_scheduler.py monitor_capture.py
curl -fsS http://localhost:8723/scheduler/status
```

## Rollback

```bash
git log --oneline -10
git revert <commit>
```
