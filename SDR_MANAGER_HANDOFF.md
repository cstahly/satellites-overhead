# SDR Manager handoff — June 3/4 2026

Read CLAUDE.md first — it has the file map, service commands, and M2-4 troubleshooting context.

---

## Current state

### M2-4 LRPT (primary target)

**Status: NOSYNC unresolved, fix untested.**

Every M2-4 pass has produced `Viterbi SYNCED + BER 0.000 + Deframer NOSYNC` at ~27 dB SNR.
Two bugs were fixed June 3:

| Commit | Fix |
|--------|-----|
| `6d2665e` | Retry off-by-one — `LRPT_RETRY_VARIANTS[0]` (iq_swap=True, 1e6) was never tried |
| `ccfd2b0` | Rule job defaulted `iq_swap=False` — initial attempt now uses variant[0] settings |

**Neither fix has been tested during a real pass yet.**

Next M2-4 pass: **June 4 15:21 EDT, 42°**
- Scheduled automatically by the rule `sat-59051-meteor_lrpt_hackrf`
- Post-pass diagnostic fires at **15:50 EDT via systemd timer** (`check-m24-pass.timer`)
- Result written to `~/m24_pass_result_*.txt`

If the pass fires and still NOSYNC: read all 4 variant diagnostic reports and the raw satdump log. The CLAUDE.md NOSYNC troubleshooting section has the decision tree.

### SO-50 FM repeater (new)

Added June 3. Every SO-50 pass above 10° is now captured and auto-processed:

1. IQ captured → `~/cosmos_captures/so_50_HHMM.iq`
2. `so50_process.py` runs in a daemon thread after capture:
   - FM demodulates → `.wav`
   - Detects bursts >3× noise floor
   - Runs `faster-whisper base` on any bursts
   - Writes `_report.md` with timestamps and transcripts

First real test on capture from the June 3 21:55 pass: two confirmed FM bursts detected (0.7s and 0.9s), Whisper returned `[unintelligible]` on both — clips are too short for reliable ASR. Longer transmissions will transcribe better.

Next SO-50 passes: 23:32 tonight (13°), 10:20 UTC tomorrow (78°, best window).

### Hardware

- **HackRF One** (serial: 14d463dc2f209de1)
- **V-dipole** 54cm arms, on mast at ~12 ft elevation as of June 3 — improved horizon and reduced multipath
- **RTL-SDR v3** — backup, not currently used

### LRPT status (verify before every session)

Check https://ub8qbd.satdump.org/wx_report_new.html

As of June 3 2026:
- **M2-4 LRPT ON at 137.1 MHz** ← target
- **M2-3 LRPT OFF** — beacon only 137.9 MHz

---

## What's in this repo

| File | Purpose |
|------|---------|
| `scheduler/sdr_scheduler.py` | Live scheduler (symlinked from `~/sdr_scheduler.py`) |
| `serve.py` | Web UI on :8723 |
| `scheduler_mcp.py` | MCP server |
| `monitor_capture.py` | T+90s satdump health monitor |
| `predict.py` | Headless pass predictor |
| `so50_process.py` | SO-50 FM demod + Whisper pipeline |
| `analyze_150mhz.py` | Bounded-memory sampled spectrum analyzer for raw IQ captures |
| `hackrf_fm_demod.py` | General FM demodulator (HackRF IQ → 50 kHz PCM) |
| `hackrf_am_demod.py` | General AM demodulator (HackRF IQ → 16 kHz WAV) |
| `check_m24_pass.sh` | One-shot post-pass diagnostic script (also installed as systemd timer) |
| `sdr_scheduler_rules.json` | Reference copy of live rules (live copy at `~/sdr_scheduler_rules.json`) |
| `deploy/sdr-scheduler.service` | Systemd unit for scheduler |
| `deploy/satellites-overhead.service` | Systemd unit for web UI |

Runtime files **not** in git (home dir):
- `~/sdr_scheduler_rules.json` — authoritative live rules
- `~/sdr_capture_history.json` — capture history
- `~/sdr_scheduler_commands.json` — one-shot queue
- `~/sdr_scheduler_status.json` — heartbeat
- `~/sdr_scheduler.log` — scheduler log

---

## Pending work

### Immediate (before anything else)
1. **Check June 4 15:21 M2-4 pass result** — `cat ~/m24_pass_result_*.txt` or `sdr captures --norad 59051` + `sdr report <id>`. If still NOSYNC, escalate.

### Deferred
2. **Frontend refactor** — Move web UI to sadbabyrabbit.com. User is about to start this. See architecture section below.
3. **ORBCOMM** — Next pass is first real test of samplerate-as-integer fix. Check `sdr captures --norad <orbcomm_norad>` after next ORBCOMM pass.

---

## Frontend refactor context

The user is refactoring the web frontend to run on **sadbabyrabbit.com**. Current architecture:

- `serve.py` — aiohttp server, :8723, serves `index.html` + REST API
- API endpoints: `/scheduler/status`, `/scheduler/rules`, `/scheduler/scan-now`, `/captures`, `/passes`, `/capture-settings`
- All hardware control goes through the scheduler queue — never direct from web process
- Scheduler is the single authority over HackRF

The backend API and scheduler are already decoupled from the frontend. A refactor to serve the frontend from a different host (nginx reverse proxy, or separate static hosting) should only need to handle CORS on the API endpoints.

Do not restart the scheduler mid-pass. The completed set is in-memory — a restart during a pass window will cause the job to re-fire.

---

## Session startup checklist

**Do this first, before anything else:**

1. `sdr status` — confirm scheduler is running
2. `sdr passes` — check for passes in next 24h
3. If a pass is within 24h: `systemd-run --user --on-calendar="<UTC time>" ~/check_m24_pass.sh` to schedule post-pass monitoring
4. Check `~/m24_pass_result_*.txt` if the M2-4 post-pass timer has already fired

---

## Pipeline reference

### M2-4 LRPT capture flow

```
Rule fires (sat-59051-meteor_lrpt_hackrf)
  → satdump live meteor_m2-x_lrpt --iq_swap --samplerate 1000000
  → monitor at T+90s
    SYNCED → done
    NOSYNC → kill, retry LRPT_RETRY_VARIANTS[next_idx]
    Exhausted → invoke Claude monitor
```

### SO-50 FM capture flow

```
Rule fires (sat-27607-so50-fm)
  → hackrf_transfer -f 145850000 -s 2000000 → cosmos_captures/so_50_HHMM.iq
  → so50_process.py [daemon thread]
      FM demod → .wav
      burst detection (>3× noise RMS, ≥0.3s)
      faster-whisper base → _report.md
```

The generic IQ analyzer must remain bounded-memory. The previous temporary
`/tmp/analyze_150mhz.py` loaded an entire multi-gigabyte capture and all FFT
windows into RAM, causing an OOM kill on June 3, 2026. The scheduler now invokes
the checked-in `analyze_150mhz.py`, which samples at most 4096 FFT windows.

### FM demod standalone

```bash
# SO-50 or any FM sat — output 50 kHz PCM for multimon-ng
python3 hackrf_fm_demod.py <file.iq> <offset_hz> | sox -t raw -r 50000 -e signed -b 16 -c 1 - -t wav - | multimon-ng -t wav -a AFSK1200 -A -

# Aviation AM — output 16 kHz WAV
hackrf_transfer -r /dev/stdout -f <freq_hz> -s 2000000 -l 16 -g 36 -a 1 | python3 hackrf_am_demod.py output.wav
```

---

## Scheduler known bugs / quirks

See CLAUDE.md for full details. Summary:

- **Retry off-by-one** — FIXED `6d2665e`. Monitor now correctly tries variant[0] first.
- **Rule iq_swap default** — FIXED `ccfd2b0`. Initial rule job now uses `iq_swap=True`.
- **CADU filename** — FIXED `ccfd2b0`. `satdump_capture` now uses `{pipeline}.cadu` not hardcoded name.
- **Fire-time boundary** — FIXED June 3. 90s grace window prevents wrap-to-next-day.
- **Completed set in-memory** — Scheduler restart re-evaluates all jobs. Avoid restarting during a pass window.
- **Optional child OOM** — `OOMPolicy=continue` keeps the scheduler alive if an analyzer or postprocessor is killed.

### June 3, 2026 prediction/OOM repair

At 23:45 EDT, the SO-50 capture completed successfully at 3.1 GB. The old
temporary `/tmp/analyze_150mhz.py` then loaded the entire IQ file and every FFT
result into memory. Its process reached about 14 GB RSS and was OOM-killed at
23:47, causing `sdr-scheduler.service` to restart. During the memory pressure,
`/scheduler/upcoming` exceeded the CLI timeout; `sdr rules` discarded that error
and incorrectly displayed `no passes predicted`.

Repairs:

- `analyze_150mhz.py` samples at most 4096 FFT windows and analyzed the same
  3.1 GB capture in about 1.8 seconds.
- The scheduler invokes the checked-in analyzer instead of `/tmp`.
- The scheduler service uses `OOMPolicy=continue`.
- `/scheduler/upcoming` parses each TLE group once per request and returns
  explicit per-rule prediction errors.
- `sdr rules` displays `prediction unavailable` plus a warning on API failure.

Runtime rollback backups:

- `/usr/local/bin/sdr.before-20260604-prediction-fix`
- `~/.config/systemd/user/sdr-scheduler.service.before-20260604-prediction-fix`

To fully undo, revert the repair commit, restore those two backup files, run
`systemctl --user daemon-reload`, then restart the web and scheduler services
outside a pass window.
