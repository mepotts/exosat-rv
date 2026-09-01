"""Generic, control-only stellar-component velocity injection.

This module operates on an already decomposed one-dimensional spectral exposure.  It is a
component-level prerequisite for a later end-to-end implementation: it does **not** establish
that a detector image, extraction, or instrument pipeline has been injected correctly.

The sign convention is positive velocity for recession.  For ``beta = v / c`` the
relativistic wavelength factor is

``doppler_factor = sqrt((1 + beta) / (1 - beta))``.

At a fixed observed wavelength ``lambda``, the shifted stellar spectrum is therefore sampled
from ``lambda / doppler_factor``.  Telluric transmission remains on the original observed
wavelength grid.  The reconstructed noiseless observation is

``LSF * (shifted_stellar_flux * telluric_transmission)``

and the original noise array is added afterward, unchanged.  Interpolation outside the input
stellar grid uses the nearest boundary value; synthetic controls should put continuum at both
boundaries so this declared extrapolation does not create a line feature.  The wavelength grid
must be strictly increasing and uniformly sampled in linear wavelength.  LSF entries are the
blue-to-red response to a monochromatic input on that grid; descending or irregular grids are
rejected rather than silently changing an asymmetric kernel's physical orientation.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral

import numpy as np
from numpy.typing import ArrayLike, NDArray

C_M_S = 299_792_458.0
"""Speed of light in vacuum, exactly, in metres per second."""

FloatArray = NDArray[np.float64]

_WAVELENGTH_GRID_RTOL = 1e-9


def _float_array_1d(value: ArrayLike, name: str) -> FloatArray:
    """Return a private, read-only float64 copy of a non-empty one-dimensional array."""
    try:
        array = np.array(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be convertible to a numeric array") from exc
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional array")
    array.setflags(write=False)
    return array


def _validate_wavelength(wavelength: FloatArray) -> None:
    if wavelength.size < 2:
        raise ValueError("wavelength must contain at least two samples")
    if not np.all(np.isfinite(wavelength)):
        raise ValueError("wavelength must contain only finite values")
    if np.any(wavelength <= 0.0):
        raise ValueError("wavelength values must be positive")
    steps = np.diff(wavelength)
    if not np.all(steps > 0.0):
        raise ValueError("wavelength must be strictly increasing")
    grid_atol = 8.0 * np.finfo(np.float64).eps * float(np.max(np.abs(wavelength)))
    if not np.allclose(
        steps,
        steps[0],
        rtol=_WAVELENGTH_GRID_RTOL,
        atol=grid_atol,
    ):
        raise ValueError("wavelength must be uniformly sampled in linear wavelength")


def _validate_lsf(lsf_kernel: FloatArray, sample_count: int) -> None:
    if lsf_kernel.size > sample_count:
        raise ValueError("lsf_kernel cannot be longer than the spectrum")
    if not np.all(np.isfinite(lsf_kernel)):
        raise ValueError("lsf_kernel must contain only finite values")
    if np.any(lsf_kernel < 0.0):
        raise ValueError("lsf_kernel must be non-negative")
    try:
        with np.errstate(over="raise", invalid="raise"):
            total = float(np.sum(lsf_kernel, dtype=np.float64))
    except FloatingPointError as exc:
        raise ValueError("lsf_kernel must have a positive finite sum") from exc
    if not np.isfinite(total) or total <= 0.0:
        raise ValueError("lsf_kernel must have a positive finite sum")
    if not np.isclose(total, 1.0, rtol=1e-12, atol=1e-12):
        raise ValueError("lsf_kernel must already be normalized to unit sum")


@dataclass(frozen=True, slots=True)
class DecomposedSpectralExposure:
    """Stellar, telluric, LSF, and noise components on one observed wavelength grid.

    All inputs are copied into read-only float64 arrays.  ``stellar_flux`` is the noiseless
    stellar component before telluric multiplication.  ``telluric_transmission`` is sampled
    at ``wavelength`` and must lie in [0, 1].  ``noise`` is an already realized additive
    noise vector, not a standard deviation.  ``wavelength`` must be increasing and uniformly
    sampled in linear wavelength so the fixed index-space LSF has an unambiguous orientation.
    """

    wavelength: FloatArray
    stellar_flux: FloatArray
    telluric_transmission: FloatArray
    lsf_kernel: FloatArray
    noise: FloatArray

    def __post_init__(self) -> None:
        wavelength = _float_array_1d(self.wavelength, "wavelength")
        stellar_flux = _float_array_1d(self.stellar_flux, "stellar_flux")
        telluric = _float_array_1d(self.telluric_transmission, "telluric_transmission")
        lsf_kernel = _float_array_1d(self.lsf_kernel, "lsf_kernel")
        noise = _float_array_1d(self.noise, "noise")

        _validate_wavelength(wavelength)
        expected_shape = wavelength.shape
        for name, array in (
            ("stellar_flux", stellar_flux),
            ("telluric_transmission", telluric),
            ("noise", noise),
        ):
            if array.shape != expected_shape:
                raise ValueError(f"{name} must have the same shape as wavelength")
            if not np.all(np.isfinite(array)):
                raise ValueError(f"{name} must contain only finite values")

        if np.any(stellar_flux < 0.0):
            raise ValueError("stellar_flux must be non-negative")
        if np.any((telluric < 0.0) | (telluric > 1.0)):
            raise ValueError("telluric_transmission must lie in the closed interval [0, 1]")
        _validate_lsf(lsf_kernel, wavelength.size)

        object.__setattr__(self, "wavelength", wavelength)
        object.__setattr__(self, "stellar_flux", stellar_flux)
        object.__setattr__(self, "telluric_transmission", telluric)
        object.__setattr__(self, "lsf_kernel", lsf_kernel)
        object.__setattr__(self, "noise", noise)


@dataclass(frozen=True, slots=True)
class InjectionDiagnostics:
    """Scalar diagnostics for one stellar-component injection."""

    velocity_m_s: float
    beta: float
    doppler_factor: float
    extrapolated_pixel_count: int
    maximum_stellar_change: float
    maximum_noiseless_change: float


@dataclass(frozen=True, slots=True)
class SpectralInjectionResult:
    """Components and physical reconstructions before and after injection.

    Preserved components are copied into the result rather than aliased to the input.  Every
    array is read-only.  ``wavelength`` is also the telluric wavelength grid.
    """

    wavelength: FloatArray
    original_stellar_flux: FloatArray
    shifted_stellar_flux: FloatArray
    telluric_transmission: FloatArray
    lsf_kernel: FloatArray
    noise: FloatArray
    original_noiseless_flux: FloatArray
    injected_noiseless_flux: FloatArray
    original_observed_flux: FloatArray
    injected_observed_flux: FloatArray
    diagnostics: InjectionDiagnostics


@dataclass(frozen=True, slots=True)
class InjectionInvariance:
    """Exact preservation and reconstruction checks for an injection result."""

    wavelength_sampling_unchanged: bool
    original_stellar_component_unchanged: bool
    telluric_transmission_unchanged: bool
    lsf_kernel_unchanged: bool
    noise_realization_unchanged: bool
    diagnostic_velocity_valid: bool
    diagnostic_velocity_matches_expected: bool
    diagnostic_beta_matches: bool
    diagnostic_doppler_factor_matches: bool
    diagnostic_extrapolated_pixel_count_matches: bool
    diagnostic_maximum_stellar_change_matches: bool
    diagnostic_maximum_noiseless_change_matches: bool
    stellar_shift_matches_convention: bool
    original_reconstruction_matches: bool
    injected_reconstruction_matches: bool

    @property
    def passed(self) -> bool:
        """Whether every required component and reconstruction invariant holds."""
        return all(
            (
                self.wavelength_sampling_unchanged,
                self.original_stellar_component_unchanged,
                self.telluric_transmission_unchanged,
                self.lsf_kernel_unchanged,
                self.noise_realization_unchanged,
                self.diagnostic_velocity_valid,
                self.diagnostic_velocity_matches_expected,
                self.diagnostic_beta_matches,
                self.diagnostic_doppler_factor_matches,
                self.diagnostic_extrapolated_pixel_count_matches,
                self.diagnostic_maximum_stellar_change_matches,
                self.diagnostic_maximum_noiseless_change_matches,
                self.stellar_shift_matches_convention,
                self.original_reconstruction_matches,
                self.injected_reconstruction_matches,
            )
        )


def relativistic_doppler_factor(velocity_m_s: float) -> float:
    """Return the wavelength factor for a finite, subluminal velocity.

    Positive velocity is recession and produces a factor greater than one.  Boolean values,
    arrays, non-finite values, and velocities with ``abs(v) >= c`` are rejected.
    """
    if isinstance(velocity_m_s, (bool, np.bool_)) or not np.isscalar(velocity_m_s):
        raise ValueError("velocity_m_s must be a real scalar")
    try:
        velocity = float(velocity_m_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("velocity_m_s must be a real scalar") from exc
    if not np.isfinite(velocity):
        raise ValueError("velocity_m_s must be finite")
    if abs(velocity) >= C_M_S:
        raise ValueError("velocity_m_s must be strictly subluminal")
    beta = velocity / C_M_S
    factor = float(np.sqrt((1.0 + beta) / (1.0 - beta)))
    if not np.isfinite(factor) or factor <= 0.0:
        raise ValueError("velocity_m_s produced an invalid Doppler factor")
    return factor


def shift_stellar_component(
    wavelength: ArrayLike,
    stellar_flux: ArrayLike,
    velocity_m_s: float,
) -> FloatArray:
    """Relativistically shift a stellar component while retaining its sampling.

    The returned spectrum is evaluated as ``stellar_flux(wavelength / factor)``.  The nearest
    boundary value is used when the source coordinate lies outside the supplied grid.  The
    wavelength array must be increasing and uniformly sampled in linear wavelength.
    """
    grid = _float_array_1d(wavelength, "wavelength")
    stellar = _float_array_1d(stellar_flux, "stellar_flux")
    _validate_wavelength(grid)
    if stellar.shape != grid.shape:
        raise ValueError("stellar_flux must have the same shape as wavelength")
    if not np.all(np.isfinite(stellar)):
        raise ValueError("stellar_flux must contain only finite values")

    factor = relativistic_doppler_factor(velocity_m_s)
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            source_wavelength = grid / factor
    except FloatingPointError as exc:
        raise ValueError("Doppler source wavelengths became non-finite") from exc
    if not np.all(np.isfinite(source_wavelength)):
        raise ValueError("Doppler source wavelengths became non-finite")
    shifted = np.interp(
        source_wavelength,
        grid,
        stellar,
        left=float(stellar[0]),
        right=float(stellar[-1]),
    ).astype(np.float64, copy=False)
    if not np.all(np.isfinite(shifted)):
        raise ValueError("shifted stellar component became non-finite")
    shifted.setflags(write=False)
    return shifted


def convolve_fixed_lsf(flux: ArrayLike, lsf_kernel: ArrayLike) -> FloatArray:
    """Convolve one flux vector with a fixed normalized LSF and retain its length.

    Kernel entries give the response to a monochromatic input from lower to higher wavelength
    on an increasing, uniform grid.  Values beyond the sampled interval are continued with the
    nearest edge value.  For a kernel of length ``m``, ``(m - 1) // 2`` samples are padded on
    the left and ``m // 2`` on the right before a ``valid`` convolution.  This also explicitly
    defines even-kernel half-pixel centering.
    """
    flux_array = _float_array_1d(flux, "flux")
    kernel = _float_array_1d(lsf_kernel, "lsf_kernel")
    if not np.all(np.isfinite(flux_array)):
        raise ValueError("flux must contain only finite values")
    _validate_lsf(kernel, flux_array.size)

    left = (kernel.size - 1) // 2
    right = kernel.size // 2
    padded = np.pad(flux_array, (left, right), mode="edge")
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            convolved = np.convolve(padded, kernel, mode="valid").astype(
                np.float64,
                copy=False,
            )
    except FloatingPointError as exc:
        raise ValueError("LSF convolution produced non-finite flux") from exc
    if not np.all(np.isfinite(convolved)):
        raise ValueError("LSF convolution produced non-finite flux")
    convolved.setflags(write=False)
    return convolved


def _readonly_result_array(value: FloatArray) -> FloatArray:
    result = np.array(value, dtype=np.float64, copy=True)
    result.setflags(write=False)
    return result


def _finite_scalar(value: object) -> float | None:
    if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if np.isfinite(numeric) else None


def inject_stellar_velocity(
    exposure: DecomposedSpectralExposure,
    velocity_m_s: float,
) -> SpectralInjectionResult:
    """Inject velocity into only the stellar component of a decomposed exposure.

    The input object and all of its arrays are left untouched.  Tellurics are multiplied into
    the stellar component before the same fixed LSF is applied, and the same realized noise is
    added to the baseline and injected reconstructions.
    """
    if not isinstance(exposure, DecomposedSpectralExposure):
        raise TypeError("exposure must be a DecomposedSpectralExposure")

    factor = relativistic_doppler_factor(velocity_m_s)
    try:
        velocity = float(velocity_m_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("velocity_m_s must be a real scalar") from exc
    shifted_stellar = shift_stellar_component(
        exposure.wavelength,
        exposure.stellar_flux,
        velocity,
    )
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            original_pre_lsf = exposure.stellar_flux * exposure.telluric_transmission
            injected_pre_lsf = shifted_stellar * exposure.telluric_transmission
        original_noiseless = convolve_fixed_lsf(original_pre_lsf, exposure.lsf_kernel)
        injected_noiseless = convolve_fixed_lsf(injected_pre_lsf, exposure.lsf_kernel)
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            original_observed = original_noiseless + exposure.noise
            injected_observed = injected_noiseless + exposure.noise
            source_wavelength = exposure.wavelength / factor
    except FloatingPointError as exc:
        raise ValueError("spectral reconstruction produced non-finite values") from exc
    reconstructed = (
        original_pre_lsf,
        injected_pre_lsf,
        original_noiseless,
        injected_noiseless,
        original_observed,
        injected_observed,
        source_wavelength,
    )
    if any(not np.all(np.isfinite(array)) for array in reconstructed):
        raise ValueError("spectral reconstruction produced non-finite values")

    lower = float(np.min(exposure.wavelength))
    upper = float(np.max(exposure.wavelength))
    extrapolated = int(np.count_nonzero((source_wavelength < lower) | (source_wavelength > upper)))
    diagnostics = InjectionDiagnostics(
        velocity_m_s=velocity,
        beta=velocity / C_M_S,
        doppler_factor=factor,
        extrapolated_pixel_count=extrapolated,
        maximum_stellar_change=float(np.max(np.abs(shifted_stellar - exposure.stellar_flux))),
        maximum_noiseless_change=float(np.max(np.abs(injected_noiseless - original_noiseless))),
    )

    return SpectralInjectionResult(
        wavelength=_readonly_result_array(exposure.wavelength),
        original_stellar_flux=_readonly_result_array(exposure.stellar_flux),
        shifted_stellar_flux=_readonly_result_array(shifted_stellar),
        telluric_transmission=_readonly_result_array(exposure.telluric_transmission),
        lsf_kernel=_readonly_result_array(exposure.lsf_kernel),
        noise=_readonly_result_array(exposure.noise),
        original_noiseless_flux=_readonly_result_array(original_noiseless),
        injected_noiseless_flux=_readonly_result_array(injected_noiseless),
        original_observed_flux=_readonly_result_array(original_observed),
        injected_observed_flux=_readonly_result_array(injected_observed),
        diagnostics=diagnostics,
    )


def check_injection_invariants(
    exposure: DecomposedSpectralExposure,
    result: SpectralInjectionResult,
    *,
    expected_velocity_m_s: float | None = None,
) -> InjectionInvariance:
    """Check every preserved component, diagnostic, and physical reconstruction.

    Supplying ``expected_velocity_m_s`` binds the result to an external injection plan.  When
    it is omitted, the diagnostic velocity must still be valid and internally consistent with
    the shifted spectrum, but no independent plan value can be established.
    """
    if not isinstance(exposure, DecomposedSpectralExposure):
        raise TypeError("exposure must be a DecomposedSpectralExposure")
    if not isinstance(result, SpectralInjectionResult):
        raise TypeError("result must be a SpectralInjectionResult")

    diagnostic_velocity = _finite_scalar(result.diagnostics.velocity_m_s)
    diagnostic_velocity_valid = False
    if diagnostic_velocity is not None:
        try:
            relativistic_doppler_factor(diagnostic_velocity)
        except ValueError:
            pass
        else:
            diagnostic_velocity_valid = True

    if expected_velocity_m_s is None:
        if diagnostic_velocity_valid:
            bound_velocity = diagnostic_velocity
        else:
            bound_velocity = None
        diagnostic_velocity_matches_expected = diagnostic_velocity_valid
    else:
        relativistic_doppler_factor(expected_velocity_m_s)
        try:
            bound_velocity = float(expected_velocity_m_s)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("expected_velocity_m_s must be a real scalar") from exc
        diagnostic_velocity_matches_expected = (
            diagnostic_velocity_valid and diagnostic_velocity == bound_velocity
        )

    if bound_velocity is None:
        expected_factor_value = None
        expected_beta = None
        expected_shifted = None
        expected_injected_noiseless = None
        expected_extrapolated = None
        expected_maximum_stellar_change = None
        expected_maximum_noiseless_change = None
    else:
        expected_factor_value = relativistic_doppler_factor(bound_velocity)
        expected_beta = bound_velocity / C_M_S
        expected_shifted = shift_stellar_component(
            exposure.wavelength,
            exposure.stellar_flux,
            bound_velocity,
        )
        expected_injected_noiseless = convolve_fixed_lsf(
            expected_shifted * exposure.telluric_transmission,
            exposure.lsf_kernel,
        )
        try:
            with np.errstate(over="raise", divide="raise", invalid="raise"):
                source_wavelength = exposure.wavelength / expected_factor_value
        except FloatingPointError as exc:
            raise ValueError("expected velocity produced non-finite source wavelengths") from exc
        expected_extrapolated = int(
            np.count_nonzero(
                (source_wavelength < exposure.wavelength[0])
                | (source_wavelength > exposure.wavelength[-1])
            )
        )
        expected_maximum_stellar_change = float(
            np.max(np.abs(expected_shifted - exposure.stellar_flux))
        )

    expected_original_noiseless = convolve_fixed_lsf(
        exposure.stellar_flux * exposure.telluric_transmission,
        exposure.lsf_kernel,
    )
    if expected_injected_noiseless is not None:
        expected_maximum_noiseless_change = float(
            np.max(np.abs(expected_injected_noiseless - expected_original_noiseless))
        )
    try:
        with np.errstate(over="raise", divide="raise", invalid="raise"):
            expected_original_observed = expected_original_noiseless + exposure.noise
            expected_injected_observed = (
                expected_injected_noiseless + exposure.noise
                if expected_injected_noiseless is not None
                else None
            )
    except FloatingPointError as exc:
        raise ValueError("invariant reconstruction produced non-finite values") from exc

    diagnostic_beta = _finite_scalar(result.diagnostics.beta)
    diagnostic_factor = _finite_scalar(result.diagnostics.doppler_factor)
    diagnostic_maximum_stellar = _finite_scalar(result.diagnostics.maximum_stellar_change)
    diagnostic_maximum_noiseless = _finite_scalar(result.diagnostics.maximum_noiseless_change)
    diagnostic_count = result.diagnostics.extrapolated_pixel_count
    count_matches = (
        expected_extrapolated is not None
        and not isinstance(diagnostic_count, (bool, np.bool_))
        and isinstance(diagnostic_count, Integral)
        and int(diagnostic_count) == expected_extrapolated
    )
    return InjectionInvariance(
        wavelength_sampling_unchanged=np.array_equal(result.wavelength, exposure.wavelength),
        original_stellar_component_unchanged=np.array_equal(
            result.original_stellar_flux,
            exposure.stellar_flux,
        ),
        telluric_transmission_unchanged=np.array_equal(
            result.telluric_transmission,
            exposure.telluric_transmission,
        ),
        lsf_kernel_unchanged=np.array_equal(result.lsf_kernel, exposure.lsf_kernel),
        noise_realization_unchanged=np.array_equal(result.noise, exposure.noise),
        diagnostic_velocity_valid=diagnostic_velocity_valid,
        diagnostic_velocity_matches_expected=diagnostic_velocity_matches_expected,
        diagnostic_beta_matches=(
            diagnostic_beta is not None
            and expected_beta is not None
            and diagnostic_beta == expected_beta
        ),
        diagnostic_doppler_factor_matches=(
            diagnostic_factor is not None
            and expected_factor_value is not None
            and diagnostic_factor == expected_factor_value
        ),
        diagnostic_extrapolated_pixel_count_matches=count_matches,
        diagnostic_maximum_stellar_change_matches=(
            diagnostic_maximum_stellar is not None
            and expected_maximum_stellar_change is not None
            and diagnostic_maximum_stellar == expected_maximum_stellar_change
        ),
        diagnostic_maximum_noiseless_change_matches=(
            diagnostic_maximum_noiseless is not None
            and expected_maximum_noiseless_change is not None
            and diagnostic_maximum_noiseless == expected_maximum_noiseless_change
        ),
        stellar_shift_matches_convention=(
            expected_shifted is not None
            and np.array_equal(result.shifted_stellar_flux, expected_shifted)
        ),
        original_reconstruction_matches=(
            np.array_equal(result.original_noiseless_flux, expected_original_noiseless)
            and np.array_equal(result.original_observed_flux, expected_original_observed)
        ),
        injected_reconstruction_matches=(
            expected_injected_noiseless is not None
            and np.array_equal(result.injected_noiseless_flux, expected_injected_noiseless)
            and expected_injected_observed is not None
            and np.array_equal(result.injected_observed_flux, expected_injected_observed)
        ),
    )
