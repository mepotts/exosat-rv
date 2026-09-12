"""Independent synthetic-only adversarial checks of the VIPER engineering bridge.

No external VIPER execution or observational data is needed by this test file.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from exosat_rv.m38.viper_bridge import (
    SOURCE_FILES,
    analytic_flux,
    copy_runtime,
    execute_viper,
    native_template,
    parse_rvo,
    viper_argv,
    write_synthetic_fits,
)


@pytest.mark.parametrize("velocity", [-7000.0, -300.0, 0.0, 300.0, 7000.0])
def test_analytic_line_center_has_independently_predicted_sign(velocity):
    # Isolate a single line. The centroid expectation uses only the declared
    # classical wavelength convention, not the bridge's synthesis implementation.
    wave = np.linspace(1550.06, 1550.42, 10001)
    berv = 1100.0
    flux = analytic_flux(wave, velocity, berv)
    centroid = np.sum(wave * (1 - flux)) / np.sum(1 - flux)
    expected = 1550.24 * (299792458.0 + velocity) / (299792458.0 + berv)
    assert centroid == pytest.approx(expected, abs=2e-8)
    reversed_sign = 1550.24 * (299792458.0 - velocity) / (299792458.0 + berv)
    if velocity:
        assert abs(centroid - reversed_sign) > 0.002


def test_analytic_pixel_average_matches_independent_dense_quadrature():
    from scipy.special import erf

    wave = np.linspace(1550.10, 1550.38, 161)
    spacing = wave[1] - wave[0]
    velocity, berv = 2800.0, -7300.0
    factor = (299792458.0 + velocity) / (299792458.0 + berv)
    center = 1550.24 * factor
    sigma = 1550.24 * np.sqrt(2500**2 + 1500**2) / 299792458.0 * factor
    amplitude = 0.2 * 2500 / np.sqrt(2500**2 + 1500**2)
    upper = (wave + spacing / 2 - center) / (np.sqrt(2) * sigma)
    lower = (wave - spacing / 2 - center) / (np.sqrt(2) * sigma)
    integral = amplitude * sigma * np.sqrt(np.pi / 2) * (erf(upper) - erf(lower))
    expected = 1 - integral / spacing
    np.testing.assert_allclose(analytic_flux(wave, velocity, berv), expected, atol=2e-6)


@pytest.mark.parametrize("template", [False, True])
def test_fits_units_mapping_and_no_truth_fields(tmp_path, template):
    from astropy.io import fits

    wave = np.linspace(1550, 1554, 1024)
    flux = analytic_flux(wave, 1300, -4700)
    sigma = np.linspace(0.001, 0.003, wave.size)
    path = tmp_path / ("synthetic_tpl.fits" if template else "synthetic.fits")
    write_synthetic_fits(path, wave, flux, sigma, template=template)
    with fits.open(path) as hdus:
        assert len(hdus) == 4
        assert "SYNTHETIC" in hdus[0].header["ESO PRO CATG"]
        for detector in (1, 2, 3):
            assert hdus[detector].columns.names == ["01_01_SPEC", "01_01_ERR", "01_01_WL"]
            np.testing.assert_array_equal(hdus[detector].data["01_01_SPEC"], flux)
            np.testing.assert_array_equal(hdus[detector].data["01_01_ERR"], sigma)
            np.testing.assert_array_equal(
                hdus[detector].data["01_01_WL"], wave * (10 if template else 1)
            )
            assert hdus[detector].columns[2].unit == ("Angstrom" if template else "nm")
        # Reproduce the instrument reader's non-K mapping independently, including
        # its detector offset determined by the last column in every table.
        maxima = [int(hdus[d].columns.names[-1].split("_")[0]) for d in (1, 2, 3)]
        offset = maxima.index(max(maxima)) + 1
        mapped = []
        for order in (0, 1, 2):
            order_index, detector = divmod(order, 3)
            detector = (detector + offset) % 3 or 3
            mapped.append((detector, maxima[detector - 1] - order_index))
        assert mapped == [(1, 1), (2, 1), (3, 1)]
    if template:
        native_wave, native_flux, native_error = native_template(path)
        np.testing.assert_array_equal(native_wave, wave * 10)
        np.testing.assert_array_equal(native_flux, flux)
        np.testing.assert_array_equal(native_error, sigma)


@pytest.mark.parametrize("template", [False, True])
def test_fits_rejects_unit_suffix_mismatch_without_writing(tmp_path, template):
    wave = np.linspace(1550, 1554, 1024)
    path = tmp_path / ("bad.fits" if template else "bad_tpl.fits")
    with pytest.raises(ValueError, match="suffix"):
        write_synthetic_fits(path, wave, wave * 0 + 1, wave * 0 + 0.01, template=template)
    assert not path.exists()


@pytest.mark.parametrize("invalid_sigma", [0.0, -0.01, np.nan, np.inf])
def test_fits_rejects_invalid_declared_pixel_uncertainty(tmp_path, invalid_sigma):
    wave = np.linspace(1550, 1554, 1024)
    sigma = np.full(wave.size, 0.01)
    sigma[100] = invalid_sigma
    path = tmp_path / "invalid_error.fits"
    with pytest.raises(ValueError, match="invalid synthetic"):
        write_synthetic_fits(path, wave, np.ones(wave.size), sigma)
    assert not path.exists()


def test_rvo_aligns_by_filename_not_row_position(tmp_path):
    path = tmp_path / "fit.rvo.dat"
    path.write_text(
        "BJD RV e_RV BERV rv0 e_rv0 filename\n"
        "2458849.5 -18 2 1.2 -18 2 beta.fits\n"
        "2458849.5 42 3 1.2 42 3 alpha.fits\n"
    )
    result = parse_rvo(path, ("alpha.fits", "beta.fits"))
    assert result["alpha.fits"]["rv0"] == 42
    assert result["beta.fits"]["rv0"] == -18


@pytest.mark.parametrize(
    "rows",
    [
        "",
        "2458849.5 42 3 1.2 42 3 wrong.fits\n",
        "2458849.5 42 3 1.2 42 3 alpha.fits\n" * 2,
        "2458849.5 42 3 1.2 nan 3 alpha.fits\n",
        "2458849.5 42 3 1.2 42 0 alpha.fits\n",
        "2458849.5 42 3 1.2 42 -3 alpha.fits\n",
        "2458849.5 42 3 1.2 42 inf alpha.fits\n",
        "2458849.5 42 3 1.2 42 alpha.fits\n",
    ],
)
def test_rvo_rejects_missing_duplicate_or_invalid_order_output(tmp_path, rows):
    path = tmp_path / "fit.rvo.dat"
    path.write_text("BJD RV e_RV BERV rv0 e_rv0 filename\n" + rows)
    with pytest.raises(ValueError):
        parse_rvo(path, ("alpha.fits",))


def test_rvo_rejects_relabelled_or_lost_order(tmp_path):
    path = tmp_path / "fit.rvo.dat"
    path.write_text("BJD RV e_RV BERV rv1 e_rv1 filename\n2458849.5 42 3 1.2 42 3 alpha.fits\n")
    with pytest.raises(ValueError, match="columns"):
        parse_rvo(path, ("alpha.fits",), orders=(0,))


def test_runtime_copy_is_source_allowlisted_and_never_overwrites(tmp_path):
    source = tmp_path / "source"
    for name in SOURCE_FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# synthetic source fixture {name}\n")
    forbidden = source / "lib" / "hidden_observation.fits"
    forbidden.parent.mkdir()
    forbidden.write_bytes(b"DO NOT COPY DATA")
    output = tmp_path / "private"
    manifest = copy_runtime(source, output)
    assert set(manifest) == set(SOURCE_FILES)
    assert not (output / "lib").exists()
    assert all((output / name).read_bytes() == (source / name).read_bytes() for name in manifest)
    with pytest.raises(ValueError, match="fresh"):
        copy_runtime(source, output)


def test_argv_never_uses_real_atlas_or_target_and_fixes_wavelength():
    argv = viper_argv(Path("runtime"), Path("training"), Path("output"), None, rebuild=True)
    assert argv[argv.index("-fts") + 1] == "None"
    assert argv[argv.index("-telluric") + 1] == ""
    assert argv[argv.index("-tpl_wave") + 1] == "berv"
    assert argv[argv.index("-tpl_noRV") + 1] == "0"
    assert argv[argv.index("-createtpl") + 1] == "1"
    assert argv[argv.index("-oset") + 1] == "0"
    assert "wave" in argv[argv.index("-fix") + 1 : argv.index("-ip")]
    assert "-targ" not in argv
    assert "-config_file" not in argv


@pytest.mark.parametrize("column", ["SPEC", "ERR"])
@pytest.mark.parametrize("bad_value", [np.inf, -np.inf])
def test_native_template_does_not_treat_infinities_as_masked_edges(tmp_path, column, bad_value):
    from astropy.io import fits

    wave = np.linspace(1550, 1554, 1024)
    path = tmp_path / "generated_tpl.fits"
    write_synthetic_fits(path, wave, wave * 0 + 1, wave * 0 + 0.01, template=True)
    with fits.open(path, mode="update") as hdus:
        hdus[1].data[f"01_01_{column}"][0] = bad_value
    with pytest.raises(ValueError, match="malformed"):
        native_template(path)


def test_execute_refuses_unregistered_runtime_before_starting_process(tmp_path, monkeypatch):
    import exosat_rv.m38.viper_bridge as bridge

    runtime = tmp_path / "shared_installation_fixture"
    runtime.mkdir()
    (runtime / "viper.py").write_text("# harmless fixture, must never execute\n")
    inputs = tmp_path / "synthetic_inputs"
    inputs.mkdir()
    output = tmp_path / "output"

    def forbidden_process(*args, **kwargs):
        pytest.fail("subprocess was started before runtime validation")

    monkeypatch.setattr(bridge.subprocess, "run", forbidden_process)
    with pytest.raises(ValueError, match="unregistered"):
        execute_viper(runtime, inputs, output, None, rebuild=True)
    assert not output.exists()


def test_execute_rejects_modified_registered_source(tmp_path, monkeypatch):
    import exosat_rv.m38.viper_bridge as bridge

    source = tmp_path / "source"
    for name in SOURCE_FILES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# synthetic source fixture {name}\n")
    runtime = tmp_path / "private"
    copy_runtime(source, runtime)
    (runtime / "viper.py").write_text("# changed after registration\n")
    inputs = tmp_path / "synthetic_inputs"
    inputs.mkdir()

    def forbidden_process(*args, **kwargs):
        pytest.fail("subprocess was started with modified registered source")

    monkeypatch.setattr(bridge.subprocess, "run", forbidden_process)
    with pytest.raises(ValueError, match="binding"):
        execute_viper(runtime, inputs, tmp_path / "output", None, rebuild=True)


@pytest.mark.parametrize("drift", ["grid", "mask"])
def test_fixed_step_driver_rejects_template_grid_and_mask_drift(tmp_path, monkeypatch, drift):
    # This is only a driver failure-path test, not evidence of genuine template
    # rebuilding. Real subprocess runs are audited separately in retained evidence.
    import scripts.m38_viper_synthetic_bridge as driver

    monkeypatch.setattr(driver, "copy_runtime", lambda *args: {})
    monkeypatch.setattr(driver, "synthetic_berv_mps", lambda: 0.0)

    def generated_file(path, *args, **kwargs):
        path.write_bytes(b"generated-only test placeholder")

    def fake_builder(runtime, inputs, output, template, *, rebuild):
        assert inputs.name == "training"
        assert rebuild
        output.mkdir()
        (output / "fit_tpl.fits").write_bytes(b"generated-only template placeholder")
        return {}

    def changed_template(path):
        wave = np.linspace(15500, 15540, 2048)
        flux = np.ones(wave.size)
        if path.parent.name == "build1":
            if drift == "grid":
                wave = wave + 0.001
            else:
                flux[0] = np.nan
        return wave, flux, np.ones(wave.size) * 0.01

    monkeypatch.setattr(driver, "write_synthetic_fits", generated_file)
    monkeypatch.setattr(driver, "execute_viper", fake_builder)
    monkeypatch.setattr(driver, "native_template", changed_template)
    with pytest.raises(RuntimeError, match=f"template {drift} drift"):
        driver.run_case(
            tmp_path / "unused_source",
            tmp_path / "case",
            np.array([-300.0, -100.0, 400.0]),
            np.array([-500.0, 500.0]),
            iterations=1,
        )


def test_bridge_report_is_invariant_to_rvo_dictionary_insertion_order():
    from scripts import m38_render_viper_bridge as report

    result = json.loads(report.EVIDENCE.read_text())
    expected = report.render(result)
    for name in ("positive", "negative", "heldout_perturb"):
        rows = result["cases"][name]["heldout"]["rows"]
        result["cases"][name]["heldout"]["rows"] = dict(reversed(list(rows.items())))
    assert report.render(result) == expected


@pytest.mark.parametrize(
    "corruption", ["negative_training_cache", "stage_loss", "residual_nan", "residual_stale"]
)
def test_bridge_report_rejects_false_training_response_or_stale_residuals(corruption):
    from scripts import m38_render_viper_bridge as report

    result = json.loads(report.EVIDENCE.read_text())
    case = result["cases"]["negative"]
    if corruption == "negative_training_cache":
        case["history"][1]["native_arrays_sha256"] = result["cases"]["reference"]["history"][1][
            "native_arrays_sha256"
        ]
    elif corruption == "stage_loss":
        case["history"].pop(1)
    elif corruption == "residual_nan":
        case["learned_minus_expected_mps"][0] = float("nan")
    else:
        case["learned_minus_expected_mps"][0] += 10
    with pytest.raises(ValueError):
        report.render(result)
