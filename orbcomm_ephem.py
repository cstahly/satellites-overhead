#!/usr/bin/env python3
"""Parse a satdump ORBCOMM .frm (orbcomm_stx_auto_plotter) into decoded products.
Self-contained (no gr-orbcomm / external deps). Per pass it produces:

  orbcomm_decoded.txt   — summary (packet taxonomy + ephemeris fixes) [also stdout/email]
  orbcomm_messages.txt   — reassembled M2M messages + terminal codes + per-type samples

Packet structure, Fletcher checksum, and ephemeris ECEF scaling from Frank
Bieberly's ORBCOMM-receiver (github.com/fbieberly/ORBCOMM-receiver). Packet-type
classifications and the message demux/terminal-code extraction were reverse-
engineered locally 2026-06-15 (see AGENT_HANDOFF). Usage: orbcomm_ephem.py <capdir>
Exit 0 if any ephemeris fix decoded.
"""
import sys, os, glob, math, collections
from datetime import datetime, timedelta

HDR = {  # type-byte (hex) -> label.  *=reverse-engineered locally, not in fbieberly
    '65': 'Sync', '1a': 'Message', '1b': 'Uplink_info', '1c': 'Downlink_info',
    '1d': 'Network', '1e': 'Fill', '1f': 'Ephemeris', '22': 'Orbital',
    '0a': 'Data2*', '0d': 'Ctrl_0d*', '0e': 'Beacon_0e*', '0b': 'Ctrl_0b*', '13': 'Status_13*',
}

def fletcher(h):
    s1 = s2 = 0
    if len(h) % 2: h += '0'
    for i in range(0, len(h) - 1, 2):
        s1 = (s1 + int(h[i:i+2], 16)) % 256
        s2 = (s1 + s2) % 256
    return '{:02X}{:02X}'.format(s2, s1)

def ecef_to_lla(x, y, z):
    f = 1.0 / 298.257223563
    a = 6378137.0; b = a * (1 - f)
    e2 = 1 - (b*b)/(a*a); eps = e2 / (1 - e2)
    p = math.sqrt(x*x + y*y); q = math.atan2(z*a, p*b)
    phi = math.atan2(z + eps*b*math.sin(q)**3, p - e2*a*math.cos(q)**3)
    lam = math.atan2(y, x)
    v = a / math.sqrt(1 - e2*math.sin(phi)**2)
    h = (p / math.cos(phi)) - v
    return math.degrees(phi), math.degrees(lam), h

def parse_ephem(p):
    pl = ''.join([p[xx:xx+2] for xx in range(42, 2, -2)])
    wn = int(pl[:4], 16); tow = int(pl[4:10], 16)
    gt = datetime(1980, 1, 6) + timedelta(weeks=wn, seconds=tow)
    M, V = 8378155.0, 1048576.0
    def d(s):
        s = s[::-1]
        return (2*(int(s[:2][::-1],16) + 256*int(s[2:4][::-1],16) + 65536*int(s[4:],16))*M)/V - M
    z, y, x = d(pl[25:30]), d(pl[30:35]), d(pl[35:40])
    lat, lon, alt = ecef_to_lla(x, y, z)
    return dict(sat_id=int(p[4:6], 16), lat=lat, lon=lon, alt_km=alt/1000.0,
                gps=gt.strftime('%Y-%m-%d %H:%M:%S'))

def load_valid(capdir):
    frms = glob.glob(os.path.join(capdir, "*.frm"))
    if not frms:
        return []
    hexs = open(frms[0], 'rb').read().hex()
    i, packets = 0, []
    while i + 24 <= len(hexs):
        plen = 48 if hexs[i:i+2] == '1f' else 24
        packets.append(hexs[i:i+plen]); i += plen
    return [p for p in packets if fletcher(p) == '0000']

def demux_messages(valid):
    """Reassemble Message (0x1a) fragments by contiguity: collect {0..total-1}
    per `total` value, emit sorted when complete. byte1 = total(hi)/frag(lo)."""
    msgs = [(int(p[2], 16), int(p[3], 16), p[4:20]) for p in valid if p[:2] == '1a']
    open_m, done = {}, []
    for t, f, d in msgs:
        if t == 0:
            continue
        slot = open_m.setdefault(t, {})
        if f in slot:
            open_m[t] = {f: d}
        else:
            slot[f] = d
        if len(open_m[t]) == t:
            done.append(''.join(open_m[t][k] for k in sorted(open_m[t])))
            del open_m[t]
    return done

def terminal_codes(valid):
    """'F'-prefixed terminal codes from Uplink_info (0x1b), first 4 payload bytes."""
    out = collections.Counter()
    for p in valid:
        if p[:2] == '1b':
            raw = bytes.fromhex(p[4:12])
            out[''.join(c if 32 <= b < 127 else '.' for b, c in zip(raw, raw.decode('latin1')))] += 1
    return out

def main():
    capdir = sys.argv[1]
    valid = load_valid(capdir)
    counts = collections.Counter(HDR.get(p[:2], 'UNK_0x'+p[:2]) for p in valid)
    fixes = []
    for p in valid:
        if p[:2] == '1f' and len(p) >= 48:
            try:
                e = parse_ephem(p)
                if -90 <= e['lat'] <= 90 and -180 <= e['lon'] <= 180 and 600 < e['alt_km'] < 1500:
                    fixes.append(e)
            except Exception:
                pass
    messages = demux_messages(valid)
    termcodes = terminal_codes(valid)

    # --- summary (stdout + email + orbcomm_decoded.txt) ---
    lines = [f"ORBCOMM decode: {len(valid)} Fletcher-valid packets, "
             f"{len(messages)} messages reassembled"]
    if counts:
        lines.append("  types: " + ", ".join(f"{k}={v}" for k, v in counts.most_common()))
    if termcodes:
        lines.append("  terminal codes: " + ", ".join(f"{k}(x{v})" for k, v in termcodes.most_common(6)))
    if fixes:
        lines.append(f"  {len(fixes)} ephemeris fix(es):")
        for e in fixes:
            lines.append(f"    sat {e['sat_id']:3d}: {e['lat']:7.2f}, {e['lon']:8.2f}  "
                         f"{e['alt_km']:.0f} km  GPS {e['gps']}")
    else:
        lines.append("  no ephemeris fixes (weak pass or none in window)")
    summary = "\n".join(lines)
    print(summary)
    try:
        with open(os.path.join(capdir, "orbcomm_decoded.txt"), "w") as f:
            f.write(summary + "\n")
    except Exception:
        pass

    # --- detailed message dump (orbcomm_messages.txt) ---
    try:
        with open(os.path.join(capdir, "orbcomm_messages.txt"), "w") as f:
            f.write(f"# ORBCOMM reassembled messages — {len(messages)} total\n")
            f.write("# format: [bytes] hex | ascii\n\n")
            for m in messages:
                asc = ''.join(c if 32 <= ord(c) < 127 else '.' for c in bytes.fromhex(m).decode('latin1'))
                f.write(f"[{len(m)//2:2d}B] {m}  |{asc}|\n")
            f.write("\n# terminal codes (Uplink_info, 'F'-prefixed):\n")
            for k, v in termcodes.most_common():
                f.write(f"  {k}  x{v}\n")
            f.write("\n# sample packets per type:\n")
            seen = set()
            for p in valid:
                t = HDR.get(p[:2], 'UNK_0x'+p[:2])
                if t not in seen and t not in ('Fill',):
                    seen.add(t); f.write(f"  {t:14s} {p}\n")
    except Exception:
        pass

    sys.exit(0 if fixes else 1)

if __name__ == "__main__":
    main()
