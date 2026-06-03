# Satellites Overhead

A single-file web app that shows which satellites are above your horizon right
now and predicts upcoming passes, plus a tiny Python server that proxies and
caches orbital data so you never hit CelesTrak's rate limiter.

## Files

| File         | What it is                                                        |
|--------------|-------------------------------------------------------------------|
| `index.html` | The entire frontend: UI, sky plot, and a Web Worker that does all the orbital math (SGP4 via `satellite.js`, loaded from a CDN). |
| `serve.py`   | Static file server **+** caching TLE proxy. The browser fetches `/tle?group=NAME` from here; this process fetches CelesTrak at most once per group per 2 h and caches to `./.tlecache/`. |
| `.tlecache/` | Auto-created TLE cache. Safe to delete; regenerates on demand. Not needed when moving the project. |

## Run

```bash
python3 serve.py            # defaults to port 8723
# open http://localhost:8723
```

No build step, no npm install. Needs Python 3 and internet (for the CDN script
and CelesTrak). The headless pass predictor also needs PyEphem
(`python3 -m pip install ephem` if your distro does not already package it).
To reach it from a phone on the same LAN, it already binds
`0.0.0.0` — browse to `http://<host-ip>:8723` (note: mobile browsers may block
geolocation over a plain LAN IP without HTTPS).

## Headless pass JSON

For scheduler integrations, use the Python predictor instead of the browser:

```bash
python3 predict.py --lat 40.42 --lon -86.88 --alt-m 180 \
  --hours 8 --min-el 5 --norad 59051 --track-step-s 10
```

Or run the server and query `/passes`:

```bash
curl 'http://localhost:8723/passes?group=active&lat=40.42&lon=-86.88&alt_m=180&hours=8&min_el=5&norad=59051&track_step_s=10'
```

The response includes `norad`, `aos`, `los`, `max_el`, `aos_az`, `los_az`,
`duration_s`, and a sampled `track` of `{t, az, el, range, range_rate}` points.

The default catalog in the web UI is `radio`, a curated subset of active TLEs
for common radio/weather/station/amateur targets. The full `active` catalog is
still available, but it is much slower for predictions. Overhead, pass, and
scheduler-rule tables all have text filters for large lists.

The web UI can also save persistent SDR scheduler rules through the local
server. Run `python3 serve.py`, predict passes, choose a profile/frequency, and
click `Track` on a pass. Rules are stored at `~/sdr_scheduler_rules.json`; the
scheduler reads that file directly, so it does not depend on the web server
staying online after the rule is saved.

## How it works

1. Browser gets geolocation, then `fetch('/tle?group=active')`.
2. `serve.py` returns cached or freshly-downloaded TLEs (CelesTrak GP data).
3. The Web Worker parses TLEs into `satrec`s and, every 3 s, computes
   topocentric look angles (azimuth/elevation/range) for the observer — the
   "overhead now" list and sky plot.
4. "Predict passes" scans forward N hours at a coarse step, detects horizon
   crossings, then refines rise/peak/set with bisection + ternary search.
5. CSV export buttons dump either table client-side.

## Data sources & gotchas

- **Orbital data**: CelesTrak GP/TLE, e.g.
  `https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle`.
- CelesTrak **rate-limits** repeated downloads with HTTP 403. The proxy's 2 h
  disk cache is the fix — keep using it rather than fetching from the browser.
- `satcat.csv` is **metadata only** (no epoch/state vectors) and cannot be used
  to compute positions. You need GP/TLE data.
- `active` (~15k objects) is the largest no-auth public set. The full catalog
  (incl. debris) requires a Space-Track login.

See `AGENTS.md` for architecture detail and the radio-scheduler integration plan.
