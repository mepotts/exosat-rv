"""M35 / NEXT-DIRECTIONS B2: Gaia DR3 astrometry for every host on the roster.

An unseen companion perturbs its host's astrometry. Gaia DR3 publishes three handles on
that -- RUWE, the astrometric excess noise and its significance -- plus a flag saying
whether the source appears in the non-single-star tables at all. For a satellite claim
resting on radial velocities, an independent astrometric statement about the *host* is a
cheap systematics defence, and it strengthens the null results as much as the detection.

The query is a plain ra/dec box, not CONTAINS. DATA-SOURCES.md records that trap for ESO;
it bites on TAPVizieR too -- the CONTAINS form returns HTTP 400 here while the box works.
And it is ONE batched query rather than one per target: thirty-one separate round trips ran
for over half an hour without finishing, while the batched form returns in seconds.

Nothing is interpreted for you beyond what Gaia says. The conventional RUWE cut is 1.4,
but this file does not cite a source for it, because no citation was verified while writing
it, and this project has shipped fifteen unverified references already. Read the numbers.

Usage: python scripts/m35_gaia_astrometry.py [--out data/m35-gaia.json]
"""
import io
import json
import math
import os
import sys
import urllib.parse
import urllib.request

_ROOT = os.environ.get("EXOSAT_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
GAIA = '"I/355/gaiadr3"'
UA = {"User-Agent": "exosat-rv/0.1 (mailto:matthew.e.potts@gmail.com)"}
BOX_DEG = 0.0056                    # 20 arcsec: companions sit 0.5-3 arcsec from the host
COLS = "Source, RA_ICRS, DE_ICRS, Plx, e_Plx, Gmag, RUWE, epsi, sepsi, NSS, VarFlag"


def tap(query, timeout=300):
    data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL",
                                   "FORMAT": "json", "QUERY": query}).encode()
    req = urllib.request.Request(TAP, data=data, headers=dict(UA))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8"))
    names = [c["name"] for c in j["metadata"]]
    return [dict(zip(names, row)) for row in j["data"]]


def sep_arcsec(ra1, de1, ra2, de2):
    dra = (ra1 - ra2) * math.cos(math.radians(0.5 * (de1 + de2)))
    return 3600.0 * math.hypot(dra, de1 - de2)


def roster():
    """Every roster target that carries coordinates."""
    path = os.path.join(_ROOT, "data", "m5-targets.json")
    out = []
    for t in json.load(io.open(path, encoding="utf-8")):
        ra, dec = t.get("ra_deg"), t.get("dec_deg")
        if ra is None or dec is None or ra != ra or dec != dec:
            continue                                  # NaN coordinates: nothing to query
        out.append((t.get("simbad_id") or t["eso_object"], float(ra), float(dec)))
    return out


def fmt(value, spec):
    return (spec % value) if isinstance(value, (int, float)) else "%*s" % (len(spec % 0), "--")


def main():
    out_path = os.path.join(_ROOT, "data", "m35-gaia.json")
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    def say(*a):
        stdout.write(" ".join(str(x) for x in a) + os.linesep.replace("\r", ""))

    targets = roster()
    boxes = []
    for _, ra, dec in targets:
        dra = BOX_DEG / math.cos(math.radians(dec))
        boxes.append("(RA_ICRS BETWEEN %.6f AND %.6f AND DE_ICRS BETWEEN %.6f AND %.6f)"
                     % (ra - dra, ra + dra, dec - BOX_DEG, dec + BOX_DEG))
    rows = tap("SELECT %s FROM %s WHERE %s" % (COLS, GAIA, " OR ".join(boxes)))

    say("# M35 / B2 -- Gaia DR3 astrometric quality for the roster hosts")
    say("# one batched cone query; adopted host = nearest source with a parallax within 20 arcsec")
    say("# RUWE near 1.0 means the single-star astrometric model fits. NSS is Gaia's [0/7]")
    say("# flag for the non-single-star tables; 0 = no orbital/acceleration/SB solution.")
    say("")
    say("%-24s %6s %7s %7s %6s %7s %6s %4s %s"
        % ("target", "sep\"", "G", "plx", "RUWE", "epsi", "sig", "NSS", "var"))
    say("-" * 98)

    results = []
    for name, ra, dec in targets:
        near = []
        for r in rows:
            d = sep_arcsec(ra, dec, r["RA_ICRS"], r["DE_ICRS"])
            if d <= BOX_DEG * 3600:
                near.append(dict(r, sep_arcsec=d))
        withplx = [r for r in near if r.get("Plx") is not None]
        host = min(withplx, key=lambda r: r["sep_arcsec"]) if withplx else None
        results.append({"target": name, "query_ra_deg": ra, "query_dec_deg": dec,
                        "n_gaia_sources_in_box": len(near), "host": host,
                        "all_sources": near})
        if host is None:
            say("%-24s %6s  no Gaia source carrying a parallax in the box (%d source(s))"
                % (name[:24], "--", len(near)))
            continue
        say("%-24s %6.2f %7s %7s %6s %7s %6s %4s %s" % (
            name[:24], host["sep_arcsec"],
            fmt(host["Gmag"], "%7.3f"), fmt(host["Plx"], "%7.2f"),
            fmt(host["RUWE"], "%6.3f"), fmt(host["epsi"], "%7.3f"),
            fmt(host["sepsi"], "%6.1f"),
            host["NSS"] if host["NSS"] is not None else "--",
            host["VarFlag"] or "--"))

    io.open(out_path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    say("")
    say("wrote %s (%d targets, %d Gaia rows)"
        % (os.path.relpath(out_path, _ROOT), len(results), len(rows)))


if __name__ == "__main__":
    main()
