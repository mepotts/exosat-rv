#!/bin/bash
# Generated products and staging land outside the repo: EXOSAT_WORK=/path ./this-script.sh
WORK="${EXOSAT_WORK:-$HOME/exosat-work}"
# Pull every raw frame + master calibration needed to reduce one CRIRES+ night.
# dataPortal sets the real filename in Content-Disposition, so -OJ is required; files
# arrive .Z (Unix compress) and gzip -d handles them.
D=$HOME/cr2res/raw/night1
mkdir -p "$D" && cd "$D" || exit 1
n=0
while read -r u; do
  [ -z "$u" ] && continue
  n=$((n+1))
  curl -sL -OJ --max-time 1800 "$u" || echo "FAILED $u"
done < "$WORK"/night1_urls.txt
echo "downloaded $n"
for f in *.Z; do [ -e "$f" ] && gzip -d -f "$f"; done
ls -la | tail -30
du -sh "$D"
touch "$D/.fetched"
