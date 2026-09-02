"""Synthetic-only tests for the explicitly non-scientific M38 toy controls."""

from dataclasses import replace

import numpy as np
import pytest

from exosat_rv.m38.convergence import ConvergencePolicy
from exosat_rv.m38.provenance import canonical_sha256
from exosat_rv.m38.synthetic_controls import (
    ToyControlSpecification,
    ToyEpochSpecification,
    ToyOrderSpecification,
    ToySyntheticControl,
    ToyTemplateAdapterFactory,
    generate_toy_control,
)
from exosat_rv.m38.template_chain import (
    CrossInjectionMaskContract,
    EpochVelocity,
    ExtractionArm,
    OrderPropagationPlan,
    PreTemplateInjectionPlan,
    TemplateChainDataError,
    TemplateChainRoster,
    WorkflowFreshnessRegistry,
    make_disjoint_fold_plan,
    run_template_chain_ensemble,
)


def toy_specification() -> ToyControlSpecification:
    return ToyControlSpecification(
        control_label="arbitrary-wiring-fixture",
        epochs=(
            ToyEpochSpecification("epoch-a", -2_000.0, 101),
            ToyEpochSpecification("epoch-b", 0.0, 202),
            ToyEpochSpecification("epoch-c", 2_500.0, 303),
        ),
        orders=(
            ToyOrderSpecification("order-x", 500.0, 0.001, 500.064, 500.090),
            ToyOrderSpecification("order-y", 600.0, 0.001, 600.061, 600.094),
        ),
        sample_count=129,
        stellar_depth=0.4,
        stellar_width=0.006,
        telluric_depth=0.2,
        telluric_width=0.005,
        lsf_kernel=(0.2, 0.6, 0.2),
        noise_standard_deviation=0.0005,
    )


def zero_plan(specification: ToyControlSpecification) -> PreTemplateInjectionPlan:
    epoch_ids = tuple(item.epoch_id for item in specification.epochs)
    return PreTemplateInjectionPlan(
        plan_label="explicit-zero-wiring-plan",
        epoch_ids=epoch_ids,
        velocities=tuple(EpochVelocity(epoch_id, 0.0) for epoch_id in epoch_ids),
    )


def test_generator_is_deterministic_content_bound_and_byte_immutable() -> None:
    specification = toy_specification()
    first = generate_toy_control(specification)
    second = generate_toy_control(specification)

    assert first.control_sha256 == second.control_sha256
    assert first.exposures.content_sha256 == second.exposures.content_sha256
    assert first.exposures.epoch_ids == ("epoch-a", "epoch-b", "epoch-c")
    assert first.exposures.order_ids == ("order-x", "order-y")
    first.exposures.verify_integrity()
    first.specification.verify_integrity()
    first.verify_integrity()
    assert first.recompute_sha256() == first.control_sha256

    record = first.exposures.get("epoch-a", "order-x")
    assert not record.stellar_flux.flags.writeable
    with pytest.raises(ValueError):
        record.stellar_flux.setflags(write=True)


def test_toy_control_rejects_relabelled_seed_derivation() -> None:
    specification = toy_specification()
    changed = replace(
        specification,
        epochs=(
            replace(
                specification.epochs[0],
                noise_seed=specification.epochs[0].noise_seed + 1,
            ),
            *specification.epochs[1:],
        ),
    )
    changed_control = generate_toy_control(changed)

    with pytest.raises(TemplateChainDataError, match="do not exactly replay"):
        ToySyntheticControl(
            specification=specification,
            exposures=changed_control.exposures,
        )


def test_toy_spec_and_control_recursive_integrity_detect_tampering() -> None:
    specification = toy_specification()
    control = generate_toy_control(specification)

    object.__setattr__(specification, "noise_standard_deviation", 0.001)
    with pytest.raises(TemplateChainDataError, match="specification content hash mismatch"):
        specification.verify_integrity()
    with pytest.raises(TemplateChainDataError, match="specification content hash mismatch"):
        control.verify_integrity()


def test_noise_seed_and_truth_velocity_are_part_of_generated_identity() -> None:
    specification = toy_specification()
    changed_epoch = replace(specification.epochs[0], noise_seed=102)
    changed_specification = replace(
        specification,
        epochs=(changed_epoch, *specification.epochs[1:]),
    )
    velocity_specification = replace(
        specification,
        epochs=(
            replace(specification.epochs[0], baseline_velocity_m_s=-1_500.0),
            *specification.epochs[1:],
        ),
    )

    baseline = generate_toy_control(specification)
    changed_noise = generate_toy_control(changed_specification)
    changed_velocity = generate_toy_control(velocity_specification)

    assert baseline.control_sha256 != changed_noise.control_sha256
    assert baseline.control_sha256 != changed_velocity.control_sha256
    assert baseline.exposures.content_sha256 != changed_noise.exposures.content_sha256
    assert baseline.exposures.content_sha256 != changed_velocity.exposures.content_sha256


def test_baseline_truth_moves_only_the_stellar_component() -> None:
    control = generate_toy_control(toy_specification())
    moving = control.exposures.get("epoch-a", "order-x")
    stationary = control.exposures.get("epoch-b", "order-x")

    assert not np.array_equal(moving.stellar_flux, stationary.stellar_flux)
    assert np.array_equal(moving.wavelength, stationary.wavelength)
    assert np.array_equal(moving.telluric_transmission, stationary.telluric_transmission)
    assert np.array_equal(moving.lsf_kernel, stationary.lsf_kernel)
    assert not np.array_equal(moving.noise, stationary.noise)


def test_toy_adapter_exercises_chain_wiring_without_supplying_thresholds() -> None:
    specification = toy_specification()
    control = generate_toy_control(specification)
    fold_plan = make_disjoint_fold_plan(
        ("epoch-a", "epoch-b"),
        ("epoch-c",),
        fold_id="held-out-c",
    )
    order_plan = OrderPropagationPlan(
        mode="common",
        available_order_ids=control.exposures.order_ids,
        arms=(ExtractionArm("toy-arm", ("order-x",)),),
        common_template_order_ids=control.exposures.order_ids,
    )
    policy = ConvergencePolicy(
        d_template_limit=1_000_000.0,
        d_rv_limit=1_000_000.0,
        q_conv=1,
        k_max=2,
        template_aggregate="maximum",
    )
    factory = ToyTemplateAdapterFactory(
        adapter_label="test-only",
        relaxation=0.5,
        adjacent_noise_scale=1.0,
    )

    result = run_template_chain_ensemble(
        control.exposures,
        (zero_plan(specification),),
        fold_plan,
        order_plan,
        policy,
        factory,
        mask_contract=CrossInjectionMaskContract(
            reference_plan_sha256=zero_plan(specification).plan_sha256,
            roster_sha256=TemplateChainRoster(
                fold_plan=fold_plan,
                order_plan=order_plan,
            ).roster_sha256,
        ),
        ensemble_nonce=canonical_sha256({"test": "toy-adapter-chain"}),
        freshness_registry=WorkflowFreshnessRegistry(),
    )

    fold = result.trials[0].fold_results[0]
    assert fold.convergence.converged
    assert fold.evaluation_rv is not None
    assert fold.evaluation_rv.epoch_ids == ("epoch-c",)
    assert fold.evaluation_rv.order_ids == ("order-x",)
    assert fold.invocation.template_order_ids == ("order-x", "order-y")
    assert len(factory.created_invocation_sha256) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        {"sample_count": 7},
        {"stellar_depth": 0.0},
        {"telluric_depth": 1.1},
        {"lsf_kernel": (0.2, 0.2)},
        {"noise_standard_deviation": -0.1},
    ],
)
def test_invalid_toy_specifications_fail_closed(mutation: dict[str, object]) -> None:
    with pytest.raises(TemplateChainDataError):
        replace(toy_specification(), **mutation)


def test_duplicate_labels_and_out_of_grid_lines_fail_closed() -> None:
    specification = toy_specification()
    with pytest.raises(TemplateChainDataError, match="epoch IDs"):
        replace(
            specification,
            epochs=(specification.epochs[0], specification.epochs[0]),
        )
    with pytest.raises(TemplateChainDataError, match="inside"):
        replace(
            specification,
            orders=(
                replace(specification.orders[0], stellar_line_center=900.0),
                specification.orders[1],
            ),
        )
