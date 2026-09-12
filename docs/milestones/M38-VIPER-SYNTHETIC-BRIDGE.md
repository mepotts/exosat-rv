# M38 — generated spectra through the actual VIPER template builder

**Engineering development, 2026-09-12; not a scientific protocol pass.** The first
reduced-1D bridge in the [implementation plan](M38-REAL-ADAPTER-NEXT-STEP.md) now executes
actual VIPER template construction and RV fitting. It is a standalone fixed-step probe,
**not yet a production `TemplateChainAdapter` or a converged template-selection experiment**.
No target spectra, fitted science templates, atlas, published RVs, or historical batch
drivers were opened or executed. M37's scientific qualifications are unchanged.

## What ran

The caller generates eleven analytic Gaussian stellar lines on a 2,048-pixel uniform
1550–1554 nm grid, with eight-point pixel integration and analytically combined stellar
and Gaussian LSF widths. Telluric transmission and blaze are unity. This analytic synthesis
does not call the project's interpolation injection operator or VIPER's spectral model.
Three duplicate generated chip tables exercise the CRIRES reader layout; **only order 0
is fitted**, so these are not three independent spectral chunks or controls.

Fictitious coordinate RA=90°, Dec=0°, UTC 2020-01-01, and CRIRES's geodetic location give
a reproducible Astropy barycentric correction. These are engineering metadata, not target
epochs. Input wavelengths are nm; native template wavelengths are Angstrom. The analytic
stellar Doppler factor is `1+v/c`; the expected VIPER log-velocity is `c*log1p(v/c)`.
The builder's classical shifting convention differs from the fitter's logarithmic one;
absolute residuals below deliberately include interpolation/model and template-gauge error.

Each case starts in a fresh source-only runtime and uses three training velocities
[-300, -100, 400] m/s and four held-out velocities [-1200, -150, 150, 1200] m/s.
The positive case adds [-100, 0, 100] m/s to training and [-200, -30, 30, 200] m/s to
evaluation; the negative case subtracts these. The isolation case perturbs only the last
held-out velocity by +400 m/s. Two additional reference cases use independent additive
Gaussian noise seeds 1847/1848 and sigma=0.0001 normalized flux. Noiseless cases supply
sigma=0.0001 as a numerical fitting weight, not claimed physical uncertainty.

VIPER first builds from training observations **without any stellar truth template**, then
executes three actual `-createtpl` rebuilds using the previous native template. Evaluation
files are excluded from every builder glob. After learned-template evaluation, a separate
known-rest-template arm checks absolute sign and scale. The known template never enters
the learned chain. Native grids and finite-flux masks must remain unchanged; missing rows,
lost orders, nonfinite RVs, and nonpositive fitted per-order errors stop the run.

Wavelength and IP parameters are fixed, telluric/cell inputs disabled, and the already
convolved template is kept outside the LSF convolution. All effective fitting settings,
subprocess commands, per-order rows, source digests, and native-template digests are retained
in the [JSON evidence](../evidence/m38-viper-synthetic-bridge-2026-09-12.json).

## Results

<!-- BEGIN GENERATED VIPER BRIDGE -->

| Case | Max absolute learned-template residual (m/s) | Max absolute known-template residual (m/s) | Final adjacent flux change |
|---|---:|---:|---:|
| `reference` | 0.521157 | 0.002407 | 2.69630082e-06 |
| `zero_repeat` | 0.521157 | 0.002407 | 2.69630082e-06 |
| `positive` | 0.627834 | 0.002051 | 2.59314128e-07 |
| `negative` | 0.057016 | 0.001985 | 6.79982528e-06 |
| `heldout_perturb` | 0.521157 | 0.002407 | 2.69630082e-06 |
| `noise_1847` | 0.448101 | 0.262288 | 2.8266642e-06 |
| `noise_1848` | 0.854257 | 0.230193 | 2.847998e-06 |

Every retained native template wavelength/flux/scatter array is bitwise identical
between `reference`, `zero_repeat`, and `heldout_perturb` at all four stages.
Perturbing the training velocities changes the reconstructed template.

| Paired injection case | Slope (with intercept) | Intercept (m/s) |
|---|---:|---:|
| `positive` | 0.999997205 | 0.107732 |
| `negative` | 1.000007671 | -0.573582 |

Paired slopes use expected log-velocity differences, consistently with the absolute residuals.
These four-epoch paired slopes are engineering summaries, not calibrated recovery
intervals. Template zero-point shifts are shown as intercepts, not fitted away
from the absolute-residual table. Two noise seeds do not establish uncertainty coverage.

Retained evidence SHA-256: `21dbe7802fd60dc9bc32f83c827adccc611898921ec5f759688db869ec3f9fff`.

<!-- END GENERATED VIPER BRIDGE -->

## Retained failures and compatibility boundary

Initial setup attempts stopped on missing gnuplot, then on synthetic compatibility headers
that VIPER's writer deletes unconditionally. The input writer now explicitly labels unity
blaze and generated headers; no real calibration is impersonated. The native writer also
hardcodes 2,048 values for unfitted chips, which establishes this fixture's pixel count.
The launch wrapper installs an explicit no-op **plotting-only** module and disables Astropy
IERS downloads. Numerical VIPER source remains unchanged. This is source-inspected process
isolation, **not an OS access-control sandbox**; the external runtime is trusted code.

The original noiseless training fixture [-300, 0, 300] m/s produced an infinite covariance
error at its almost-zero-RV middle epoch. The parser rejected it. Changing the numerical RV
starting guess from 0 to 1 km/s did not solve that case. The successful fixture above avoids
that exact-zero training epoch; this is an explicitly development-tuned fixture change,
not evidence that zero-velocity or noisy near-zero fitting is generally reliable. The
independent audit retains the failed rows/log hashes and replay checks separately.

The [independent coding-agent audit](../evidence/m38-viper-bridge-audit-2026-09-12.json)
records those failures, source/native-product rehashes, an independent reference replay,
environment versions, and adversarial tests. It is engineering review, not independent
human protocol governance or validation of an observational control.

## Reproduction and remaining work

From the checkout, with Astropy/SciPy/NumPy and the inspected external VIPER source available:

```bash
PYTHONPATH=src:. python -m scripts.m38_viper_synthetic_bridge \
  --viper-source /path/to/viper --output /fresh/private/experiment
PYTHONPATH=src:. python -m scripts.m38_render_viper_bridge --check
```

The first command creates only generated spectra and a fresh source-allowlisted runtime.
It refuses an existing output directory. No external observational/library files are copied.
The source allowlist and hashes identify the locally patched VIPER source, not an unmodified
upstream release. Generated FITS/runtime/log products remain in private ignored scratch;
small numerical evidence is retained in Git. VIPER writes a creation timestamp into native
FITS: full-file hashes differ on rerun, while the retained native-array hashes are the
deterministic replay/isolation comparison. Nothing was deleted from the shared installation.

Next: diagnose the near-zero covariance failure, add real synthetic telluric/mask fixtures,
asymmetric LSF and wavelength/model mismatch, multiple chunks and irregular grids; wire the
native products into the existing template-chain contracts with a reviewed convergence rule
and physically justified RV frame. Final adjacent changes are **not** asserted to satisfy
convergence, and template scatter is not used as a calibrated convergence uncertainty.
Broader repeated-noise/selection coverage and observational control truth remain separate
requirements. The reviewed protocol freeze and independent governance must still precede
any target stage. This test neither validates detector extraction nor confirms a satellite.
