"""Engineering-only generated 1-D spectra → real VIPER template-builder bridge.

Not a production TemplateChainAdapter, convergence policy, or target-data loader. The
external executable is trusted inspected code, not OS-sandboxed by this module. Only a
source allowlist is copied; no external spectra, templates, or atmosphere libraries are.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

C_MPS = 299792458.0
SOURCE_FILES = (
    "viper.py",
    "vpr.py",
    "config_viper.ini",
    "inst/inst_CRIRES.py",
    "inst/readmultispec.py",
    "inst/airtovac.py",
    "inst/FTS_resample.py",
    "utils/param.py",
    "utils/convert_output.py",
    "utils/pause.py",
    "utils/model.py",
    "utils/targ.py",
    "utils/hbox.py",
    "utils/gplot.py",
    "utils/wstat.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_runtime(source: Path, destination: Path) -> dict[str, str]:
    """Create a fresh source-only runtime; refuse symlinks or an existing destination."""
    source, destination = source.resolve(), destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("runtime destination must be fresh")
    manifest = {}
    for name in SOURCE_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError(f"missing or unsafe runtime source: {name}")
        manifest[name] = sha256(path)
    destination.mkdir(parents=True)
    for name in SOURCE_FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
        if sha256(target) != manifest[name]:
            raise ValueError("runtime changed during copy")
    (destination / "synthetic-runtime.json").write_text(
        json.dumps(
            {"source": str(source), "destination": str(destination.resolve()), "sha256": manifest},
            sort_keys=True,
        )
    )
    return manifest


def synthetic_berv_mps() -> float:
    """Same explicit fictitious coordinate/date as the fixture FITS reader uses."""
    import astropy.units as u
    from astropy.coordinates import EarthLocation, SkyCoord
    from astropy.time import Time
    from astropy.utils import iers

    iers.conf.auto_download = False
    location = EarthLocation.from_geodetic(
        lon=-70.4045 * u.deg, lat=-24.6268 * u.deg, height=2648 * u.m
    )
    return float(
        SkyCoord(ra=90 * u.deg, dec=0 * u.deg)
        .radial_velocity_correction(
            obstime=Time("2020-01-01T00:00:00", scale="utc"), location=location
        )
        .to_value(u.m / u.s)
    )


def analytic_flux(wavelength_nm: np.ndarray, velocity_mps: float, berv_mps: float) -> np.ndarray:
    """Analytic Gaussian stellar lines: positive velocity is a redshift.

    Classical wavelength Doppler factor, independently evaluated (not the project
    interpolation injection operator). Gaussian stellar width 2.5 km/s and Gaussian
    LSF width 1.5 km/s combine analytically. Eight-point detector-pixel integration;
    unity tellurics. Independent from VIPER's log-shift/discrete interpolation model.
    """
    wavelength_nm = np.asarray(wavelength_nm, dtype=float)
    if (
        wavelength_nm.ndim != 1
        or wavelength_nm.size < 2
        or not np.isfinite(wavelength_nm).all()
        or np.any(np.diff(wavelength_nm) <= 0)
        or not np.isfinite([velocity_mps, berv_mps]).all()
        or abs(velocity_mps) > 10000
        or abs(berv_mps) > 100000
    ):
        raise ValueError("invalid synthetic wavelength or velocity")
    spacing = np.diff(wavelength_nm)
    if not np.allclose(spacing, spacing[0], rtol=1e-8, atol=1e-10):
        raise ValueError("engineering fixture requires a uniform grid")
    centers = np.array(
        [
            1550.24,
            1550.57,
            1550.91,
            1551.31,
            1551.72,
            1552.04,
            1552.41,
            1552.78,
            1553.16,
            1553.54,
            1553.83,
        ]
    )
    depths = np.array([0.2, 0.35, 0.25, 0.4, 0.3, 0.2, 0.4, 0.3, 0.25, 0.4, 0.25])
    doppler = (1 + velocity_mps / C_MPS) / (1 + berv_mps / C_MPS)
    sigma = centers * np.hypot(2500.0, 1500.0) / C_MPS
    pixels = wavelength_nm[:, None] + spacing[0] * ((np.arange(8) + 0.5) / 8 - 0.5)
    flux = np.ones_like(pixels)
    for center, depth, width in zip(centers, depths, sigma, strict=True):
        flux -= (
            depth
            * 2500
            / np.hypot(2500.0, 1500.0)
            * np.exp(-0.5 * ((pixels - center * doppler) / (width * doppler)) ** 2)
        )
    return flux.mean(axis=1)


def write_synthetic_fits(
    path: Path,
    wavelength_nm: np.ndarray,
    flux: np.ndarray,
    sigma: np.ndarray,
    *,
    template: bool = False,
) -> None:
    """Serialize observed arrays only. Three generated chips map order 0/1/2 to 1/2/3.

    All chips deliberately duplicate one artificial chunk for reader mapping tests;
    the runner fits order 0 only and never treats them as independent information.
    Template mode writes wavelength in Angstrom, input mode in nm.
    """
    from astropy.io import fits

    wave, flux, sigma = [np.asarray(value, dtype=float) for value in (wavelength_nm, flux, sigma)]
    if (
        wave.ndim != 1
        or wave.size < 128
        or flux.shape != wave.shape
        or sigma.shape != wave.shape
        or not np.isfinite([wave, flux, sigma]).all()
        or np.any(np.diff(wave) <= 0)
        or np.any(sigma <= 0)
        or np.any(wave < 1400)
        or np.any(wave > 1800)
    ):
        raise ValueError("invalid synthetic H-band arrays (wavelength must be nm)")
    if template != path.name.endswith("_tpl.fits"):
        raise ValueError("template suffix and unit mode must agree")
    hdr = fits.Header()
    hdr["OBJECT"] = "GENERATED_ENGINEERING_FIXTURE_NOT_AN_OBSERVATION"
    hdr["HIERARCH ESO INS WLEN ID"] = "H_SYNTHETIC"
    hdr["HIERARCH ESO PRO CATG"] = "SYNTHETIC_1D"
    hdr["HIERARCH ESO PRO REC1 CAL1 CATG"] = "CAL_FLAT_EXTRACT_1D"
    hdr["COMMENT"] = "Synthetic unity blaze. Compatibility keyword, not a real calibration."
    hdr["DATE-OBS"] = "2020-01-01T00:00:00"
    hdr["UTC"], hdr["LST"], hdr["ARCFILE"] = 0.0, 0.0, "GENERATED"
    hdr["HIERARCH ESO PRO DATANCOM"] = 1
    hdr["HIERARCH ESO PRO REC1 PIPE ID"] = "synthetic_generator_not_DRS"
    hdr["RA"], hdr["DEC"] = 90.0, 0.0
    hdus = [fits.PrimaryHDU(header=hdr)]
    for detector in (1, 2, 3):
        columns = [
            fits.Column(name="01_01_SPEC", format="D", array=flux),
            fits.Column(name="01_01_ERR", format="D", array=sigma),
            fits.Column(
                name="01_01_WL",
                format="D",
                unit="Angstrom" if template else "nm",
                array=wave * (10 if template else 1),
            ),
        ]
        hdus.append(fits.BinTableHDU.from_columns(columns, name=f"CHIP{detector}.INT1"))
    fits.HDUList(hdus).writeto(path, overwrite=False)


def parse_rvo(
    path: Path,
    expected_filenames: tuple[str, ...],
    orders: tuple[int, ...] = (0,),
    *,
    initial: bool = False,
) -> dict:
    """Fail closed on missing rows/order pairs, duplicate identities, and invalid fits."""
    if not expected_filenames or len(set(expected_filenames)) != len(expected_filenames):
        raise ValueError("expected identities must be nonempty and unique")
    lines = path.read_text().splitlines()
    if not lines:
        raise ValueError("empty RVO")
    header = lines[0].split()
    required = [
        "BJD",
        "RV",
        "e_RV",
        "BERV",
        *[item for order in orders for item in (f"rv{order}", f"e_rv{order}")],
        "filename",
    ]
    if header != required:
        raise ValueError("unexpected RVO columns")
    rows = {}
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != len(header):
            raise ValueError("malformed RVO row")
        name = fields[-1]
        if name not in expected_filenames or name in rows:
            raise ValueError("unexpected or duplicate RVO identity")
        numbers = np.asarray(fields[:-1], dtype=float)
        if not np.isfinite(numbers).all():
            raise ValueError("nonfinite RVO output")
        errors = numbers[5::2]
        if np.any(errors < 0 if initial else errors <= 0):
            raise ValueError("invalid per-order RV uncertainty")
        rows[name] = dict(zip(header[:-1], numbers.tolist(), strict=True))
    if set(rows) != set(expected_filenames):
        raise ValueError("missing RVO identities")
    return rows


def native_template(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keep the actual native grid, finite-mask and scatter, including masked edges."""
    from astropy.io import fits

    with fits.open(path) as hdus:
        arrays = tuple(
            np.array(hdus[1].data[f"01_01_{column}"], dtype=float)
            for column in ("WL", "SPEC", "ERR")
        )
    wave, flux, error = arrays
    if (
        wave.ndim != 1
        or wave.size < 128
        or not np.isfinite(wave).all()
        or np.any(np.diff(wave) <= 0)
        or np.any(wave < 14000)
        or np.any(wave > 18000)
        or np.isinf(flux).any()
        or np.isinf(error).any()
        or np.sum(np.isfinite(flux)) < wave.size * 0.8
        or np.any(error[np.isfinite(error)] < 0)
    ):
        raise ValueError("malformed native template or incorrect Angstrom grid")
    return arrays


def viper_argv(
    runtime: Path, inputs: Path, tag: Path, template: Path | None, *, rebuild: bool
) -> list[str]:
    """Explicit numerical fixture settings, with no remote target or library lookup."""
    argv = [sys.executable, str(runtime / "viper.py"), str(inputs / "*.fits")]
    if template is not None:
        argv.append(str(template))
    argv += [
        "-inst",
        "CRIRES",
        "-tag",
        str(tag),
        "-fts",
        "None",
        "-nocell",
        "-telluric",
        "",
        "-oset",
        "0",
        "-iset",
        "0:2048",
        "-chunks",
        "1",
        "-deg_norm",
        "0",
        "-deg_wave",
        "1",
        "-deg_bkg",
        "0",
        "-fix",
        "wave",
        "ip",
        "-ip",
        "g",
        "-iphs",
        "20",
        "-oversampling",
        "4",
        "-rv_guess",
        "1",
        "-wgt",
        "error",
        "-kapsig",
        "0",
        "-kapsig_ctpl",
        "0",
        "-vcut",
        "10",
        "-tpl_is_conv",
        "1",
        "-tpl_wave",
        "berv",
        "-tpl_noRV",
        "0",
        "-tellshift",
        "0",
        "-tsig",
        "1",
        "-demo",
        "0",
        "-output_format",
        "dat",
    ]
    if rebuild:
        argv += ["-createtpl", "1"]
    return argv


def execute_viper(
    runtime: Path, inputs: Path, output: Path, template: Path | None, *, rebuild: bool
) -> dict:
    """Execute in a fresh private work directory, retaining argv, log and native output."""
    if not (runtime / "viper.py").is_file() or not inputs.is_dir():
        raise ValueError("missing private runtime or inputs")
    marker = runtime / "synthetic-runtime.json"
    if not marker.is_file():
        raise ValueError("unregistered runtime: use copy_runtime first")
    binding = json.loads(marker.read_text())
    if (
        binding["destination"] != str(runtime.resolve())
        or Path(binding["source"]).resolve() == runtime.resolve()
        or set(binding["sha256"]) != set(SOURCE_FILES)
        or any(
            (runtime / name).is_symlink() or sha256(runtime / name) != digest
            for name, digest in binding["sha256"].items()
        )
    ):
        raise ValueError("private runtime source binding failed")
    for left, right in ((runtime, inputs), (runtime, output), (inputs, output)):
        if left.resolve().is_relative_to(right.resolve()) or right.resolve().is_relative_to(
            left.resolve()
        ):
            raise ValueError("runtime, inputs and output must be disjoint directories")
    output.mkdir(parents=True, exist_ok=False)
    tag = output / "fit"
    argv = viper_argv(runtime, inputs, tag, template, rebuild=rebuild)
    # A tiny startup wrapper disables IERS download before unchanged VIPER code runs.
    # Source is unchanged and no observational/template path is on the argv.
    wrapper = (
        "import runpy,sys,types; from astropy.utils import iers; "
        "iers.conf.auto_download=False; sys.path.insert(0,sys.argv[1]); "
        'exec("class NoPlot:\\n def __getattr__(self,name): return self\\n '
        "def __call__(self,*a,**kw): return self\\n "
        "def __add__(self,other): return self\\n "
        'def __sub__(self,other): return self\\n"); '
        "plot=types.ModuleType('utils.gplot'); plot.gplot=NoPlot(); "
        "plot.Gplot=NoPlot; plot.ogplot=NoPlot(); plot.Iplot=NoPlot; "
        "sys.modules['utils.gplot']=plot; "
        "sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    command = [sys.executable, "-c", wrapper, str(runtime), *argv[1:]]
    environment = {
        **os.environ,
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "PYTHONPATH": str(runtime),
        "MPLBACKEND": "Agg",
    }
    with (output / "stdout.log").open("w", encoding="utf-8") as logfile:
        result = subprocess.run(
            command,
            cwd=output,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(f"VIPER failed ({result.returncode}); see {output / 'stdout.log'}")
    expected = tuple(sorted(path.name for path in inputs.glob("*.fits")))
    rows = parse_rvo(tag.with_suffix(".rvo.dat"), expected, initial=template is None)
    if rebuild:
        native_template(output / "fit_tpl.fits")
    return {
        "argv": argv,
        "command": command,
        "rows": rows,
        "log_sha256": sha256(output / "stdout.log"),
    }
