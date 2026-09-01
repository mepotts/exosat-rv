"""Synthetic-only tests for the generic M38 stellar-component injection operator."""

from dataclasses import replace

import numpy as np
import pytest

from exosat_rv.m38.spectral import (
    C_M_S,
    DecomposedSpectralExposure,
    check_injection_invariants,
    convolve_fixed_lsf,
    inject_stellar_velocity,
    relativistic_doppler_factor,
)


def synthetic_exposure() -> tuple[DecomposedSpectralExposure, tuple[np.ndarray, ...]]:
    wavelength = np.linspace(499.5, 500.5, 4001)
    stellar = 1.0 - 0.45 * np.exp(-0.5 * ((wavelength - 500.0) / 0.004) ** 2)
    telluric = 1.0 - 0.30 * np.exp(-0.5 * ((wavelength - 500.25) / 0.003) ** 2)
    lsf = np.array([0.15, 0.70, 0.15])
    noise = np.random.default_rng(1847).normal(0.0, 0.002, wavelength.size)
    source_arrays = (wavelength, stellar, telluric, lsf, noise)
    exposure = DecomposedSpectralExposure(
        wavelength=wavelength,
        stellar_flux=stellar,
        telluric_transmission=telluric,
        lsf_kernel=lsf,
        noise=noise,
    )
    return exposure, source_arrays


@pytest.mark.parametrize("velocity_m_s", [-20_000.0, 20_000.0])
def test_relativistic_shift_recovers_sign_and_velocity(velocity_m_s: float) -> None:
    exposure, _ = synthetic_exposure()
    result = inject_stellar_velocity(exposure, velocity_m_s)

    original_center = exposure.wavelength[np.argmin(exposure.stellar_flux)]
    shifted_center = result.wavelength[np.argmin(result.shifted_stellar_flux)]
    measured_factor = shifted_center / original_center
    measured_beta = (measured_factor**2 - 1.0) / (measured_factor**2 + 1.0)
    recovered_velocity = measured_beta * C_M_S

    assert np.sign(shifted_center - original_center) == np.sign(velocity_m_s)
    assert recovered_velocity == pytest.approx(velocity_m_s, abs=200.0)
    assert result.diagnostics.doppler_factor == pytest.approx(
        relativistic_doppler_factor(velocity_m_s)
    )


def test_only_stellar_component_moves_and_reconstruction_is_physical() -> None:
    exposure, _ = synthetic_exposure()
    result = inject_stellar_velocity(exposure, 15_000.0)
    invariants = check_injection_invariants(
        exposure,
        result,
        expected_velocity_m_s=15_000.0,
    )

    expected_noiseless = convolve_fixed_lsf(
        result.shifted_stellar_flux * exposure.telluric_transmission,
        exposure.lsf_kernel,
    )
    assert invariants.passed
    assert np.array_equal(result.wavelength, exposure.wavelength)
    assert np.array_equal(result.original_stellar_flux, exposure.stellar_flux)
    assert np.array_equal(result.telluric_transmission, exposure.telluric_transmission)
    assert np.array_equal(result.lsf_kernel, exposure.lsf_kernel)
    assert np.array_equal(result.noise, exposure.noise)
    assert np.array_equal(result.injected_noiseless_flux, expected_noiseless)
    assert np.array_equal(
        result.injected_observed_flux,
        expected_noiseless + exposure.noise,
    )
    assert np.argmin(result.telluric_transmission) == np.argmin(exposure.telluric_transmission)


def test_zero_velocity_reconstructs_identical_observation() -> None:
    exposure, _ = synthetic_exposure()
    result = inject_stellar_velocity(exposure, 0.0)

    assert np.array_equal(result.shifted_stellar_flux, exposure.stellar_flux)
    assert np.array_equal(result.injected_noiseless_flux, result.original_noiseless_flux)
    assert np.array_equal(result.injected_observed_flux, result.original_observed_flux)
    assert result.diagnostics.maximum_stellar_change == 0.0


def test_inputs_are_defensively_copied_and_never_mutated() -> None:
    exposure, source_arrays = synthetic_exposure()
    source_before = tuple(array.copy() for array in source_arrays)
    exposure_before = tuple(
        array.copy()
        for array in (
            exposure.wavelength,
            exposure.stellar_flux,
            exposure.telluric_transmission,
            exposure.lsf_kernel,
            exposure.noise,
        )
    )

    result = inject_stellar_velocity(exposure, -12_500.0)

    for before, after in zip(source_before, source_arrays, strict=True):
        assert np.array_equal(after, before)
    for before, after in zip(
        exposure_before,
        (
            exposure.wavelength,
            exposure.stellar_flux,
            exposure.telluric_transmission,
            exposure.lsf_kernel,
            exposure.noise,
        ),
        strict=True,
    ):
        assert np.array_equal(after, before)
    assert not np.shares_memory(result.wavelength, exposure.wavelength)
    assert not np.shares_memory(result.noise, exposure.noise)
    assert not result.injected_observed_flux.flags.writeable


def test_invariance_checker_detects_a_changed_preserved_component() -> None:
    exposure, _ = synthetic_exposure()
    result = inject_stellar_velocity(exposure, 10_000.0)
    changed_noise = result.noise.copy()
    changed_noise[10] += 1.0
    tampered = replace(result, noise=changed_noise)

    invariants = check_injection_invariants(exposure, tampered)

    assert not invariants.noise_realization_unchanged
    assert not invariants.passed


def test_descending_wavelength_sampling_is_rejected_for_lsf_orientation() -> None:
    exposure, _ = synthetic_exposure()
    with pytest.raises(ValueError, match="strictly increasing"):
        DecomposedSpectralExposure(
            wavelength=exposure.wavelength[::-1],
            stellar_flux=exposure.stellar_flux[::-1],
            telluric_transmission=exposure.telluric_transmission[::-1],
            lsf_kernel=exposure.lsf_kernel,
            noise=exposure.noise[::-1],
        )


def test_asymmetric_lsf_is_oriented_from_lower_to_higher_wavelength() -> None:
    flux = np.zeros(7)
    flux[3] = 1.0
    kernel = np.array([0.1, 0.2, 0.7])

    convolved = convolve_fixed_lsf(flux, kernel)

    np.testing.assert_array_equal(
        convolved,
        np.array([0.0, 0.0, 0.1, 0.2, 0.7, 0.0, 0.0]),
    )


@pytest.mark.parametrize(
    ("wavelength", "message"),
    [
        (np.array([1.0, 2.0, 1.5]), "strictly increasing"),
        (np.array([1.0, 1.0, 2.0]), "strictly increasing"),
        (np.array([3.0, 2.0, 1.0]), "strictly increasing"),
        (np.array([1.0, 2.0, 4.0]), "uniformly sampled"),
        (np.array([1.0, np.nan, 2.0]), "finite"),
        (np.array([-1.0, 1.0, 2.0]), "positive"),
    ],
)
def test_invalid_wavelength_is_rejected(wavelength: np.ndarray, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DecomposedSpectralExposure(
            wavelength=wavelength,
            stellar_flux=np.ones(3),
            telluric_transmission=np.ones(3),
            lsf_kernel=np.array([1.0]),
            noise=np.zeros(3),
        )


@pytest.mark.parametrize(
    "velocity_m_s",
    [np.nan, np.inf, -np.inf, C_M_S, -C_M_S, True],
)
def test_invalid_velocity_is_rejected(velocity_m_s: float) -> None:
    exposure, _ = synthetic_exposure()
    with pytest.raises(ValueError):
        inject_stellar_velocity(exposure, velocity_m_s)


@pytest.mark.parametrize(
    "lsf_kernel",
    [
        np.array([0.2, 0.2]),
        np.array([-0.1, 1.1]),
        np.array([np.nan]),
        np.array([0.0]),
    ],
)
def test_invalid_lsf_is_rejected(lsf_kernel: np.ndarray) -> None:
    with pytest.raises(ValueError):
        DecomposedSpectralExposure(
            wavelength=np.array([1.0, 2.0, 3.0]),
            stellar_flux=np.ones(3),
            telluric_transmission=np.ones(3),
            lsf_kernel=lsf_kernel,
            noise=np.zeros(3),
        )


def test_invalid_component_shapes_and_ranges_are_rejected() -> None:
    base = {
        "wavelength": np.array([1.0, 2.0, 3.0]),
        "stellar_flux": np.ones(3),
        "telluric_transmission": np.ones(3),
        "lsf_kernel": np.array([1.0]),
        "noise": np.zeros(3),
    }
    with pytest.raises(ValueError, match="same shape"):
        DecomposedSpectralExposure(**{**base, "noise": np.zeros(2)})
    with pytest.raises(ValueError, match="non-negative"):
        DecomposedSpectralExposure(**{**base, "stellar_flux": np.array([1.0, -0.1, 1.0])})
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        DecomposedSpectralExposure(**{**base, "telluric_transmission": np.array([1.0, 1.01, 1.0])})


@pytest.mark.parametrize(
    ("field", "replacement", "invariant_field"),
    [
        ("velocity_m_s", 15_001.0, "diagnostic_velocity_matches_expected"),
        ("beta", 0.5, "diagnostic_beta_matches"),
        ("doppler_factor", 1.5, "diagnostic_doppler_factor_matches"),
        (
            "extrapolated_pixel_count",
            999,
            "diagnostic_extrapolated_pixel_count_matches",
        ),
        (
            "maximum_stellar_change",
            999.0,
            "diagnostic_maximum_stellar_change_matches",
        ),
        (
            "maximum_noiseless_change",
            999.0,
            "diagnostic_maximum_noiseless_change_matches",
        ),
    ],
)
def test_every_diagnostic_field_is_independently_checked(
    field: str,
    replacement: float,
    invariant_field: str,
) -> None:
    exposure, _ = synthetic_exposure()
    velocity = 15_000.0
    result = inject_stellar_velocity(exposure, velocity)
    corrupted_diagnostics = replace(result.diagnostics, **{field: replacement})
    corrupted = replace(result, diagnostics=corrupted_diagnostics)

    invariants = check_injection_invariants(
        exposure,
        corrupted,
        expected_velocity_m_s=velocity,
    )

    assert not getattr(invariants, invariant_field)
    assert not invariants.passed


def test_external_velocity_binding_rejects_a_different_plan_value() -> None:
    exposure, _ = synthetic_exposure()
    result = inject_stellar_velocity(exposure, 9_000.0)

    invariants = check_injection_invariants(
        exposure,
        result,
        expected_velocity_m_s=10_000.0,
    )

    assert not invariants.diagnostic_velocity_matches_expected
    assert not invariants.stellar_shift_matches_convention
    assert not invariants.passed


def test_numeric_conversion_overflow_is_rejected() -> None:
    huge_integer = 10**10_000
    exposure, _ = synthetic_exposure()

    with pytest.raises(ValueError, match="real scalar"):
        inject_stellar_velocity(exposure, huge_integer)
    with pytest.raises(ValueError, match="convertible"):
        DecomposedSpectralExposure(
            wavelength=np.array([1.0, 2.0, 3.0]),
            stellar_flux=[1.0, huge_integer, 1.0],
            telluric_transmission=np.ones(3),
            lsf_kernel=np.array([1.0]),
            noise=np.zeros(3),
        )


def test_nonfinite_reconstruction_from_overflow_is_rejected() -> None:
    maximum = np.finfo(np.float64).max
    exposure = DecomposedSpectralExposure(
        wavelength=np.array([1.0, 2.0, 3.0]),
        stellar_flux=np.full(3, maximum),
        telluric_transmission=np.ones(3),
        lsf_kernel=np.array([1.0]),
        noise=np.full(3, maximum),
    )

    with pytest.raises(ValueError, match="non-finite"):
        inject_stellar_velocity(exposure, 0.0)
