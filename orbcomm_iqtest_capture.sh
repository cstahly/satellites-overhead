#!/usr/bin/env bash
# One-shot OFFLINE-decode test (does NOT touch the scheduler config).
# Wins the RTL device race ~90s before the scheduler's fire time, records raw IQ
# of the 04:29 UTC ORBCOMM FM32 pass (66 deg), then proves the offline
# orbcomm_stx path end-to-end on a STRONG signal. Emails the result.
set -u
export PATH=/usr/local/bin:/usr/bin:/bin:/home/cstahly/.local/bin
CAP=/home/cstahly/noaa_captures/orbcomm_iqtest_0429.iq
REP=/home/cstahly/noaa_captures/orbcomm_iqtest_0429.report.txt
CENTER=137500000; FS=2000000; GAIN=40; DUR=1140   # gain 40 = the value ORBCOMM actually decodes at (30 starved the weak signal); 19 min covers AOS->LOS+margin
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

  log "=== offline decode: scan the band for active channels + decode each ==="
  /usr/bin/python3 /home/cstahly/orbcomm_scan_decode.py "$CAP" $CENTER $FS 2>&1
  log "=== done ==="
} > "$REP" 2>&1

SUM=$(grep -E ">>> TOTAL|candidate channels|captured .* bytes|Fletcher-valid" "$REP" | sed 's/^/  /')
/usr/bin/mail -s "ORBCOMM offline-decode test (04:29 UTC pass)" cstahly@gmail.com <<EOF
Offline orbcomm_stx decode test on the diverted 66-deg ORBCOMM pass.

$SUM

Full report: $REP
Raw IQ kept at: $CAP
EOF
