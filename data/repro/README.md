# Reproducibility evidence bundle

This directory freezes the small, load-bearing VIPER products used by the downstream
CD-35 2722 B and eta Tel B analyses.  Before M37 these files lived only in
`~/viper-src`, so a repository clone could inspect the exported plots and summaries but
could not rerun their source calculations.

## Included

For each adopted series, `viper/results/` contains:

- `*.rvo.dat`: one row per fitted spectrum, with BJD, combined RV, BERV, and the RV and
  uncertainty from each selected detector-order segment;
- `*.par.dat`: one row per fitted segment, retaining the fitted wavelength, line-spread,
  telluric, background, normalization, and RV parameters; and
- `*.targ.csv`: the target metadata sidecar passed to VIPER.

The four series are `M14_NODT2` (CD-35 2722 B, per nod), `M14_T2` (CD-35 2722 B,
per epoch), `E15_NOD` (eta Tel B, per nod), and `E15_R2` (eta Tel B, per epoch).
`viper/config_viper.ini` is the configuration from the audited checkout, and
`viper/viper-tracked.patch` records the two tracked local modifications found on top of VIPER
commit `e8b22fa7489a9357e3b1936c54d54f86313dc129` during the audit. The earlier runs did not
record when those changes or the current configuration were applied, so this is the audited
checkout state, not proof of its historical timing.

[`manifest.json`](manifest.json) records every included file's byte count and SHA-256
digest.  It also records hashes for the three fitted templates and H-band FTS atlas that
remain external.  Verify all included bytes offline with:

```bash
python scripts/m37_package_evidence.py --verify
```

To rebuild the bundle from the audited external checkout, use:

```bash
~/viperenv/bin/python scripts/m37_package_evidence.py --viper-root ~/viper-src
```

The packager fails if the VIPER commit, tracked patch, or any scientific input differs
from the audited hashes.

## Scope boundary

This bundle makes downstream calculations from the adopted RV/per-order tables rerunnable.
It does **not** make the project raw-to-RV reproducible: ESO exposures, CR2RES reduction
products, and fitted-template FITS files are not redistributed here.  The manifest can
confirm the identity of an external template or FTS file but cannot reconstruct one.
Likewise, neither the historical Python environment nor an immutable snapshot of every
effective extraction setting was captured at run time; no current environment or checkout is
presented as if it were that missing record.

Those boundaries matter when interpreting “reproduce”: this directory supports a
content-bound replay of the downstream statistics under the code and software versions
recorded by each audit artifact, not an independent re-extraction of the spectra. Exact output
bytes across different numerical-library/platform builds are not promised.
