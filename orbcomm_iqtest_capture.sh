#!/usr/bin/env bash
# One-shot OFFLINE-decode test (does NOT touch the scheduler config).
# Wins the RTL device race ~90s before the scheduler's fire time, records raw IQ
# of the 04:29 UTC ORBCOMM FM32 pass (66 deg), then proves the offline
# orbcomm_stx path end-to-end on a STRONG signal. Emails the result.
set -u
export PATH=/usr/local/bin:/usr/bin:/bin:/home/cstahly/.local/bin
CAP=/home/cstahly/noaa_captures/orbcomm_iqtest_0429.iq
REP=/home/cstahly/noaa_captures/orbcomm_iqtest_0429.report.txt
CENTER=137500000; FS=2000000; GAIN=40; DUR=1140   # 19 min covers AOS->LOS+margin
DEV=0

log(){ echo "[$(date -u +%H:%M:%S)] $*"; }
{
  log "=== ORBCOMM offline-decode test: capturing IQ ==="
  log "device=$DEV center=$CENTER fs=$FS gain=$GAIN dur=${DUR}s -> $CAP"
  /usr/local/bin/rtl_biast -d $DEV -b 1 2>&1 | sed 's/^/  biast: /'
  timeout ${DUR}s /usr/local/bin/rtl_sdr -d $DEV -f $CENTER -s $FS -g $GAIN "$CAP" 2>&1 | tail -4 | sed 's/^/  rtl_sdr: /'
  /usr/local/bin/rtl_biast -d $DEV -b 0 2>&1 | sed 's/^/  biast-off: /'
  SZ=$(wc -c < "$CAP" 2>/dev/null || echo 0)
  log "captured $SZ bytes ($(awk "BEGIN{printf \"%.1f\", $SZ/1e9}") GB)"

  log "=== offline decode via orbcomm_stx (per channel) ==="
  for CH in 137460000 137712500; do
    log "--- channel $CH ---"
    /usr/bin/python3 /home/cstahly/orbcomm_offline.py "$CAP" $CENTER $FS $CH /tmp/orb_iqtest.cu8 8 0 100000 2>&1 | sed 's/^/  shift: /'
    OUT=/tmp/orb_iqtest_out; rm -rf "$OUT"; mkdir -p "$OUT"
    /usr/bin/satdump orbcomm_stx baseband /tmp/orb_iqtest.cu8 "$OUT" --samplerate 250000 --baseband_format cu8 >/dev/null 2>&1
    /usr/bin/python3 - "$CH" "$OUT" <<'PY'
import sys, glob
sys.path.insert(0,'/home/cstahly/src/satellites-overhead')
import orbcomm_ephem as oe, collections
ch, out = sys.argv[1], sys.argv[2]
f = glob.glob(out+'/*.frm')
raw = open(f[0],'rb').read() if f else b''
nsync = raw.hex().count('65a8f9')
valid = oe.load_valid(out)
counts = collections.Counter(oe.HDR.get(p[:2],'UNK_0x'+p[:2]) for p in valid)
fixes=[]
for p in valid:
    if p[:2]=='1f' and len(p)>=48:
        try:
            e=oe.parse_ephem(p)
            if -90<=e['lat']<=90 and -180<=e['lon']<=180 and 600<e['alt_km']<1500: fixes.append(e)
        except Exception: pass
msgs = oe.demux_messages(valid)
print(f"  .frm {len(raw)}B, {nsync} frame-syncs")
print(f"  Fletcher-valid packets: {len(valid)}   messages reassembled: {len(msgs)}")
if counts: print("  types:", ", ".join(f"{k}={v}" for k,v in counts.most_common(8)))
for e in fixes[:8]:
    print(f"  EPHEMERIS sat {e['sat_id']:3d}: {e['lat']:.2f},{e['lon']:.2f} {e['alt_km']:.0f}km {e['gps']}")
print(f"  >>> RESULT ch {ch}: {'PASS - offline decode recovered valid packets' if valid else 'no valid packets'}")
PY
  done
  log "=== done ==="
} > "$REP" 2>&1

SUM=$(grep -E ">>> RESULT|captured .* bytes|Fletcher-valid" "$REP" | sed 's/^/  /')
/usr/bin/mail -s "ORBCOMM offline-decode test (04:29 UTC pass)" cstahly@gmail.com <<EOF
Offline orbcomm_stx decode test on the diverted 66-deg ORBCOMM pass.

$SUM

Full report: $REP
Raw IQ kept at: $CAP
EOF
