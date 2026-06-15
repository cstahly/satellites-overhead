#!/usr/bin/env python3
"""Parse an ORBCOMM satdump .frm (from orbcomm_stx_auto_plotter) and extract
Fletcher-validated packets: ephemeris (satellite GPS positions), sync info,
and a packet-type summary. Self-contained (no gr-orbcomm / external deps).

Usage: orbcomm_ephem.py <capdir>
Prints a summary and writes <capdir>/orbcomm_decoded.txt. Exit 0 if any
ephemeris fix was decoded.

Packet structure + ephemeris scaling from Frank Bieberly's ORBCOMM-receiver
(github.com/fbieberly/ORBCOMM-receiver), reverse-engineered ORBCOMM STX downlink.
"""
import sys, os, glob, math
from datetime import datetime, timedelta

HDR = {  # type-byte (hex) -> label
    '65': 'Sync', '1a': 'Message', '1b': 'Uplink_info', '1c': 'Downlink_info',
    '1d': 'Network', '1e': 'Fill', '1f': 'Ephemeris', '22': 'Orbital',
}

def fletcher(hexs):
    s1 = s2 = 0
    if len(hexs) % 2: hexs += '0'
    for i in range(0, len(hexs) - 1, 2):
        s1 = (s1 + int(hexs[i:i+2], 16)) % 256
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

def decode(capdir):
    frms = glob.glob(os.path.join(capdir, "*.frm"))
    if not frms:
        return [], {}, 0
    raw = open(frms[0], 'rb').read()
    hexs = raw.hex()
    i = 0; packets = []
    while i + 24 <= len(hexs):
        plen = 48 if hexs[i:i+2] == '1f' else 24
        packets.append(hexs[i:i+plen]); i += plen
    valid = [p for p in packets if fletcher(p) == '0000']
    counts = {}
    for p in valid:
        t = HDR.get(p[:2], 'UNK_0x' + p[:2])
        counts[t] = counts.get(t, 0) + 1
    fixes = []
    for p in valid:
        if p[:2] == '1f' and len(p) >= 48:
            try:
                e = parse_ephem(p)
                if -90 <= e['lat'] <= 90 and -180 <= e['lon'] <= 180 and 600 < e['alt_km'] < 1500:
                    fixes.append(e)
            except Exception:
                pass
    return valid, counts, fixes

def main():
    capdir = sys.argv[1]
    valid, counts, fixes = decode(capdir)
    lines = [f"ORBCOMM decode: {len(valid)} Fletcher-valid packets"]
    if counts:
        lines.append("  types: " + ", ".join(f"{k}={v}" for k, v in
                     sorted(counts.items(), key=lambda x: -x[1])))
    if fixes:
        lines.append(f"  {len(fixes)} ephemeris fix(es):")
        for e in fixes:
            lines.append(f"    sat {e['sat_id']:3d}: {e['lat']:7.2f}, {e['lon']:8.2f}  "
                         f"{e['alt_km']:.0f} km  GPS {e['gps']}")
    else:
        lines.append("  no ephemeris fixes (weak pass or no ephemeris in window)")
    out = "\n".join(lines)
    print(out)
    try:
        with open(os.path.join(capdir, "orbcomm_decoded.txt"), "w") as f:
            f.write(out + "\n")
    except Exception:
        pass
    sys.exit(0 if fixes else 1)

if __name__ == "__main__":
    main()
