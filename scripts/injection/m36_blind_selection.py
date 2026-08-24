"""M36: run the pre-registered paper-blind configuration selection.

The protocol is `docs/milestones/M36-PREREGISTRATION.md`, committed before this ran. This
file implements it and nothing else. In particular it NEVER loads the published series, and
imports nothing that does: selection is the injection-recovery slope from
`inject_score2.py`, which compares a configuration against its own uninjected run.

Injected templates are built once and shared by every configuration, because the injection
lives in the template and the grid axes are all viper runtime flags.

Run from anywhere; it drives viper in ~/viper-src.

Usage: python scripts/injection/m36_blind_selection.py [--dry-run]
"""
import itertools
import json
import os
import re
import subprocess
import sys
import time

_ROOT = os.environ.get("EXOSAT_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
SC = os.path.join(_ROOT, "scripts", "injection")
PLAN = os.path.join(SC, "inject_plan_big.json")

VIPER = os.path.expanduser("~/viper-src")
PY = os.path.expanduser("~/viperenv/bin/python")
INJDIR = os.path.expanduser("~/inj/M36")
FTS = "lib/CRIRES/FTS/CRp_SGC2_FTStmpl-HR0p007-WN5000-10000_Hband.dat"
TPL = "M13tpl_tpl.fits"          # iteration 1: iteration 2 was chosen against the paper
TARG = "CD-35 2722"

# --- the grid, exactly as pre-registered ------------------------------------------
OSETS = ["2:20", "2:11", "11:20"]
OVERSAMPLING = [1, 2, 4]
KAPSIG = [3.0, 4.5]
TELLURIC = ["sig", "mask"]

GATE_LO, GATE_HI = 0.80, 1.20    # eligibility on recovery slope
TIE = 0.005                      # |slope-1| within this counts as a tie


def grid():
    out = []
    for i, (oset, osamp, kap, tel) in enumerate(
            itertools.product(OSETS, OVERSAMPLING, KAPSIG, TELLURIC)):
        out.append({"n": i, "arm": "M36_c%02d" % i, "oset": oset, "oversampling": osamp,
                    "kapsig": kap, "telluric": tel})
    return out


def viper(files, tag, cfg, log):
    """One viper invocation. `files` may be a glob for the whole series."""
    targ_csv = os.path.join(VIPER, tag + ".targ.csv")
    src_csv = os.path.join(VIPER, "full1.targ.csv")
    if os.path.exists(src_csv) and not os.path.exists(targ_csv):
        with open(src_csv, "rb") as a, open(targ_csv, "wb") as b:
            b.write(a.read())
    cmd = [PY, "viper.py", files, cfg["_tpl"], "-inst", "CRIRES", "-fts", FTS,
           "-targ", TARG, "-tag", tag, "-nocell",
           "-oset", cfg["oset"], "-oversampling", str(cfg["oversampling"]),
           "-kapsig", str(cfg["kapsig"]), "-telluric", cfg["telluric"]]
    with open(log, "w") as fh:
        return subprocess.call(cmd, cwd=VIPER, stdout=fh, stderr=subprocess.STDOUT)


def rvo(tag):
    return os.path.join(VIPER, tag + ".rvo.dat")


def usable(path, min_rows=2):
    return os.path.exists(path) and len(
        [ln for ln in open(path).read().splitlines() if ln.strip()]) >= min_rows


def score(arm, ref_path):
    """Recovery slope, via the project's own scorer. Returns (slope, stderr, text)."""
    out = subprocess.run([PY, os.path.join(SC, "inject_score2.py"), arm, ref_path],
                         cwd=VIPER, capture_output=True, text=True).stdout
    m = re.search(r"recovery=(-?[\d.]+)% \+- ([\d.]+)%", out)
    if not m:
        return None, None, out
    return float(m.group(1)) / 100.0, float(m.group(2)) / 100.0, out


def per_order_spread(text):
    vals = [float(v) / 100.0 for v in re.findall(r"o=\s*\d+:\s*(-?[\d.]+)%", text)]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    return (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def main():
    dry = "--dry-run" in sys.argv
    plan = json.load(open(PLAN))
    configs = grid()
    print("M36: %d configurations, %d injected epochs each" % (len(configs), len(plan)))
    print("selection = injection recovery only; the published series is never read\n")
    if dry:
        for c in configs:
            print("  %s  oset=%-6s osamp=%d kapsig=%.1f telluric=%s"
                  % (c["arm"], c["oset"], c["oversampling"], c["kapsig"], c["telluric"]))
        return

    # injected templates: built once, shared by every arm
    if not os.path.isdir(INJDIR) or len(os.listdir(INJDIR)) < len(plan):
        subprocess.check_call([PY, os.path.join(SC, "mktpl.py"), PLAN,
                               os.path.join(VIPER, TPL), INJDIR], cwd=VIPER)

    results = []
    t0 = time.time()
    for c in configs:
        c["_tpl"] = TPL
        ref_tag = c["arm"] + "ref"
        ref_path = rvo(ref_tag)
        if not usable(ref_path, min_rows=3):
            viper("cr2res_data/*.fits", ref_tag, c, "/tmp/%s.log" % ref_tag)
        if not usable(ref_path, min_rows=3):
            print("%s  REFERENCE RUN FAILED -- ineligible" % c["arm"])
            results.append(dict(c, _tpl=None, slope=None, note="reference run failed"))
            continue

        for i, p in enumerate(plan):
            tag = "%s_inj%02d" % (c["arm"], i)
            if usable(rvo(tag)):
                continue
            c["_tpl"] = os.path.join(INJDIR, "inj%02d_tpl.fits" % i)
            viper("cr2res_data/" + p["file"], tag, c, "/tmp/%s.log" % tag)
        c["_tpl"] = TPL

        slope, se, text = score(c["arm"], ref_path)
        spread = per_order_spread(text)
        eligible = slope is not None and GATE_LO <= slope <= GATE_HI
        print("%s  oset=%-6s osamp=%d kap=%.1f tel=%-4s  recovery=%s  %s"
              % (c["arm"], c["oset"], c["oversampling"], c["kapsig"], c["telluric"],
                 ("%.3f +- %.3f" % (slope, se)) if slope is not None else "  n/a  ",
                 "eligible" if eligible else "INELIGIBLE"))
        results.append({k: v for k, v in c.items() if not k.startswith("_")} |
                       {"slope": slope, "slope_err": se, "per_order_spread": spread,
                        "eligible": bool(eligible), "ref_series": ref_tag})

    ok = [r for r in results if r["eligible"]]
    print("\n%d of %d configurations eligible (gate: slope in [%.2f, %.2f])"
          % (len(ok), len(results), GATE_LO, GATE_HI))
    winner = None
    if ok:
        best = min(abs(r["slope"] - 1.0) for r in ok)
        tied = [r for r in ok if abs(r["slope"] - 1.0) <= best + TIE]
        winner = min(tied, key=lambda r: (r["per_order_spread"] if r["per_order_spread"]
                                          is not None else 9e9))
        print("winner: %s  (slope %.3f, |slope-1| %.3f, per-order spread %s)"
              % (winner["arm"], winner["slope"], abs(winner["slope"] - 1.0),
                 ("%.3f" % winner["per_order_spread"]) if winner["per_order_spread"] else "n/a"))
        if len(tied) > 1:
            print("  (%d configurations tied within %.3f; broken on per-order spread)"
                  % (len(tied), TIE))
    else:
        print("NO configuration passed the gate. Per the protocol the experiment stops here.")

    out = os.path.join(_ROOT, "data", "m36-selection.json")
    json.dump({"grid": results, "winner": winner, "gate": [GATE_LO, GATE_HI],
               "tie_break_window": TIE, "elapsed_s": round(time.time() - t0)},
              open(out, "w"), indent=2)
    print("\nwrote %s in %d s" % (os.path.relpath(out, _ROOT), time.time() - t0))
    if winner:
        print("\nNext, per protocol section 6 -- and only now:")
        print("  cd ~/viper-src && %s %s/blind_search.py %s.rvo.dat"
              % (PY, SC, winner["ref_series"]))


if __name__ == "__main__":
    main()
