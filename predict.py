#!/usr/bin/env python3
"""Headless satellite pass prediction for scheduler integrations.

Uses the same cached TLE files as serve.py and emits JSON suitable for antenna
rotator / receiver scheduling.  Range is kilometers; range_rate is km/s.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

try:
    import ephem
except ImportError as exc:  # pragma: no cover - exercised only on missing dep
    raise SystemExit("predict.py requires pyephem: python3 -m pip install ephem") from exc


ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, ".tlecache")
DEFAULT_GROUP = "active"


@dataclass(frozen=True)
class TleSat:
    name: str
    norad: int
    line1: str
    line2: str


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ephem_to_dt(value) -> datetime:
    return ephem.Date(value).datetime().replace(tzinfo=timezone.utc)


def degrees(value) -> float:
    return math.degrees(float(value))


def parse_tles(text: str) -> list[TleSat]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    sats: list[TleSat] = []
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1], lines[i + 2]
        if line1.startswith("1 ") and line2.startswith("2 "):
            try:
                norad = int(line1[2:7])
            except ValueError:
                i += 1
                continue
            sats.append(TleSat(name=name, norad=norad, line1=line1, line2=line2))
            i += 3
        else:
            i += 1
    return sats


def load_tles(group: str = DEFAULT_GROUP, tle_file: str | None = None) -> list[TleSat]:
    path = tle_file or os.path.join(CACHE_DIR, f"{group}.tle")
    with open(path, encoding="utf-8") as fh:
        return parse_tles(fh.read())


def make_observer(lat: float, lon: float, alt_m: float, at: datetime) -> ephem.Observer:
    obs = ephem.Observer()
    obs.lat = str(lat)
    obs.lon = str(lon)
    obs.elevation = float(alt_m)
    obs.horizon = "0"
    obs.date = ephem.Date(at)
    return obs


def look_at(sat: ephem.EarthSatellite, obs: ephem.Observer, at: datetime) -> dict:
    obs.date = ephem.Date(at)
    sat.compute(obs)
    az = degrees(sat.az) % 360.0
    el = degrees(sat.alt)
    return {
        "t": iso(at),
        "az": az,
        "el": el,
        "sub_lat": degrees(float(sat.sublat)),
        "sub_lon": degrees(float(sat.sublong)),
        "range": float(sat.range) / 1000.0,
        "range_rate": float(sat.range_velocity) / 1000.0,
    }


def sample_track(
    tle: TleSat,
    lat: float,
    lon: float,
    alt_m: float,
    aos: datetime,
    los: datetime,
    step_s: int,
) -> list[dict]:
    sat = ephem.readtle(tle.name, tle.line1, tle.line2)
    obs = make_observer(lat, lon, alt_m, aos)
    out = []
    t = aos
    step = timedelta(seconds=step_s)
    while t < los:
        out.append(look_at(sat, obs, t))
        t += step
    out.append(look_at(sat, obs, los))
    return out


def select_tles(tles: Iterable[TleSat], names: set[str], norads: set[int]) -> list[TleSat]:
    if not names and not norads:
        return list(tles)
    wanted_names = {name.upper() for name in names}
    return [
        tle
        for tle in tles
        if tle.norad in norads or tle.name.upper() in wanted_names or any(n in tle.name.upper() for n in wanted_names)
    ]


def predict_passes(
    tles: Iterable[TleSat],
    lat: float,
    lon: float,
    alt_m: float,
    start: datetime,
    hours: float,
    min_el: float,
    track_step_s: int,
    min_duration_s: int = 0,
    limit: int | None = None,
) -> list[dict]:
    start = start.astimezone(timezone.utc)
    end = start + timedelta(hours=hours)
    passes: list[dict] = []

    for tle in tles:
        sat = ephem.readtle(tle.name, tle.line1, tle.line2)
        obs = make_observer(lat, lon, alt_m, start)
        while True:
            try:
                rise, rise_az, peak, peak_el, set_, set_az = obs.next_pass(sat)
            except (ValueError, RuntimeError):
                break

            aos = ephem_to_dt(rise)
            peak_t = ephem_to_dt(peak)
            los = ephem_to_dt(set_)
            if aos > end:
                break

            duration_s = int((los - aos).total_seconds())
            max_el = degrees(peak_el)
            if los >= start and max_el >= min_el and duration_s >= min_duration_s:
                track = sample_track(tle, lat, lon, alt_m, aos, los, track_step_s)
                peak_sample = look_at(sat, obs, peak_t)
                record = {
                    "norad": tle.norad,
                    "name": tle.name,
                    "aos": iso(aos),
                    "los": iso(los),
                    "max_t": iso(peak_t),
                    "max_el": max_el,
                    "max_az": peak_sample["az"],
                    "aos_az": degrees(rise_az) % 360.0,
                    "los_az": degrees(set_az) % 360.0,
                    "duration_s": duration_s,
                    "track_step_s": track_step_s,
                    "track": track,
                }
                passes.append(record)

            obs.date = ephem.Date(los + timedelta(seconds=1))

    passes.sort(key=lambda p: p["aos"])
    return passes[:limit] if limit is not None else passes


def parse_start(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Predict satellite passes as scheduler JSON.")
    parser.add_argument("--group", default=DEFAULT_GROUP, help="TLE cache group, default: active")
    parser.add_argument("--tle-file", help="Read TLEs from this file instead of .tlecache/<group>.tle")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--alt-m", type=float, default=0.0)
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--start", help="UTC ISO timestamp, default: now")
    parser.add_argument("--min-el", type=float, default=10.0, help="Minimum peak elevation in degrees")
    parser.add_argument("--min-duration-s", type=int, default=0)
    parser.add_argument("--track-step-s", type=int, default=1)
    parser.add_argument("--name", action="append", default=[], help="Satellite name or substring; repeatable")
    parser.add_argument("--norad", action="append", type=int, default=[], help="NORAD catalog id; repeatable")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    if args.track_step_s < 1:
        parser.error("--track-step-s must be >= 1")

    tles = select_tles(load_tles(args.group, args.tle_file), set(args.name), set(args.norad))
    passes = predict_passes(
        tles,
        lat=args.lat,
        lon=args.lon,
        alt_m=args.alt_m,
        start=parse_start(args.start),
        hours=args.hours,
        min_el=args.min_el,
        track_step_s=args.track_step_s,
        min_duration_s=args.min_duration_s,
        limit=args.limit,
    )
    print(json.dumps(passes, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
