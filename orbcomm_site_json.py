#!/usr/bin/env python3
"""Build orbcomm.json (recent decoded passes + ephemeris fixes + stats) and push
it to the website (served at /meteor/orbcomm.json). Regenerates from scratch each
run by re-parsing recent ~/noaa_captures/orbcomm_* capture dirs, so it's safe to
call from anywhere (scheduler post-decode, cron, or by hand). Self-contained
except for orbcomm_ephem (same dir on PYTHONPATH)."""
import os, sys, glob, json, collections, subprocess, datetime, tempfile

sys.path.insert(0, "/home/cstahly/src/satellites-overhead")
import orbcomm_ephem as oe

NOAADIR = os.path.expanduser("~/noaa_captures")
MAX_PASSES = 14
EC2 = "ec2-user@sadbabyrabbit.com"
KEY = os.path.expanduser("~/.ssh/sadbabyrabbit.pem")
REMOTE = "/var/www/meteor/orbcomm.json"      # served at /meteor/orbcomm.json
LOCAL = os.path.expanduser("~/orbcomm_site.json")


def pass_record(capdir):
    valid = oe.load_valid(capdir)
    if not valid:
        return None
    counts = collections.Counter(oe.HDR.get(p[:2], "UNK") for p in valid)
    fixes = []
    for p in valid:
        if p[:2] == "1f" and len(p) >= 48:
            try:
                e = oe.parse_ephem(p)
                if -90 <= e["lat"] <= 90 and -180 <= e["lon"] <= 180 and 600 < e["alt_km"] < 1500:
                    fixes.append(e)
            except Exception:
                pass
    # dedupe fixes to the latest per sat_id (a pass reports a sat multiple times)
    latest = {}
    for e in fixes:
        latest[e["sat_id"]] = e
    fix_list = [
        {"id": e["sat_id"], "lat": round(e["lat"], 3), "lon": round(e["lon"], 3),
         "alt_km": round(e["alt_km"]), "gps": e["gps"]}
        for e in sorted(latest.values(), key=lambda x: x["sat_id"])
    ]
    frm = sorted(glob.glob(os.path.join(capdir, "*.frm")))
    mtime = os.path.getmtime(frm[0]) if frm else os.path.getmtime(capdir)
    captured_at = datetime.datetime.fromtimestamp(
        mtime, datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "pass_id": os.path.basename(capdir.rstrip("/")),
        "captured_at": captured_at,
        "valid_frames": len(valid),
        "messages": len(oe.demux_messages(valid)),
        "n_fixes": len(fix_list),
        "types": dict(counts.most_common(8)),
        "fixes": fix_list,
    }


def main():
    dirs = [d for d in glob.glob(os.path.join(NOAADIR, "orbcomm_*"))
            if os.path.isdir(d) and glob.glob(os.path.join(d, "*.frm"))]
    recs = []
    for d in dirs:
        try:
            r = pass_record(d)
            if r:
                recs.append(r)
        except Exception:
            pass
    recs.sort(key=lambda r: r["captured_at"], reverse=True)
    recs = recs[:MAX_PASSES]
    # rollup: unique sats heard across these passes
    sats = sorted({f["id"] for r in recs for f in r["fixes"]})
    out = {
        "generated": datetime.datetime.now(datetime.timezone.utc)
                     .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "passes": recs,
        "unique_sats": sats,
        "totals": {
            "passes": len(recs),
            "frames": sum(r["valid_frames"] for r in recs),
            "fixes": sum(r["n_fixes"] for r in recs),
            "sats": len(sats),
        },
    }
    with open(LOCAL, "w") as f:
        json.dump(out, f, indent=2)
    # push
    try:
        subprocess.run(["scp", "-o", "StrictHostKeyChecking=no", "-i", KEY,
                        LOCAL, f"{EC2}:{REMOTE}"], check=True, timeout=60,
                       stderr=subprocess.DEVNULL)
        subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", "-i", KEY, EC2,
                        f"chmod 644 {REMOTE}"], check=True, timeout=20,
                       stderr=subprocess.DEVNULL)
        print(f"pushed orbcomm.json — {len(recs)} passes, {len(sats)} sats, "
              f"{out['totals']['frames']} frames")
    except Exception as e:
        print(f"push failed: {e}")


if __name__ == "__main__":
    main()
