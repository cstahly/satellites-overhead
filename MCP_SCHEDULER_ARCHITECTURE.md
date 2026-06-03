# MCP facade for the SDR scheduler

## Short version

Yes, adding MCP makes sense, but MCP should be an agent-facing facade over the
same backend scheduler/prediction code. It should not depend on the browser,
the DOM, the single-file web UI, or the web server being open.

The web app and MCP can share the same Python predictor, TLE cache, SatNOGS
lookup/cache, scheduler rule validation, and scheduler rule file. That is the
reason this is a good fit: both interfaces operate on the same domain model.

## Intended architecture

```text
index.html web UI
  -> serve.py HTTP routes
       -> shared predictor / rule / SatNOGS helpers

MCP server
  -> shared predictor / rule / SatNOGS helpers

sdr_scheduler.py
  -> reads ~/sdr_scheduler_rules.json
  -> predicts/runs jobs headlessly
```

The scheduler core must remain boring and independently runnable. If the web
server is stopped and no MCP server is running, the scheduler should still read
its rules and execute jobs as usual.

## What MCP should use

MCP should use shared Python backend code:

- `predict.py` or extracted prediction functions for pass windows and tracks.
- Scheduler rule read/write/validation logic currently represented in
  `serve.py` and consumed by `/home/cstahly/sdr_scheduler.py`.
- TLE cache behavior used by `serve.py`.
- SatNOGS satellite/transmitter lookup and local cache behavior.
- The same `~/sdr_scheduler_rules.json` file the web UI and scheduler already
  use.

MCP should not use:

- Browser geolocation.
- DOM state from `index.html`.
- Rendered table rows or modal state.
- The web app as a required intermediary.
- A separate MCP-only scheduler state file.

## Candidate MCP tools

These are the useful tools an agent would want:

- `list_scheduler_rules`
- `get_scheduler_rule`
- `add_satellite_rule`
- `update_scheduler_rule`
- `delete_scheduler_rule`
- `enable_scheduler_rule`
- `disable_scheduler_rule`
- `predict_satellite_passes`
- `list_overhead_now`
- `list_radio_targets`
- `get_satellite_details`
- `list_satellite_transmitters`
- `suggest_capture_settings`
- `list_upcoming_scheduler_runs`
- `dry_run_scheduler_rule`
- `run_scheduler_rule_now`
- `get_scheduler_status`

The first implementation does not need all of these. A pragmatic first cut is:

1. `list_scheduler_rules`
2. `add_satellite_rule`
3. `delete_scheduler_rule`
4. `predict_satellite_passes`
5. `list_satellite_transmitters`
6. `get_scheduler_status`

## Rule contract

MCP should write the same rule records the web UI writes:

```json
{
  "id": "sat-40069-raw_iq_hackrf",
  "enabled": true,
  "type": "satellite_recurring",
  "name": "SKYTERRA 1",
  "norad": 40069,
  "group": "radio",
  "frequency_hz": 1545000000,
  "profile": "raw_iq_hackrf",
  "min_peak_el": 20,
  "start_offset_s": -30,
  "end_offset_s": 60
}
```

The UI label is "capture", but the JSON key remains `profile` because that is
the scheduler compatibility field. It means which capture/receive pipeline to
run, such as raw IQ recording versus a Meteor LRPT capture flow.

## Important behavior constraints

- MCP can optionally query the web, SatNOGS, or CelesTrak through shared cache
  helpers.
- MCP and the web UI should both tolerate offline/stale-cache operation.
- Scheduler execution must not require MCP.
- Scheduler execution must not require `serve.py`.
- Scheduler execution must not require a browser.
- Pass predictions should come from the Python predictor, not from JavaScript
  worker code.
- Frequencies should come from transmitter records, not name-based hardcoding.
- Agent-created events that do not match satellite maps/CelesTrak/SatNOGS
  should still be supported as scheduler rules or one-shot jobs, provided the
  scheduler has enough timing/frequency/capture data to run them.

## Suggested implementation order

1. Extract reusable helpers from `serve.py` into small Python modules:
   - `scheduler_rules.py`
   - `satnogs.py`
   - `tle_cache.py`
2. Keep `serve.py` as an HTTP adapter that imports those helpers.
3. Add an MCP server as a separate adapter that imports the same helpers.
4. Keep `/home/cstahly/sdr_scheduler.py` reading the same rule file directly.
5. Add tests or smoke checks that verify web UI, MCP, and scheduler all see the
   same rule state.

## What this buys us

The web app remains the point-and-click interface for selecting satellites and
tracking them. MCP becomes the agent/programmatic interface for the same actions:

- "Track SKYTERRA whenever it is overhead."
- "Disable Meteor captures for tonight."
- "Show me all upcoming scheduled radio captures."
- "Find satellites with active transmitters in the V-dipole range."
- "Schedule this arbitrary radio event tomorrow at 145.825 MHz."

That is the correct relationship: same backend model, two interfaces.
