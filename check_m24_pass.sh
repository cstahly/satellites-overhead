#!/bin/bash
# Post-pass diagnostic for M2-4 15:21 EDT June 4 2026
# Fired by one-shot systemd timer at 15:50 EDT

OUT="/home/cstahly/m24_pass_result_$(date +%Y%m%d_%H%M).txt"
echo "M2-4 pass check — $(date)" > "$OUT"
echo "==============================" >> "$OUT"

echo "" >> "$OUT"
echo "=== Capture history ===" >> "$OUT"
sdr captures --norad 59051 2>&1 >> "$OUT"

echo "" >> "$OUT"
echo "=== Scheduler log (15:00–16:00) ===" >> "$OUT"
grep "15:[0-9][0-9]:\|16:0[0-5]:" ~/sdr_scheduler.log | tail -40 >> "$OUT"

echo "" >> "$OUT"
echo "=== Most recent capture report ===" >> "$OUT"
LATEST=$(sdr captures --norad 59051 2>/dev/null | awk 'NR==3{print $NF}')
if [ -n "$LATEST" ]; then
    echo "Capture ID: $LATEST" >> "$OUT"
    sdr report "$LATEST" 2>&1 >> "$OUT"
else
    echo "No captures found." >> "$OUT"
fi

echo "" >> "$OUT"
echo "=== Done ===" >> "$OUT"
echo "Result written to $OUT"
logger "check_m24_pass: done — see $OUT"
