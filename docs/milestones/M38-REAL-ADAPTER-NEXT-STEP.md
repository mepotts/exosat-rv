# M38 — next reduced-spectrum/template-chain adapter

**Design only, 2026-09-07.** Source inspection only: no spectra, templates, RV products,
reductions, downloads, or VIPER execution. No scientific configuration or control is selected.

## Recommendation

Implement a small **synthetic extracted-1D → actual VIPER template rebuild → held-out RV**
adapter. This replaces the centroid toy with the real fitter/template builder while keeping
inputs wholly generated. It is the shortest useful test of whether template construction
changes injected stellar velocities. It does **not** test extraction from detector images,
real CRIRES noise, or the satellite claim.

Do not run the historical batch scripts: their staging, caches, fitted templates, and
injection schedules are inappropriate for this experiment. Reuse their knowledge of the
CLI/file format, not their execution path.

## Existing contracts to reuse and gaps to close

| Source/API | Reuse | Required bridge |
|---|---|---|
| `src/exosat_rv/m38/spectral.py`: `DecomposedSpectralExposure`, `inject_stellar_velocity` | Stellar-only shift before telluric multiplication and LSF convolution; same additive noise realization | Explicit wavelength units, independent pixel uncertainties, oversampled synthesis/pixel sampling |
| `template_chain.py`: `FrozenSpectralExposure`, `ExposureSet`, `apply_pre_template_injection` | Complete epoch/order inputs; injections precede session creation | Serialize **only reconstructed observed flux**, wavelengths, errors, and declared metadata to the fitter; never feed truth stellar components to its template builder |
| `TemplateChainAdapterFactory.create_session` / `TemplateChainSession` | Fresh chain per injection, arm, and fold | Implement `initial_template`, `fit_training`, `update_template`, `adjacent_noise_scale`, `fit_evaluation` using VIPER subprocess outputs |
| `run_template_chain_ensemble` | Training/evaluation separation, iteration history, convergence and mask checks | Actual VIPER template wavelength grids, errors, and masks must be reconciled with `TemplateState`'s rectangular flux-only diagnostic representation |
| `synthetic_controls.py`: `ToyTemplateSession` | Examples of the session lifecycle only | Its pixel-centroid RV and relaxed observed-spectrum mean are not a Doppler fitter or telluric-clean template algorithm |
| `synthetic_campaign.py` | Later selection integration | `SyntheticTemplateRunConfig` binds the **toy** factory, `RVFrameTransform` declares `toy-centroid-pixel`, and `BridgeUncertaintyContract` supplies uniform toy scales. Do not relabel these as real RV uncertainties or silently plug in VIPER |

For a first adapter, use one fixed disjoint training/evaluation split. Leave-one-out folds
add independent template zero-points; their common RV frame needs an explicit physical
solution before joining them into a time series. Do not fit fold offsets to injection truth.

## Minimal synthetic input representation

Provide a caller-generated H-band order/chunk layout, with order identifiers mapped
explicitly to detector and DRS column number. Do not copy the historical preferred order set.
Each epoch/order needs:

- Vacuum wavelength grid with a declared unit; noiseless stellar spectrum, fixed topocentric
  telluric transmission, normalized LSF, and realized additive noise.
- A **separate positive uncertainty vector**: `noise` is a realization, not its sigma.
- Synthetic time, coordinate/location or explicitly controlled barycentric transformation,
  and a declared rest/topocentric/barycentric velocity convention. None come from a target.
- Synthesis grid padding beyond all requested shifts and LSF support. For the first fixture,
  use an equal-length uniform grid per order; later add irregular native pixel grids and
  wavelength-dependent LSF. The existing injection operator rejects irregular grids.

The observed-flux model remains `LSF * (S(lambda / D) * T(lambda)) + noise`. Oversample the
physical model, then integrate/sample onto the stated detector-pixel wavelength map. Keeping
sampling/noise fixed within an injected/reference pair tests paired transmission; it is not
a physical re-draw of flux-dependent photon noise. Separate noise realizations are needed
for uncertainty coverage. Never shift the composite observed spectrum: that moves tellurics.

For FITS compatibility, `scripts/m15_convert.py` documents three `CHIP1/2/3` tables with
`{DRS_order:02d}_01_SPEC`, `_ERR`, and `_WL` columns. The observation reader interprets `_WL`
in **nm and multiplies by 10**, whereas VIPER-generated `_tpl.fits` wavelengths are already
in **Angstrom**. Generate headers from explicit synthetic metadata; do not copy a real
observation header or pretend an unperformed calibration was performed. Label any compatibility
keyword describing synthetic blaze removal accordingly in the fixture documentation.

## What the actual VIPER source requires

Inspected external sources were `/home/matth/viper-src/viper.py`,
`inst/inst_CRIRES.py`, and `config_viper.ini`—read as text, never imported. Useful anchors:

- `inst_CRIRES.Spectrum` reads wavelength setting, detector columns, observation category,
  time/coordinate headers, calibration-category cards, and potentially an external blaze
  spectrum. Its non-K order mapping depends on the last column of each detector table.
  Validate the round-trip mapping for **every** requested synthetic chunk.
- `inst_CRIRES.Tpl` and `write_fits` read/write native templates. Retain native wavelength,
  flux, and error arrays; do not regard equal flux arrays on changed wavelengths as the same
  template. Use an explicitly fixed diagnostic grid for convergence, binding that grid to
  the comparison; continue fitting with the native product.
- `viper.py:588–635` builds telluric-corrected spectra and shifts them by fitted RV/BERV;
  `:952–1014` combines them. `update_template` should execute this genuine `-createtpl`
  route with the previous template, not return a shifted/averaged toy template.
- The CLI executes at module scope and uses global state. It deletes residual `.dat` files
  under its own `res` directory and writes other products. Use a dedicated, minimal runtime
  copy and private working directory; **do not execute it in the existing shared installation**.
- `-nocell` alone still reads the configured FTS before replacing its flux with unity.
  `-fts None` selects the explicit synthetic unity-cell branch. Telluric `add` reads an
  atmosphere FITS library and applies an empirical wavelength offset in source. A synthetic
  telluric fixture must account for this explicitly; no hidden real atlas/template access.
- CLI/config precedence changes defaults. Supply explicit order/pixel ranges, template mode,
  normalization/wavelength/background degrees, weighting, clipping including
  `-kapsig_ctpl`, IP settings, oversampling, RV guess, and telluric/cell treatment.
  `config_viper.ini` spells one template-clipping key `kapsig_cptl`; do not assume it controls
  the differently spelled command argument.
- `.rvo.dat` contains named per-order RV/error pairs and filenames. Rows can be absent when
  all orders fail. Parse identities and completeness, not positional row assumptions or just
  the printed overall RV. Internal fitted velocities use km/s; output RVs use m/s.

The native template's `ERR` is computed as an across-input scatter in the inspected builder.
It is not automatically the uncertainty of adjacent template differences: iterations reuse
the same observations. The adapter must not supply it unchanged as a calibrated convergence
noise scale. A deterministic numerical tolerance is sufficient for an initial noiseless
engineering fixture, but a later noise-scale estimate needs simulation-based validation.

## Bounded first implementation and independent tests

1. Add a pure synthetic FITS writer/reader-contract test, plus argv and output parsers. Start
   with several generated stellar lines, unity telluric transmission, fixed known wavelength
   solution, a simple LSF, and one disjoint fold. Fixing wavelength is essential for this
   first no-telluric test: freely shifting both stellar RV and wavelength solution is degenerate.
2. Implement the session around a fresh VIPER runtime, reconstructing its initial template
   from **training observations only**, then rebuilding and refitting until the chosen
   engineering stopping criterion. Run reference and positive/negative/zero injection cases
   from iteration zero. Retain per-order outputs and native template products.
3. Demonstrate sign and nm/Angstrom conversion against analytic line positions evaluated
   independently of `shift_stellar_component`; compare a fixed-known-template fit with the
   learned-template chain. Test subpixel and larger shifts, multiple noise seeds, and a
   deliberately wrong sign/unit mapping. A paired slope alone must not hide an incorrect
   reference series.
4. Add generated telluric lines in a dedicated synthetic atmosphere fixture, first with a
   known wavelength map, then with fitted wavelength coefficients. Verify telluric centroids
   remain fixed while stellar lines move. Test asymmetric LSF, varying telluric depth, and
   star/telluric overlap. The matched simulator/fitter case is only a baseline; include
   independent synthesis/interpolation and controlled model mismatch to avoid a closed-loop
   self-confirmation.
5. Perturb a held-out epoch and verify every training-template product is unchanged; perturb
   a training epoch and verify reconstruction actually responds. Check template-grid/mask
   drift, missing RV rows, lost orders, malformed outputs, and nonconvergence fail explicitly.

**Deliverable of the first slice:** a reproducible synthetic reduced-1D template-transmission
test using the actual VIPER implementation, with measured errors and stated limitations.
Not a real-control pass, a detector-level injection, a calibrated adaptive selection study,
or authority to run the science target. A detector-raw extension would additionally model
spatial trace/PSF, blaze/throughput, detector sampling and noise, nod subtraction, and the
cr2res extraction/calibration chain; this adapter deliberately does not simulate those steps.

### External source fingerprints inspected

| File | SHA-256 |
|---|---|
| `viper.py` | `cf000bc57cc5dfbd3a193cc0bc4f6a00ee26376225783c759310910cb6508fc4` |
| `inst/inst_CRIRES.py` | `4587947f658be331d08112d5f450b103859e7bf6d0005f641eea44a1fcd6696c` |
| `config_viper.ini` | `24c1a73fbfe07dc26cdaa35387fb03eb7c0a455e0b1c871f57d30c2a834bd2c6` |

These identify inspected source state, not a complete executable environment or historical
science execution. No external library data were inspected.
