# Agent handoff — Satellites Overhead → radio scheduler

You're picking this up on a new box. The owner wants to feed satellite pass
predictions into a **radio scheduler** (antenna rotator + receiver tuning).
This doc is the architecture, the data contracts, and the integration plan.
Read `README.md` first for run instructions. (Codex reads this file as
`AGENTS.md`; Claude Code, please read it too.)

## TL;DR for the integration

The existing app is a **viewer**. A radio scheduler is **headless and
server-side**, so do **not** make it depend on the browser. The pass-prediction
math currently lives in JavaScript inside a Web Worker (`index.html`,
the `workerSrc` template string). For the scheduler, **port that logic to
Python** and expose it as JSON — either a new endpoint in `serve.py`
(`GET /passes?...`) or a standalone `predict.py` CLI. Then have the scheduler
consume that JSON.

## Current architecture

- `index.html` — single-file frontend. All orbital math runs in a Web Worker
  using `satellite.js` (SGP4) pulled from a CDN. Key worker functions:
  - `lookAt(satrec, date, gmst)` → topocentric `{el, az, range, eci}`.
  - `predict` handler → coarse forward scan detecting horizon crossings.
  - `finish()` → refines rise/peak/set with bisection + ternary search.
  - `bisect()` → time of the 0° elevation crossing (AOS/LOS).
- `serve.py` — static server + caching TLE proxy. Browser calls
  `GET /tle?group=NAME`; the server caches CelesTrak data to `.tlecache/` for
  2 h (`TTL`) and serves stale on failure. Catalog whitelist in `ALLOWED`.
- `.tlecache/*.tle` — **bundled, pre-warmed cache** (active, starlink, visual,
  stations, gps-ops, science). This is why the new box doesn't hit a 403 on
  first run.

## Data conventions (match these exactly when porting)

- **Time**: JavaScript epoch milliseconds, UTC. SGP4 uses TLE epoch internally.
- **Azimuth**: degrees clockwise from true North (0–360). N=0, E=90, S=180, W=270.
- **Elevation**: degrees above the local horizon. Negative = below.
- **Range**: slant range, km. **Altitude**: geodetic height, km.
- A "pass" = an interval where elevation ≥ 0°. AOS/LOS are the 0° crossings.

### Pass record (what `predict` emits today)
```
{ name, start, end, maxEl, maxAz, startAz }   // start/end = epoch ms
```
### Overhead record (the live list)
```
{ name, el, az, range, alt, dir }
```

## What a radio scheduler additionally needs (today's gaps)

1. **Full az/el track per pass**, not just rise/peak/set — sample every ~1 s so
   a rotator (e.g. hamlib `rotctld`) can follow the satellite. Add a function
   that, given a satrec + AOS/LOS, returns `[{t, az, el, range, range_rate}]`.
2. **Doppler / range-rate** for receiver tuning (hamlib `rigctld`). Compute
   range-rate from consecutive ECF positions or `satellite.js` Doppler helpers;
   shifted_freq = f * (1 − range_rate / c).
3. **Transmit/receive frequencies** — **NOT in TLE data.** Pull per-satellite
   transmitters from the **SatNOGS DB API**
   (`https://db.satnogs.org/api/transmitters/?satellite__norad_cat_id=NNNNN`).
   Keep NORAD ID: it's TLE line 1, columns 3–7. (Note: the proxy currently
   serves TLE without an explicit NORAD field — parse it from the line.)
4. **Usable-pass filter**: most scheduling wants min peak elevation ≥ ~10–15°
   and may exclude passes shorter than some duration.
5. **Sun/eclipse state** only matters for optical, not radio — ignore for RF.

## Recommended next steps (in order)

1. **Confirm the scheduler's input format.** Ask the owner: is it gpredict,
   SatNOGS client, Hamlib directly, or a custom cron/JSON ingest? That decides
   the output contract. Don't guess — it changes everything downstream.
2. **Port prediction to Python.** Use `skyfield` (nicer API) or `python-sgp4`
   (lighter). Reuse the bundled TLEs in `.tlecache/`. Reproduce `lookAt` +
   bisection/ternary refinement. Validate against the JS app for a known sat.
3. **Add `GET /passes` to `serve.py`** returning JSON:
   ```
   /passes?group=active&hours=24&min_el=10&lat=..&lon=..&alt_m=..
   → [{ norad, name, aos, los, max_el, max_az, aos_az, los_az,
        duration_s, track:[{t,az,el,range,range_rate}] }, ...]
   ```
   Times as ISO-8601 UTC. Keep the same 2 h TLE cache.
4. **Enrich with frequencies** from SatNOGS DB; cache that too (it changes rarely).
5. **Emit the scheduler's native format** (or a thin adapter) from the JSON.

## Gotchas (learned the hard way)

- **CelesTrak 403** = rate limiting on repeated downloads. Always go through the
  proxy/cache; never fetch from many clients/loops. The bundled `.tlecache/`
  avoids a cold-start 403. `serve.py` serves stale on 403 by design.
- **`satcat.csv` is useless for positions** — it's metadata (period/incl/apogee),
  no epoch/state vector. You must use GP/TLE data.
- `active` (~15k) is the largest no-auth set. Full catalog incl. debris needs a
  **Space-Track** login.
- Want fully offline (scheduler box has no internet)? Either bump `TTL` very high
  or add a `--offline` flag to `serve.py` that skips the network and always
  serves cache. The stale-fallback path already makes 403s non-fatal.
- TLE accuracy degrades over days; refresh elements every 1–3 days for good
  pass timing. The 2 h TTL refresh handles this when online.

## Quick verification

```bash
python3 serve.py
curl -s localhost:8723/tle?group=active | grep -c '^1 '   # ~15000
# In a browser: http://localhost:8723 → Use my location → Predict passes → ⬇ CSV
```
