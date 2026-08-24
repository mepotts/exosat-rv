"""M35 / NEXT-DIRECTIONS B1: is there a ~171 d PHOTOMETRIC period in CD-35 2722?

The satellite claim rests on a radial-velocity period near 171 d measured on the companion.
The host is 2.8" away, this project has already measured slit contamination from it, and a
rotating spotted star imprints its rotation period on any contaminated spectrum. So if the
host varies photometrically at ~171 d, the satellite has an activity explanation. If it does
not, that is an independent systematics defence -- and a referee will ask for it either way.

ASAS-SN covers this declination with a 3900 d baseline, which is 23 cycles of the period in
question, and needs no account. Two things are done in the project's own idiom rather than
with an analytic false-alarm probability:

  * significance is PERMUTATION-calibrated, exactly as m28_nullcal.py argues for the RV
    search -- the analytic FAP charges for parameters, not for searching 4000 periods;
  * the non-detection is turned into a LIMIT by INJECTION RECOVERY, because a null with no
    amplitude attached says nothing about whether the test could have seen anything.

The V and g eras are treated separately throughout. ASAS-SN changed filter in 2018 and the
zero-point step between the eras is exactly the kind of thing that manufactures power at
long periods; combining them would put a step function into a period search.

Usage: python scripts/m35_asassn_photometry.py [--refetch]
"""
import io
import json
import os
import sys

import numpy as np

_ROOT = os.environ.get("EXOSAT_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

RA, DEC = 92.3300338228, -35.82529604851      # config.py, [TAP] SIMBAD
P_RV = 171.454                                # the period under test (M30 §, M14)
CACHE = os.path.join(_ROOT, "data", "m35-asassn-cd35.csv")
OUT = os.path.join(_ROOT, "data", "m35-photometry.json")
PMIN, PMAX_CAP = 2.0, 2000.0   # the real cap is the baseline; see bounded_pmax()
N_PERM = 500
RNG = np.random.default_rng(20260824)


def fetch(refetch=False):
    if os.path.exists(CACHE) and not refetch:
        import csv
        rows = list(csv.DictReader(io.open(CACHE, encoding="utf-8")))
        return ([float(r["jd"]) for r in rows], [float(r["mag"]) for r in rows],
                [float(r["mag_err"]) for r in rows], [r["phot_filter"] for r in rows],
                [int(r["asas_sn_id"]) for r in rows])
    import warnings
    warnings.filterwarnings("ignore")
    from pyasassn.client import SkyPatrolClient
    client = SkyPatrolClient()
    lcs = client.cone_search(ra_deg=RA, dec_deg=DEC, radius=0.02, catalog="master_list",
                             download=True, threads=2)
    df = lcs.data
    # the two ids that sit on the target (~1"); the third is 40" away and is a different star
    sep = {}
    for aid, g in df.groupby("asas_sn_id"):
        sep[aid] = 3600.0 * np.hypot((g["ra_deg"].iloc[0] - RA) * np.cos(np.radians(DEC)),
                                     g["dec_deg"].iloc[0] - DEC) if "ra_deg" in g else np.nan
    keep = df[df["quality"] == "G"]
    keep = keep[(keep["mag_err"] > 0) & (keep["mag_err"] < 0.5)]
    keep.to_csv(CACHE, index=False,
                columns=["asas_sn_id", "jd", "mag", "mag_err", "phot_filter", "camera"])
    return (list(keep["jd"]), list(keep["mag"]), list(keep["mag_err"]),
            list(keep["phot_filter"]), list(keep["asas_sn_id"]))


def bounded_pmax(t):
    """Half the baseline: two full cycles minimum.

    This note's own section 5.3 is about exactly this. Searching a 41 d series out to 460 d
    manufactured a dBIC = +9.3 entry at ~171 d in this project's own table. An unbounded grid
    here produced 'best' periods of 1250-1580 d against baselines of 1609 and 2439 d, which is
    the same defect wearing a different hat -- so the grid is bounded and the earlier numbers
    are not used.
    """
    return min(PMAX_CAP, (t.max() - t.min()) / 2.0)


def periodogram(t, y, dy):
    from astropy.timeseries import LombScargle
    ls = LombScargle(t, y, dy)
    freq = np.linspace(1.0 / bounded_pmax(t), 1.0 / PMIN, 60000)
    power = ls.power(freq)
    return ls, freq, power


def analyse(t, y, dy, label, results):
    t, y, dy = np.asarray(t, float), np.asarray(y, float), np.asarray(dy, float)
    ok = np.isfinite(t) & np.isfinite(y) & np.isfinite(dy) & (dy > 0)
    t, y, dy = t[ok], y[ok], dy[ok]
    if len(t) < 50:
        print("%-12s only %d epochs -- skipped" % (label, len(t)))
        return
    y = y - np.median(y)
    ls, freq, power = periodogram(t, y, dy)

    i_best = int(np.argmax(power))
    p_best, pw_best = 1.0 / freq[i_best], power[i_best]
    pw_at_rv = float(ls.power(np.array([1.0 / P_RV]))[0])

    # permutation null: keep the sampling, destroy time coherence, rebuild max-power
    maxes = np.empty(N_PERM)
    at_rv = np.empty(N_PERM)
    for k in range(N_PERM):
        perm = RNG.permutation(len(y))
        lsp = type(ls)(t, y[perm], dy[perm])
        maxes[k] = lsp.power(freq).max()
        at_rv[k] = lsp.power(np.array([1.0 / P_RV]))[0]
    p_global = float((maxes >= pw_best).mean())
    p_at_rv = float((at_rv >= pw_at_rv).mean())

    # injection recovery: what amplitude at P_RV would this sampling have caught?
    thresh = float(np.quantile(at_rv, 0.99))
    detected = None
    for amp_mmag in (2, 3, 5, 7, 10, 15, 20, 30, 50):
        amp = amp_mmag / 1000.0
        rec = []
        for k in range(30):
            phase = RNG.uniform(0, 2 * np.pi)
            yi = y + amp * np.sin(2 * np.pi * t / P_RV + phase)
            rec.append(type(ls)(t, yi, dy).power(np.array([1.0 / P_RV]))[0] >= thresh)
        if np.mean(rec) >= 0.9:
            detected = amp_mmag
            break

    print("%-12s n=%-5d baseline=%.0f d  grid<=%.0f d  best P=%9.3f d (power %.3f, perm p=%.3f)"
          % (label, len(t), t.max() - t.min(), bounded_pmax(t), p_best, pw_best, p_global))
    print("%-12s power at %.3f d = %.4f, permutation p = %.3f   %s"
          % ("", P_RV, pw_at_rv, p_at_rv,
             "DETECTION" if p_at_rv < 0.01 else "no detection"))
    print("%-12s injection: %s"
          % ("", ("%d mmag recovered at 90%%" % detected) if detected
             else "not recovered even at 50 mmag"))
    results.append({
        "series": label, "n_epochs": len(t), "baseline_days": float(t.max() - t.min()),
        "best_period_days": float(p_best), "best_power": float(pw_best),
        "grid_max_period_days": float(bounded_pmax(t)),
        "best_permutation_p": p_global, "power_at_rv_period": pw_at_rv,
        "permutation_p_at_rv_period": p_at_rv,
        "injection_limit_mmag": detected, "rv_period_days": P_RV,
        "n_permutations": N_PERM,
    })


def main():
    jd, mag, err, filt, aid = fetch("--refetch" in sys.argv)
    jd = np.asarray(jd, float); mag = np.asarray(mag, float)
    err = np.asarray(err, float); filt = np.asarray(filt); aid = np.asarray(aid)

    # adopt the ASAS-SN id closest to the target; the third source in the cone is 40" away
    ids, counts = np.unique(aid, return_counts=True)
    print("# M35 / B1 -- ASAS-SN photometry of CD-35 2722 (the HOST), tested at %.3f d" % P_RV)
    print("# ids in the cone: %s" % ", ".join("%d (n=%d)" % (i, c) for i, c in zip(ids, counts)))
    print()

    results = []
    for target_id in ids:
        for f in ("V", "g"):
            m = (aid == target_id) & (filt == f)
            if m.sum() >= 50:
                analyse(jd[m], mag[m], err[m], "%d/%s" % (target_id, f), results)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(
        json.dumps(results, indent=2) + "\n")
    print("\nwrote %s" % os.path.relpath(OUT, _ROOT))


if __name__ == "__main__":
    main()
