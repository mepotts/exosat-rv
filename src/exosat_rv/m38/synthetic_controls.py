"""Deterministic toy spectra and adapter for M38 template-chain wiring tests.

Nothing here models CRIRES+, VIPER, a real control object, or an admissible scientific
threshold.  The generator makes small Gaussian-line arrays from fully caller-supplied values.
The adapter performs elementary mean-template relaxation and line-centroid differencing solely
to exercise fold, injection, order-propagation, convergence, mask, and lineage plumbing.

Real extraction software must implement the protocol independently and be validated on the
eventual declared controls.  Passing this toy adapter is not evidence that a real extraction or
template chain preserves a signal.  Its per-invocation Python sessions and tokens demonstrate
runner call wiring only; they do not demonstrate a cold process rebuild, process isolation, or
absence of caches behind an adapter boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from exosat_rv.m38.provenance import canonical_sha256
from exosat_rv.m38.spectral import (
    DecomposedSpectralExposure,
    check_injection_invariants,
    inject_stellar_velocity,
)
from exosat_rv.m38.template_chain import (
    AdapterIdentity,
    ChainInvocation,
    ExposureSet,
    FrozenSpectralExposure,
    RVState,
    TemplateChainDataError,
    TemplateChainExecutionError,
    TemplateState,
)


def _label(value: str, name: str) -> str:
    if type(value) is not str or not value:
        raise TemplateChainDataError(f"{name} must be a non-empty native string")
    return value


def _finite_float(value: float, name: str) -> float:
    if type(value) is not float or not np.isfinite(value):
        raise TemplateChainDataError(f"{name} must be a finite native float")
    return value


def _positive_float(value: float, name: str) -> float:
    numeric = _finite_float(value, name)
    if numeric <= 0.0:
        raise TemplateChainDataError(f"{name} must be positive")
    return numeric


def _unit_interval(value: float, name: str, *, allow_zero: bool) -> float:
    numeric = _finite_float(value, name)
    lower_ok = numeric >= 0.0 if allow_zero else numeric > 0.0
    if not lower_ok or numeric > 1.0:
        interval = "[0, 1]" if allow_zero else "(0, 1]"
        raise TemplateChainDataError(f"{name} must lie in {interval}")
    return numeric


@dataclass(frozen=True, slots=True)
class ToyEpochSpecification:
    """One synthetic epoch with explicit baseline stellar velocity and noise seed."""

    epoch_id: str
    baseline_velocity_m_s: float
    noise_seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "epoch_id", _label(self.epoch_id, "epoch_id"))
        velocity = _finite_float(self.baseline_velocity_m_s, "baseline_velocity_m_s")
        object.__setattr__(
            self,
            "baseline_velocity_m_s",
            0.0 if velocity == 0.0 else velocity,
        )
        if type(self.noise_seed) is not int or self.noise_seed < 0:
            raise TemplateChainDataError("noise_seed must be a non-negative native integer")


@dataclass(frozen=True, slots=True)
class ToyOrderSpecification:
    """One arbitrary synthetic wavelength grid and two line locations."""

    order_id: str
    wavelength_start: float
    wavelength_step: float
    stellar_line_center: float
    telluric_line_center: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "order_id", _label(self.order_id, "order_id"))
        object.__setattr__(
            self,
            "wavelength_start",
            _positive_float(self.wavelength_start, "wavelength_start"),
        )
        object.__setattr__(
            self,
            "wavelength_step",
            _positive_float(self.wavelength_step, "wavelength_step"),
        )
        object.__setattr__(
            self,
            "stellar_line_center",
            _positive_float(self.stellar_line_center, "stellar_line_center"),
        )
        object.__setattr__(
            self,
            "telluric_line_center",
            _positive_float(self.telluric_line_center, "telluric_line_center"),
        )


@dataclass(frozen=True, slots=True)
class ToyControlSpecification:
    """Fully explicit, non-instrumental inputs for the toy generator."""

    control_label: str
    epochs: tuple[ToyEpochSpecification, ...]
    orders: tuple[ToyOrderSpecification, ...]
    sample_count: int
    stellar_depth: float
    stellar_width: float
    telluric_depth: float
    telluric_width: float
    lsf_kernel: tuple[float, ...]
    noise_standard_deviation: float
    specification_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        label = _label(self.control_label, "control_label")
        epochs = tuple(self.epochs)
        orders = tuple(self.orders)
        if len(epochs) < 2 or any(type(item) is not ToyEpochSpecification for item in epochs):
            raise TemplateChainDataError(
                "epochs must contain at least two ToyEpochSpecification values"
            )
        if not orders or any(type(item) is not ToyOrderSpecification for item in orders):
            raise TemplateChainDataError("orders must contain ToyOrderSpecification values")
        if len({item.epoch_id for item in epochs}) != len(epochs):
            raise TemplateChainDataError("toy epoch IDs must be unique")
        if len({item.order_id for item in orders}) != len(orders):
            raise TemplateChainDataError("toy order IDs must be unique")
        if type(self.sample_count) is not int or self.sample_count < 8:
            raise TemplateChainDataError("sample_count must be a native integer of at least 8")
        stellar_depth = _unit_interval(self.stellar_depth, "stellar_depth", allow_zero=False)
        stellar_width = _positive_float(self.stellar_width, "stellar_width")
        telluric_depth = _unit_interval(self.telluric_depth, "telluric_depth", allow_zero=True)
        telluric_width = _positive_float(self.telluric_width, "telluric_width")
        noise = _finite_float(self.noise_standard_deviation, "noise_standard_deviation")
        if noise < 0.0:
            raise TemplateChainDataError("noise_standard_deviation must be non-negative")
        kernel = tuple(self.lsf_kernel)
        if not kernel or any(type(item) is not float for item in kernel):
            raise TemplateChainDataError("lsf_kernel must contain native floats")
        kernel_array = np.asarray(kernel, dtype=np.float64)
        if (
            not np.all(np.isfinite(kernel_array))
            or np.any(kernel_array < 0.0)
            or not np.isclose(float(np.sum(kernel_array)), 1.0, rtol=1e-12, atol=1e-12)
        ):
            raise TemplateChainDataError("lsf_kernel must be finite, non-negative, and unit-sum")
        if len(kernel) > self.sample_count:
            raise TemplateChainDataError("lsf_kernel cannot exceed sample_count")
        for order in orders:
            last = order.wavelength_start + (self.sample_count - 1) * order.wavelength_step
            if not order.wavelength_start < order.stellar_line_center < last:
                raise TemplateChainDataError("stellar line center must lie inside its toy grid")
            if not order.wavelength_start < order.telluric_line_center < last:
                raise TemplateChainDataError("telluric line center must lie inside its toy grid")

        for name, value in (
            ("control_label", label),
            ("epochs", epochs),
            ("orders", orders),
            ("stellar_depth", stellar_depth),
            ("stellar_width", stellar_width),
            ("telluric_depth", telluric_depth),
            ("telluric_width", telluric_width),
            ("lsf_kernel", kernel),
            ("noise_standard_deviation", noise),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "specification_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "control_label": self.control_label,
                "epochs": [
                    {
                        "baseline_velocity_m_s_hex": item.baseline_velocity_m_s.hex(),
                        "epoch_id": item.epoch_id,
                        "noise_seed": item.noise_seed,
                    }
                    for item in self.epochs
                ],
                "lsf_kernel_hex": [item.hex() for item in self.lsf_kernel],
                "noise_standard_deviation_hex": self.noise_standard_deviation.hex(),
                "orders": [
                    {
                        "order_id": item.order_id,
                        "stellar_line_center_hex": item.stellar_line_center.hex(),
                        "telluric_line_center_hex": item.telluric_line_center.hex(),
                        "wavelength_start_hex": item.wavelength_start.hex(),
                        "wavelength_step_hex": item.wavelength_step.hex(),
                    }
                    for item in self.orders
                ],
                "sample_count": self.sample_count,
                "stellar_depth_hex": self.stellar_depth.hex(),
                "stellar_width_hex": self.stellar_width.hex(),
                "telluric_depth_hex": self.telluric_depth.hex(),
                "telluric_width_hex": self.telluric_width.hex(),
            }
        )

    def verify_integrity(self) -> None:
        rebuilt = ToyControlSpecification(
            control_label=self.control_label,
            epochs=tuple(
                ToyEpochSpecification(
                    item.epoch_id,
                    item.baseline_velocity_m_s,
                    item.noise_seed,
                )
                for item in self.epochs
            ),
            orders=tuple(
                ToyOrderSpecification(
                    item.order_id,
                    item.wavelength_start,
                    item.wavelength_step,
                    item.stellar_line_center,
                    item.telluric_line_center,
                )
                for item in self.orders
            ),
            sample_count=self.sample_count,
            stellar_depth=self.stellar_depth,
            stellar_width=self.stellar_width,
            telluric_depth=self.telluric_depth,
            telluric_width=self.telluric_width,
            lsf_kernel=self.lsf_kernel,
            noise_standard_deviation=self.noise_standard_deviation,
        )
        if rebuilt.specification_sha256 != self.specification_sha256:
            raise TemplateChainDataError("toy control specification content hash mismatch")


@dataclass(frozen=True, slots=True)
class ToySyntheticControl:
    """Replay-verified toy exposures and their deterministic baseline truth."""

    specification: ToyControlSpecification
    exposures: ExposureSet
    control_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.specification) is not ToyControlSpecification:
            raise TemplateChainDataError("specification must be a ToyControlSpecification")
        self.specification.verify_integrity()
        if type(self.exposures) is not ExposureSet:
            raise TemplateChainDataError("exposures must be an ExposureSet")
        self.exposures.verify_integrity()
        expected_epochs = tuple(item.epoch_id for item in self.specification.epochs)
        expected_orders = tuple(item.order_id for item in self.specification.orders)
        if (
            self.exposures.epoch_ids != expected_epochs
            or self.exposures.order_ids != expected_orders
        ):
            raise TemplateChainDataError("generated exposure labels do not match the specification")
        expected = _generate_toy_exposures(self.specification)
        if expected.content_sha256 != self.exposures.content_sha256:
            raise TemplateChainDataError(
                "toy exposures do not exactly replay from the retained specification"
            )
        object.__setattr__(
            self,
            "control_sha256",
            self.recompute_sha256(),
        )

    def recompute_sha256(self) -> str:
        return canonical_sha256(
            {
                "exposure_sha256": self.exposures.recompute_sha256(),
                "specification_sha256": self.specification.recompute_sha256(),
            }
        )

    def verify_integrity(self) -> None:
        rebuilt = ToySyntheticControl(
            specification=self.specification,
            exposures=self.exposures,
        )
        if rebuilt.control_sha256 != self.control_sha256:
            raise TemplateChainDataError("toy synthetic control content hash mismatch")


def _generate_toy_exposures(specification: ToyControlSpecification) -> ExposureSet:
    if type(specification) is not ToyControlSpecification:
        raise TypeError("specification must be a ToyControlSpecification")
    specification.verify_integrity()
    records: list[FrozenSpectralExposure] = []
    kernel = np.asarray(specification.lsf_kernel, dtype=np.float64)
    for epoch in specification.epochs:
        for order_index, order in enumerate(specification.orders):
            wavelength = order.wavelength_start + order.wavelength_step * np.arange(
                specification.sample_count,
                dtype=np.float64,
            )
            stellar = 1.0 - specification.stellar_depth * np.exp(
                -0.5 * ((wavelength - order.stellar_line_center) / specification.stellar_width) ** 2
            )
            telluric = 1.0 - specification.telluric_depth * np.exp(
                -0.5
                * ((wavelength - order.telluric_line_center) / specification.telluric_width) ** 2
            )
            rng = np.random.default_rng(np.random.SeedSequence([epoch.noise_seed, order_index]))
            noise = rng.normal(
                0.0,
                specification.noise_standard_deviation,
                specification.sample_count,
            )
            base = DecomposedSpectralExposure(
                wavelength=wavelength,
                stellar_flux=stellar,
                telluric_transmission=telluric,
                lsf_kernel=kernel,
                noise=noise,
            )
            shifted = inject_stellar_velocity(base, epoch.baseline_velocity_m_s)
            if not check_injection_invariants(
                base,
                shifted,
                expected_velocity_m_s=epoch.baseline_velocity_m_s,
            ).passed:
                raise TemplateChainExecutionError("toy baseline injection invariants failed")
            records.append(
                FrozenSpectralExposure(
                    epoch_id=epoch.epoch_id,
                    order_id=order.order_id,
                    wavelength=shifted.wavelength,
                    stellar_flux=shifted.shifted_stellar_flux,
                    telluric_transmission=shifted.telluric_transmission,
                    lsf_kernel=shifted.lsf_kernel,
                    noise=shifted.noise,
                )
            )
    return ExposureSet(
        epoch_ids=tuple(item.epoch_id for item in specification.epochs),
        order_ids=tuple(item.order_id for item in specification.orders),
        records=tuple(records),
    )


def generate_toy_control(specification: ToyControlSpecification) -> ToySyntheticControl:
    """Generate deterministic Gaussian-line arrays for wiring tests only."""
    exposures = _generate_toy_exposures(specification)
    return ToySyntheticControl(specification=specification, exposures=exposures)


def _observed_cube(data: ExposureSet) -> np.ndarray:
    rows: list[np.ndarray] = []
    expected_shape: tuple[int, ...] | None = None
    for epoch_id in data.epoch_ids:
        order_rows: list[np.ndarray] = []
        for order_id in data.order_ids:
            observed = np.asarray(data.get(epoch_id, order_id).observed_flux())
            if expected_shape is None:
                expected_shape = observed.shape
            elif observed.shape != expected_shape:
                raise TemplateChainExecutionError(
                    "toy adapter requires equal pixel counts across requested orders"
                )
            order_rows.append(observed)
        rows.append(np.stack(order_rows))
    return np.stack(rows)


def _centroid(flux: np.ndarray) -> float:
    if flux.ndim != 1 or not np.all(np.isfinite(flux)):
        raise TemplateChainExecutionError("toy centroid requires one finite flux vector")
    continuum = float(np.max(flux))
    weights = np.maximum(continuum - flux, 0.0)
    total = float(np.sum(weights))
    if not np.isfinite(total) or total <= 0.0:
        raise TemplateChainExecutionError("toy centroid has no positive line weight")
    coordinate = np.arange(flux.size, dtype=np.float64)
    value = float(np.sum(coordinate * weights) / total)
    if not np.isfinite(value):
        raise TemplateChainExecutionError("toy centroid became non-finite")
    return value


class ToyTemplateSession:
    """Stateful, lineage-locked session used only by :class:`ToyTemplateAdapterFactory`."""

    def __init__(
        self,
        invocation: ChainInvocation,
        session_token: str,
        *,
        relaxation: float,
        adjacent_noise_scale: float,
    ) -> None:
        self._invocation_sha256 = invocation.invocation_sha256
        self._session_token = _label(session_token, "session_token")
        self._relaxation = relaxation
        self._adjacent_noise_scale = adjacent_noise_scale
        self._initial_created = False
        self._last_training_fit_index: int | None = None

    @property
    def session_token(self) -> str:
        return self._session_token

    def _check_invocation(self, invocation: ChainInvocation) -> None:
        if type(invocation) is not ChainInvocation:
            raise TemplateChainExecutionError("toy adapter requires a ChainInvocation")
        if invocation.invocation_sha256 != self._invocation_sha256:
            raise TemplateChainExecutionError("toy session was used with a different lineage")

    def initial_template(
        self,
        training_data: ExposureSet,
        invocation: ChainInvocation,
    ) -> TemplateState:
        self._check_invocation(invocation)
        if self._initial_created:
            raise TemplateChainExecutionError("toy initial template cannot be reused as a cache")
        if training_data.epoch_ids != invocation.training_epoch_ids:
            raise TemplateChainExecutionError("toy training epochs changed")
        if training_data.order_ids != invocation.template_order_ids:
            raise TemplateChainExecutionError("toy template orders changed")
        cube = _observed_cube(training_data)
        seed = np.array(cube[0], copy=True)
        self._initial_created = True
        return TemplateState(
            invocation_sha256=invocation.invocation_sha256,
            state_index=0,
            order_ids=invocation.template_order_ids,
            flux=seed,
            valid_mask=np.isfinite(seed),
        )

    def _fit(
        self,
        data: ExposureSet,
        template: TemplateState,
        invocation: ChainInvocation,
        *,
        role: str,
    ) -> RVState:
        self._check_invocation(invocation)
        template_index = {order_id: index for index, order_id in enumerate(template.order_ids)}
        if not set(data.order_ids).issubset(template_index):
            raise TemplateChainExecutionError("toy fit order is absent from the template")
        cube = _observed_cube(data)
        values = np.empty((len(data.epoch_ids), len(data.order_ids)), dtype=np.float64)
        for epoch_index in range(len(data.epoch_ids)):
            for order_index, order_id in enumerate(data.order_ids):
                template_row = template.flux[template_index[order_id]]
                values[epoch_index, order_index] = _centroid(
                    cube[epoch_index, order_index]
                ) - _centroid(template_row)
        rv_role = "training" if role == "training" else "evaluation"
        return RVState(
            invocation_sha256=invocation.invocation_sha256,
            state_index=template.state_index,
            role=rv_role,
            epoch_ids=data.epoch_ids,
            order_ids=data.order_ids,
            values=values,
            valid_mask=np.isfinite(values),
        )

    def fit_training(
        self,
        training_data: ExposureSet,
        template: TemplateState,
        invocation: ChainInvocation,
    ) -> RVState:
        if not self._initial_created:
            raise TemplateChainExecutionError("toy training fit preceded iteration zero")
        if self._last_training_fit_index is not None and template.state_index != (
            self._last_training_fit_index + 1
        ):
            raise TemplateChainExecutionError("toy training states are not fresh and contiguous")
        result = self._fit(training_data, template, invocation, role="training")
        self._last_training_fit_index = template.state_index
        return result

    def update_template(
        self,
        training_data: ExposureSet,
        previous_template: TemplateState,
        previous_rv: RVState,
        *,
        state_index: int,
        invocation: ChainInvocation,
    ) -> TemplateState:
        self._check_invocation(invocation)
        if self._last_training_fit_index != previous_template.state_index:
            raise TemplateChainExecutionError("toy template update lacks its fresh training fit")
        if previous_rv.state_index != previous_template.state_index or state_index != (
            previous_template.state_index + 1
        ):
            raise TemplateChainExecutionError("toy update state indices are not contiguous")
        cube = _observed_cube(training_data)
        target = np.mean(cube, axis=0)
        updated = previous_template.flux + self._relaxation * (target - previous_template.flux)
        return TemplateState(
            invocation_sha256=invocation.invocation_sha256,
            state_index=state_index,
            order_ids=invocation.template_order_ids,
            flux=updated,
            valid_mask=np.isfinite(updated),
        )

    def adjacent_noise_scale(
        self,
        previous_template: TemplateState,
        current_template: TemplateState,
        invocation: ChainInvocation,
    ) -> np.ndarray:
        self._check_invocation(invocation)
        if previous_template.state_index + 1 != current_template.state_index:
            raise TemplateChainExecutionError("toy adjacent template states are not contiguous")
        if not np.array_equal(previous_template.valid_mask, current_template.valid_mask):
            raise TemplateChainExecutionError("toy template mask changed")
        return np.where(
            current_template.valid_mask,
            self._adjacent_noise_scale,
            np.nan,
        )

    def fit_evaluation(
        self,
        evaluation_data: ExposureSet,
        template: TemplateState,
        invocation: ChainInvocation,
    ) -> RVState:
        if self._last_training_fit_index != template.state_index:
            raise TemplateChainExecutionError(
                "toy evaluation did not follow the final training fit"
            )
        if evaluation_data.epoch_ids != invocation.evaluation_epoch_ids:
            raise TemplateChainExecutionError("toy evaluation epochs changed")
        if evaluation_data.order_ids != invocation.fit_order_ids:
            raise TemplateChainExecutionError("toy evaluation orders changed")
        return self._fit(evaluation_data, template, invocation, role="evaluation")


class ToyTemplateAdapterFactory:
    """Fresh-session factory for the wiring-only toy adapter.

    ``relaxation`` and ``adjacent_noise_scale`` are mandatory engineering inputs.  They are not
    recommended scientific values and the factory intentionally supplies no defaults.
    """

    def __init__(
        self,
        *,
        adapter_label: str,
        relaxation: float,
        adjacent_noise_scale: float,
    ) -> None:
        label = _label(adapter_label, "adapter_label")
        relaxation_value = _unit_interval(relaxation, "relaxation", allow_zero=False)
        noise_value = _positive_float(adjacent_noise_scale, "adjacent_noise_scale")
        configuration = canonical_sha256(
            {
                "adapter_label": label,
                "adjacent_noise_scale_hex": noise_value.hex(),
                "relaxation_hex": relaxation_value.hex(),
                "warning": "wiring-only toy adapter; not a scientific extraction",
            }
        )
        self._identity = AdapterIdentity(
            adapter_name="m38-pure-python-toy-template-adapter",
            adapter_version="1",
            configuration_sha256=configuration,
        )
        self._relaxation = relaxation_value
        self._adjacent_noise_scale = noise_value
        self._creation_count = 0
        self._created_invocation_sha256: list[str] = []

    @property
    def identity(self) -> AdapterIdentity:
        return self._identity

    @property
    def created_invocation_sha256(self) -> tuple[str, ...]:
        return tuple(self._created_invocation_sha256)

    def create_session(self, invocation: ChainInvocation) -> ToyTemplateSession:
        if type(invocation) is not ChainInvocation:
            raise TemplateChainExecutionError("toy factory requires a ChainInvocation")
        counter = self._creation_count
        self._creation_count += 1
        token = canonical_sha256(
            {
                "adapter_identity_sha256": self.identity.identity_sha256,
                "creation_counter": counter,
                "invocation_sha256": invocation.invocation_sha256,
            }
        )
        self._created_invocation_sha256.append(invocation.invocation_sha256)
        return ToyTemplateSession(
            invocation,
            token,
            relaxation=self._relaxation,
            adjacent_noise_scale=self._adjacent_noise_scale,
        )


__all__ = [
    "ToyControlSpecification",
    "ToyEpochSpecification",
    "ToyOrderSpecification",
    "ToySyntheticControl",
    "ToyTemplateAdapterFactory",
    "ToyTemplateSession",
    "generate_toy_control",
]
