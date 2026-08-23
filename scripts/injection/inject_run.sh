#!/bin/bash
# Repo root, overridable: EXOSAT_ROOT=/path/to/exosat-rv ./this-script.sh
# Derived before any cd, so BASH_SOURCE still resolves against this script.
EXOSAT_ROOT="${EXOSAT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# Generated products and staging land outside the repo: EXOSAT_WORK=/path ./this-script.sh
WORK="${EXOSAT_WORK:-$HOME/exosat-work}"
cd ~/viper-src || exit 1
export PATH="$HOME/bin:$PATH"
FTS=lib/CRIRES/FTS/CRp_SGC2_FTStmpl-HR0p007-WN5000-10000_Hband.dat
PY=~/viperenv/bin/python
OUT=$WORK/inj; mkdir -p "$OUT"
PLAN="$EXOSAT_ROOT"/scripts/injection/inject_plan.json

# two template families: the corrected (telluric-free) one and the M2 baseline one
$PY "$EXOSAT_ROOT"/scripts/injection/mktpl.py "$PLAN" U_mk_tpl.fits      ~/inj/clean
$PY "$EXOSAT_ROOT"/scripts/injection/mktpl.py "$PLAN" cd35_2722B_tpl.fits ~/inj/base

n=$($PY -c "import json;print(len(json.load(open('$PLAN'))))")
for arm in clean base; do
  if [ "$arm" = clean ]; then FLAGS="-nocell"; else FLAGS=""; fi
  : > "$OUT/$arm.txt"
  for ((i=0;i<n;i++)); do
    f=$($PY -c "import json;print(json.load(open('$PLAN'))[$i]['file'])")
    t=$(printf "inj%02d" $i)
    cp -f full1.targ.csv "${arm}_$t.targ.csv"
    $PY viper.py "cr2res_data/$f" ~/inj/$arm/${t}_tpl.fits -inst CRIRES -fts "$FTS" \
        -targ "CD-35 2722" -tag "${arm}_$t" $FLAGS > /tmp/${arm}_$t.log 2>&1
    rv=$(awk 'NR==2{print $2}' "${arm}_$t.rvo.dat" 2>/dev/null)
    bj=$(awk 'NR==2{print $1}' "${arm}_$t.rvo.dat" 2>/dev/null)
    echo "$i $bj $rv $f" >> "$OUT/$arm.txt"
  done
  echo "arm $arm done ($(wc -l < "$OUT/$arm.txt") epochs)"
done
echo INJDONE
