"""Adversarial synthetic tests for the M38 cross-fitted template-chain contracts."""

from itertools import count

import numpy as np
import pytest

from exosat_rv.m38.convergence import ConvergencePolicy
from exosat_rv.m38.provenance import canonical_sha256
from exosat_rv.m38.synthetic_controls import (
    ToyControlSpecification,
    ToyEpochSpecification,
    ToyOrderSpecification,
    ToyTemplateAdapterFactory,
    ToyTemplateSession,
    generate_toy_control,
)
from exosat_rv.m38.template_chain import (
    AdapterIdentity,
    AppliedInjection,
    CrossInjectionMaskContract,
    EpochVelocity,
    ExtractionArm,
    FoldChainResult,
    FoldPlan,
    InjectionTrialResult,
    OrderPropagationPlan,
    PreTemplateInjectionPlan,
    RVState,
    TemplateChainDataError,
    TemplateChainEnsembleResult,
    TemplateChainExecutionError,
    TemplateChainRoster,
    TemplateFold,
    TemplateState,
    WorkflowFreshnessRegistry,
    apply_pre_template_injection,
    make_disjoint_fold_plan,
    make_leave_one_out_fold_plan,
)
from exosat_rv.m38.template_chain import (
    run_template_chain_ensemble as _source_run_template_chain_ensemble,
)

_TEST_ENSEMBLE_NONCE_COUNTER = count()


def ensemble_nonce(label: str = "template-chain-test") -> str:
    return canonical_sha256(
        {
            "label": label,
            "test_ensemble_index": next(_TEST_ENSEMBLE_NONCE_COUNTER),
        }
    )


def _run_template_chain_ensemble(*args, **kwargs):
    """Bind explicit fresh-run evidence unless an adversarial test supplies its own."""
    if "ensemble_nonce" not in kwargs:
        kwargs["ensemble_nonce"] = ensemble_nonce()
    if "freshness_registry" not in kwargs:
        kwargs["freshness_registry"] = WorkflowFreshnessRegistry()
    return _source_run_template_chain_ensemble(*args, **kwargs)


def control_fixture():
    specification = ToyControlSpecification(
        control_label="chain-wiring-fixture",
        epochs=(
            ToyEpochSpecification("e0", -1_500.0, 11),
            ToyEpochSpecification("e1", -500.0, 22),
            ToyEpochSpecification("e2", 750.0, 33),
            ToyEpochSpecification("e3", 1_750.0, 44),
        ),
        orders=(
            ToyOrderSpecification("o0", 400.0, 0.001, 400.050, 400.085),
            ToyOrderSpecification("o1", 500.0, 0.001, 500.052, 500.082),
            ToyOrderSpecification("o2", 600.0, 0.001, 600.054, 600.080),
        ),
        sample_count=129,
        stellar_depth=0.35,
        stellar_width=0.006,
        telluric_depth=0.15,
        telluric_width=0.004,
        lsf_kernel=(0.25, 0.5, 0.25),
        noise_standard_deviation=0.0002,
    )
    return generate_toy_control(specification)


def plan(
    label: str,
    velocities: tuple[float, ...],
    *,
    replicate_identity_sha256: str | None = None,
) -> PreTemplateInjectionPlan:
    epoch_ids = ("e0", "e1", "e2", "e3")
    return PreTemplateInjectionPlan(
        plan_label=label,
        epoch_ids=epoch_ids,
        velocities=tuple(
            EpochVelocity(epoch_id, velocity)
            for epoch_id, velocity in zip(epoch_ids, velocities, strict=True)
        ),
        replicate_identity_sha256=replicate_identity_sha256,
    )


def permissive_policy() -> ConvergencePolicy:
    return ConvergencePolicy(
        d_template_limit=1_000_000.0,
        d_rv_limit=1_000_000.0,
        q_conv=1,
        k_max=2,
        template_aggregate="maximum",
    )


def toy_factory() -> ToyTemplateAdapterFactory:
    return ToyTemplateAdapterFactory(
        adapter_label="template-chain-test",
        relaxation=0.5,
        adjacent_noise_scale=1.0,
    )


def common_orders() -> OrderPropagationPlan:
    return OrderPropagationPlan(
        mode="common",
        available_order_ids=("o0", "o1", "o2"),
        arms=(
            ExtractionArm("left", ("o0", "o1")),
            ExtractionArm("right", ("o2",)),
        ),
        common_template_order_ids=("o0", "o1", "o2"),
    )


def mask_contract(
    reference_plan: PreTemplateInjectionPlan,
    fold_plan: FoldPlan,
    order_plan: OrderPropagationPlan,
) -> CrossInjectionMaskContract:
    roster = TemplateChainRoster(fold_plan=fold_plan, order_plan=order_plan)
    return CrossInjectionMaskContract(
        reference_plan_sha256=reference_plan.plan_sha256,
        roster_sha256=roster.roster_sha256,
    )


def run_template_chain_ensemble(
    source,
    injection_plans,
    fold_plan,
    order_plan,
    convergence_policy,
    adapter_factory,
    **kwargs,
):
    """Test helper that always binds the first supplied plan as the mask reference."""
    plans = tuple(injection_plans)
    return _run_template_chain_ensemble(
        source,
        plans,
        fold_plan,
        order_plan,
        convergence_policy,
        adapter_factory,
        mask_contract=mask_contract(plans[0], fold_plan, order_plan),
        **kwargs,
    )


def test_disjoint_and_leave_one_out_plans_exclude_every_evaluation_epoch() -> None:
    disjoint = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    leave_one_out = make_leave_one_out_fold_plan(("e0", "e1", "e2", "e3"))

    assert disjoint.folds[0].training_epoch_ids == ("e0", "e1")
    assert disjoint.folds[0].evaluation_epoch_ids == ("e2", "e3")
    for fold in (*disjoint.folds, *leave_one_out.folds):
        assert set(fold.training_epoch_ids).isdisjoint(fold.evaluation_epoch_ids)
    assert [fold.evaluation_epoch_ids for fold in leave_one_out.folds] == [
        ("e0",),
        ("e1",),
        ("e2",),
        ("e3",),
    ]


def test_overlapping_or_incomplete_fold_plans_fail_closed() -> None:
    with pytest.raises(TemplateChainDataError, match="disjoint"):
        TemplateFold("bad", ("e0", "e1"), ("e1",))
    with pytest.raises(TemplateChainDataError, match="partition"):
        FoldPlan(
            strategy="disjoint",
            epoch_ids=("e0", "e1", "e2"),
            folds=(TemplateFold("bad", ("e0",), ("e1",)),),
        )
    with pytest.raises(TemplateChainDataError, match="one fold per epoch"):
        FoldPlan(
            strategy="leave_one_out",
            epoch_ids=("e0", "e1", "e2"),
            folds=(TemplateFold("loo", ("e1", "e2"), ("e0",)),),
        )


def test_common_template_orders_and_arm_fit_orders_propagate_separately() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1", "e2"), ("e3",), fold_id="holdout")
    result = run_template_chain_ensemble(
        control.exposures,
        (plan("common-run", (0.0, 0.0, 0.0, 0.0)),),
        fold_plan,
        common_orders(),
        permissive_policy(),
        toy_factory(),
    )

    left, right = result.trials[0].fold_results
    assert left.invocation.template_order_ids == ("o0", "o1", "o2")
    assert right.invocation.template_order_ids == ("o0", "o1", "o2")
    assert left.training_rv_states[0].order_ids == ("o0", "o1", "o2")
    assert right.training_rv_states[0].order_ids == ("o0", "o1", "o2")
    assert left.evaluation_rv is not None
    assert right.evaluation_rv is not None
    assert left.evaluation_rv.order_ids == ("o0", "o1")
    assert right.evaluation_rv.order_ids == ("o2",)


def test_arm_specific_template_orders_propagate_through_the_complete_chain() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1", "e2"), ("e3",), fold_id="holdout")
    order_plan = OrderPropagationPlan(
        mode="arm_specific",
        available_order_ids=("o0", "o1", "o2"),
        arms=(
            ExtractionArm("left", ("o0", "o1")),
            ExtractionArm("right", ("o2",)),
        ),
        common_template_order_ids=None,
    )

    result = run_template_chain_ensemble(
        control.exposures,
        (plan("arm-specific-run", (0.0, 0.0, 0.0, 0.0)),),
        fold_plan,
        order_plan,
        permissive_policy(),
        toy_factory(),
    )

    for fold_result in result.trials[0].fold_results:
        assert fold_result.invocation.template_order_ids == fold_result.invocation.fit_order_ids
        assert all(
            state.order_ids == fold_result.invocation.fit_order_ids
            for state in fold_result.template_states
        )


def test_every_injection_gets_fresh_full_sessions_and_independent_source_application() -> None:
    control = control_fixture()
    fold_plan = make_leave_one_out_fold_plan(control.exposures.epoch_ids)
    injection_plans = (
        plan("positive", (500.0, 1_000.0, 1_500.0, 2_000.0)),
        plan("negative", (-500.0, -1_000.0, -1_500.0, -2_000.0)),
    )
    factory = toy_factory()

    result = run_template_chain_ensemble(
        control.exposures,
        injection_plans,
        fold_plan,
        common_orders(),
        permissive_policy(),
        factory,
    )

    fold_count = len(fold_plan.folds) * len(common_orders().arms)
    assert len(factory.created_invocation_sha256) == len(injection_plans) * fold_count
    session_tokens = [fold.session_token for trial in result.trials for fold in trial.fold_results]
    assert len(set(session_tokens)) == len(session_tokens)
    assert all(
        trial.applied_injection.source_exposure_sha256 == control.exposures.content_sha256
        for trial in result.trials
    )
    assert result.trials[0].applied_injection.exposures.content_sha256 != (
        result.trials[1].applied_injection.exposures.content_sha256
    )
    assert control.exposures.content_sha256 == result.source_exposure_sha256
    control.exposures.verify_integrity()


def test_applied_injection_retains_source_and_rejects_relabelled_derivation() -> None:
    control = control_fixture()
    zero = plan("zero-application", (0.0, 0.0, 0.0, 0.0))
    moving = plan("moving-application", (10.0, 20.0, 30.0, 40.0))
    zero_application = apply_pre_template_injection(control.exposures, zero)
    moving_application = apply_pre_template_injection(control.exposures, moving)

    assert zero_application.source is control.exposures
    zero_application.verify_integrity()
    assert zero_application.exposures.content_sha256 != moving_application.exposures.content_sha256
    with pytest.raises(TemplateChainDataError, match="do not exactly replay"):
        AppliedInjection(
            plan=moving,
            source=control.exposures,
            exposures=zero_application.exposures,
        )


class RecordingSession:
    def __init__(self, delegate: ToyTemplateSession, seen_training: list[tuple[str, ...]]) -> None:
        self._delegate = delegate
        self._seen_training = seen_training

    @property
    def session_token(self) -> str:
        return self._delegate.session_token

    def initial_template(self, training_data, invocation):
        self._seen_training.append(training_data.epoch_ids)
        return self._delegate.initial_template(training_data, invocation)

    def fit_training(self, training_data, template, invocation):
        return self._delegate.fit_training(training_data, template, invocation)

    def update_template(self, training_data, previous_template, previous_rv, **kwargs):
        return self._delegate.update_template(
            training_data,
            previous_template,
            previous_rv,
            **kwargs,
        )

    def adjacent_noise_scale(self, previous_template, current_template, invocation):
        return self._delegate.adjacent_noise_scale(
            previous_template,
            current_template,
            invocation,
        )

    def fit_evaluation(self, evaluation_data, template, invocation):
        return self._delegate.fit_evaluation(evaluation_data, template, invocation)


class RecordingFactory:
    def __init__(self) -> None:
        self._delegate = toy_factory()
        self.seen_training: list[tuple[str, ...]] = []

    @property
    def identity(self) -> AdapterIdentity:
        return self._delegate.identity

    def create_session(self, invocation):
        return RecordingSession(
            self._delegate.create_session(invocation),
            self.seen_training,
        )


def test_adapter_receives_only_the_training_side_of_each_fold() -> None:
    control = control_fixture()
    fold_plan = make_leave_one_out_fold_plan(control.exposures.epoch_ids)
    factory = RecordingFactory()
    run_template_chain_ensemble(
        control.exposures,
        (plan("record-folds", (0.0, 0.0, 0.0, 0.0)),),
        fold_plan,
        OrderPropagationPlan(
            mode="arm_specific",
            available_order_ids=control.exposures.order_ids,
            arms=(ExtractionArm("only", ("o0",)),),
            common_template_order_ids=None,
        ),
        permissive_policy(),
        factory,
    )

    assert len(factory.seen_training) == len(fold_plan.folds)
    for seen, fold in zip(factory.seen_training, fold_plan.folds, strict=True):
        assert seen == fold.training_epoch_ids
        assert set(seen).isdisjoint(fold.evaluation_epoch_ids)


class ReusingFactory:
    def __init__(self) -> None:
        self._delegate = toy_factory()
        self._session = None

    @property
    def identity(self):
        return self._delegate.identity

    def create_session(self, invocation):
        if self._session is None:
            self._session = self._delegate.create_session(invocation)
        return self._session


class ConstantTokenFactory:
    def __init__(self) -> None:
        self._identity = toy_factory().identity

    @property
    def identity(self):
        return self._identity

    def create_session(self, invocation):
        return ToyTemplateSession(
            invocation,
            "workflow-reused-session-token",
            relaxation=0.5,
            adjacent_noise_scale=1.0,
        )


def test_session_reuse_and_any_caller_cache_fail_closed() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1", "e2"), ("e3",), fold_id="holdout")
    order_plan = OrderPropagationPlan(
        mode="arm_specific",
        available_order_ids=control.exposures.order_ids,
        arms=(ExtractionArm("only", ("o0",)),),
        common_template_order_ids=None,
    )
    with pytest.raises(TemplateChainDataError, match="cache reuse"):
        run_template_chain_ensemble(
            control.exposures,
            (plan("one", (0.0, 0.0, 0.0, 0.0)),),
            fold_plan,
            order_plan,
            permissive_policy(),
            toy_factory(),
            cached_artifacts=(object(),),
        )
    with pytest.raises(TemplateChainExecutionError, match="reused a session"):
        run_template_chain_ensemble(
            control.exposures,
            (
                plan("one", (0.0, 0.0, 0.0, 0.0)),
                plan("two", (1.0, 1.0, 1.0, 1.0)),
            ),
            fold_plan,
            order_plan,
            permissive_policy(),
            ReusingFactory(),
        )


def test_workflow_registry_rejects_reused_ensemble_nonce() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    injection = plan("nonce-bound", (1.0, 2.0, 3.0, 4.0))
    contract = mask_contract(injection, fold_plan, order_plan)
    registry = WorkflowFreshnessRegistry()
    nonce = ensemble_nonce("reused-nonce")
    factory = toy_factory()

    first = _run_template_chain_ensemble(
        control.exposures,
        (injection,),
        fold_plan,
        order_plan,
        permissive_policy(),
        factory,
        mask_contract=contract,
        ensemble_nonce=nonce,
        freshness_registry=registry,
    )
    assert first.ensemble_nonce == nonce
    assert all(
        fold.invocation.ensemble_nonce == nonce
        for trial in first.trials
        for fold in trial.fold_results
    )
    with pytest.raises(TemplateChainExecutionError, match="nonce was already used"):
        _run_template_chain_ensemble(
            control.exposures,
            (injection,),
            fold_plan,
            order_plan,
            permissive_policy(),
            factory,
            mask_contract=contract,
            ensemble_nonce=nonce,
            freshness_registry=registry,
        )


def test_workflow_registry_rejects_session_object_reuse_across_calls() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    injection = plan("object-freshness", (1.0, 2.0, 3.0, 4.0))
    contract = mask_contract(injection, fold_plan, order_plan)
    registry = WorkflowFreshnessRegistry()
    factory = ReusingFactory()

    _run_template_chain_ensemble(
        control.exposures,
        (injection,),
        fold_plan,
        order_plan,
        permissive_policy(),
        factory,
        mask_contract=contract,
        ensemble_nonce=ensemble_nonce("object-first"),
        freshness_registry=registry,
    )
    with pytest.raises(TemplateChainExecutionError, match="session object across the workflow"):
        _run_template_chain_ensemble(
            control.exposures,
            (injection,),
            fold_plan,
            order_plan,
            permissive_policy(),
            factory,
            mask_contract=contract,
            ensemble_nonce=ensemble_nonce("object-second"),
            freshness_registry=registry,
        )


def test_workflow_registry_rejects_session_token_reuse_across_calls() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    injection = plan("token-freshness", (1.0, 2.0, 3.0, 4.0))
    contract = mask_contract(injection, fold_plan, order_plan)
    registry = WorkflowFreshnessRegistry()
    factory = ConstantTokenFactory()

    _run_template_chain_ensemble(
        control.exposures,
        (injection,),
        fold_plan,
        order_plan,
        permissive_policy(),
        factory,
        mask_contract=contract,
        ensemble_nonce=ensemble_nonce("token-first"),
        freshness_registry=registry,
    )
    with pytest.raises(TemplateChainExecutionError, match="session token across the workflow"):
        _run_template_chain_ensemble(
            control.exposures,
            (injection,),
            fold_plan,
            order_plan,
            permissive_policy(),
            factory,
            mask_contract=contract,
            ensemble_nonce=ensemble_nonce("token-second"),
            freshness_registry=registry,
        )


class MaskChangingSession(RecordingSession):
    def update_template(self, training_data, previous_template, previous_rv, **kwargs):
        state = super().update_template(
            training_data,
            previous_template,
            previous_rv,
            **kwargs,
        )
        flux = state.flux.copy()
        mask = state.valid_mask.copy()
        flux[0, 0] = np.nan
        mask[0, 0] = False
        return TemplateState(
            invocation_sha256=state.invocation_sha256,
            state_index=state.state_index,
            order_ids=state.order_ids,
            flux=flux,
            valid_mask=mask,
        )


class MaskChangingFactory(RecordingFactory):
    def create_session(self, invocation):
        return MaskChangingSession(
            self._delegate.create_session(invocation),
            self.seen_training,
        )


def test_template_mask_change_fails_before_it_can_affect_convergence() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1", "e2"), ("e3",), fold_id="holdout")
    with pytest.raises(TemplateChainExecutionError, match="valid mask changed"):
        run_template_chain_ensemble(
            control.exposures,
            (plan("mask-change", (0.0, 0.0, 0.0, 0.0)),),
            fold_plan,
            common_orders(),
            permissive_policy(),
            MaskChangingFactory(),
        )


class StaleLineageSession(RecordingSession):
    def initial_template(self, training_data, invocation):
        state = super().initial_template(training_data, invocation)
        return TemplateState(
            invocation_sha256="0" * 64,
            state_index=state.state_index,
            order_ids=state.order_ids,
            flux=state.flux,
            valid_mask=state.valid_mask,
        )


class StaleLineageFactory(RecordingFactory):
    def create_session(self, invocation):
        return StaleLineageSession(
            self._delegate.create_session(invocation),
            self.seen_training,
        )


def test_stale_lineage_is_rejected_even_when_array_content_matches() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1", "e2"), ("e3",), fold_id="holdout")
    with pytest.raises(TemplateChainExecutionError, match="stale template lineage"):
        run_template_chain_ensemble(
            control.exposures,
            (plan("stale", (0.0, 0.0, 0.0, 0.0)),),
            fold_plan,
            common_orders(),
            permissive_policy(),
            StaleLineageFactory(),
        )


def test_state_arrays_are_defensively_copied_and_cannot_be_made_writeable() -> None:
    flux = np.ones((1, 5), dtype=float)
    mask = np.ones((1, 5), dtype=bool)
    state = TemplateState(
        invocation_sha256="a" * 64,
        state_index=0,
        order_ids=("order",),
        flux=flux,
        valid_mask=mask,
    )
    digest = state.state_sha256
    flux[0, 0] = 9.0
    mask[0, 0] = False

    assert state.flux[0, 0] == 1.0
    assert state.valid_mask[0, 0]
    assert state.state_sha256 == digest
    with pytest.raises(ValueError):
        state.flux.setflags(write=True)
    with pytest.raises(ValueError):
        state.valid_mask.setflags(write=True)


def test_nonconvergence_never_fits_the_evaluation_epochs() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1", "e2"), ("e3",), fold_id="holdout")
    result = run_template_chain_ensemble(
        control.exposures,
        (plan("nonconverged", (0.0, 0.0, 0.0, 0.0)),),
        fold_plan,
        OrderPropagationPlan(
            mode="arm_specific",
            available_order_ids=control.exposures.order_ids,
            arms=(ExtractionArm("only", ("o0",)),),
            common_template_order_ids=None,
        ),
        ConvergencePolicy(
            d_template_limit=0.0,
            d_rv_limit=0.0,
            q_conv=1,
            k_max=1,
            template_aggregate="maximum",
        ),
        toy_factory(),
    )

    fold = result.trials[0].fold_results[0]
    assert not fold.convergence.converged
    assert fold.convergence.failure_code == "maximum_iterations"
    assert fold.evaluation_rv is None


def test_rv_state_rejects_favourable_mask_attrition() -> None:
    with pytest.raises(TemplateChainDataError, match="NaN sentinels"):
        RVState(
            invocation_sha256="b" * 64,
            state_index=0,
            role="training",
            epoch_ids=("e0", "e1"),
            order_ids=("o0",),
            values=np.array([[1.0], [2.0]]),
            valid_mask=np.array([[True], [False]]),
        )


class CrossTrialMaskSession:
    """Internally stable session that can drift one semantic mask across trials."""

    def __init__(self, invocation, session_token: str, drift_role: str | None) -> None:
        self._invocation = invocation
        self._session_token = session_token
        self._drift_role = drift_role

    @property
    def session_token(self) -> str:
        return self._session_token

    def _matrix(self, shape: tuple[int, int], role: str) -> tuple[np.ndarray, np.ndarray]:
        values = np.zeros(shape, dtype=np.float64)
        mask = np.ones(shape, dtype=bool)
        if self._drift_role == role:
            values[0, 0] = np.nan
            mask[0, 0] = False
        return values, mask

    def _template(self, state_index: int) -> TemplateState:
        flux, mask = self._matrix(
            (len(self._invocation.template_order_ids), 5),
            "template",
        )
        return TemplateState(
            invocation_sha256=self._invocation.invocation_sha256,
            state_index=state_index,
            order_ids=self._invocation.template_order_ids,
            flux=flux,
            valid_mask=mask,
        )

    def _rv(self, state_index: int, role: str) -> RVState:
        is_training = role == "training"
        epoch_ids = (
            self._invocation.training_epoch_ids
            if is_training
            else self._invocation.evaluation_epoch_ids
        )
        order_ids = (
            self._invocation.template_order_ids if is_training else self._invocation.fit_order_ids
        )
        values, mask = self._matrix((len(epoch_ids), len(order_ids)), role)
        return RVState(
            invocation_sha256=self._invocation.invocation_sha256,
            state_index=state_index,
            role=role,
            epoch_ids=epoch_ids,
            order_ids=order_ids,
            values=values,
            valid_mask=mask,
        )

    def initial_template(self, training_data, invocation):
        return self._template(0)

    def fit_training(self, training_data, template, invocation):
        return self._rv(template.state_index, "training")

    def update_template(
        self,
        training_data,
        previous_template,
        previous_rv,
        *,
        state_index,
        invocation,
    ):
        return self._template(state_index)

    def adjacent_noise_scale(self, previous_template, current_template, invocation):
        return np.where(current_template.valid_mask, 1.0, np.nan)

    def fit_evaluation(self, evaluation_data, template, invocation):
        return self._rv(template.state_index, "evaluation")


class CrossTrialMaskFactory:
    def __init__(self, drift_role: str) -> None:
        self._identity = AdapterIdentity(
            adapter_name="adversarial-cross-trial-mask-adapter",
            adapter_version="1",
            configuration_sha256=canonical_sha256({"drift_role": drift_role}),
        )
        self._drift_role = drift_role
        self._creation_count = 0

    @property
    def identity(self) -> AdapterIdentity:
        return self._identity

    def create_session(self, invocation):
        creation_index = self._creation_count
        self._creation_count += 1
        return CrossTrialMaskSession(
            invocation,
            f"cross-trial-mask-session-{creation_index}",
            None if creation_index == 0 else self._drift_role,
        )


def one_arm_orders() -> OrderPropagationPlan:
    return OrderPropagationPlan(
        mode="arm_specific",
        available_order_ids=("o0", "o1", "o2"),
        arms=(ExtractionArm("only", ("o0", "o1")),),
        common_template_order_ids=None,
    )


@pytest.mark.parametrize(
    ("drift_role", "message"),
    [
        ("template", "template mask drifted"),
        ("training", "training RV mask drifted"),
        ("evaluation", "evaluation RV mask drifted"),
    ],
)
def test_cross_injection_semantic_mask_drift_fails_closed(
    drift_role: str,
    message: str,
) -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    reference = plan("reference", (0.0, 0.0, 0.0, 0.0))
    injected = plan("injected", (1.0, 2.0, 3.0, 4.0))

    with pytest.raises(TemplateChainDataError, match=message):
        _run_template_chain_ensemble(
            control.exposures,
            (reference, injected),
            fold_plan,
            order_plan,
            permissive_policy(),
            CrossTrialMaskFactory(drift_role),
            mask_contract=mask_contract(reference, fold_plan, order_plan),
        )


def test_display_labels_cannot_disguise_a_duplicate_physical_velocity_schedule() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    first = plan("display-a", (10.0, 20.0, 30.0, 40.0))
    duplicate = plan("display-b", (10.0, 20.0, 30.0, 40.0))

    assert first.velocity_pattern_sha256 == duplicate.velocity_pattern_sha256
    with pytest.raises(TemplateChainDataError, match="duplicate physical velocity schedules"):
        _run_template_chain_ensemble(
            control.exposures,
            (first, duplicate),
            fold_plan,
            order_plan,
            permissive_policy(),
            toy_factory(),
            mask_contract=mask_contract(first, fold_plan, order_plan),
        )


def test_replicate_labels_cannot_authorize_duplicate_single_source_schedule() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    velocities = (10.0, 20.0, 30.0, 40.0)
    first = plan(
        "replicate-a",
        velocities,
        replicate_identity_sha256=canonical_sha256({"noise_replicate": 1}),
    )
    second = plan(
        "replicate-b",
        velocities,
        replicate_identity_sha256=canonical_sha256({"noise_replicate": 2}),
    )

    assert first.velocity_pattern_sha256 == second.velocity_pattern_sha256
    with pytest.raises(TemplateChainDataError, match="caller-supplied replicate labels"):
        _run_template_chain_ensemble(
            control.exposures,
            (first, second),
            fold_plan,
            order_plan,
            permissive_policy(),
            toy_factory(),
            mask_contract=mask_contract(first, fold_plan, order_plan),
        )


def test_signed_zero_is_canonicalized_before_duplicate_schedule_detection() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    positive = plan("positive-zero", (0.0, 0.0, 0.0, 0.0))
    negative = plan("negative-zero", (-0.0, -0.0, -0.0, -0.0))

    assert all(item.velocity_m_s.hex() == "0x0.0p+0" for item in negative.velocities)
    assert positive.velocity_pattern_sha256 == negative.velocity_pattern_sha256
    with pytest.raises(TemplateChainDataError, match="duplicate physical velocity schedules"):
        _run_template_chain_ensemble(
            control.exposures,
            (positive, negative),
            fold_plan,
            order_plan,
            permissive_policy(),
            toy_factory(),
            mask_contract=mask_contract(positive, fold_plan, order_plan),
        )


def test_subresolution_velocity_alias_is_rejected_by_applied_content() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    zero = plan("zero", (0.0, 0.0, 0.0, 0.0))
    smallest_positive = float.fromhex("0x0.0000000000001p-1022")
    aliased = plan("subresolution", (smallest_positive,) * 4)

    assert zero.velocity_pattern_sha256 != aliased.velocity_pattern_sha256
    with pytest.raises(TemplateChainDataError, match="duplicate applied exposure content"):
        _run_template_chain_ensemble(
            control.exposures,
            (zero, aliased),
            fold_plan,
            order_plan,
            permissive_policy(),
            toy_factory(),
            mask_contract=mask_contract(zero, fold_plan, order_plan),
        )


def valid_constructor_fixture() -> TemplateChainEnsembleResult:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = one_arm_orders()
    reference = plan("constructor-reference", (0.0, 0.0, 0.0, 0.0))
    injected = plan("constructor-injected", (1.0, 2.0, 3.0, 4.0))
    return _run_template_chain_ensemble(
        control.exposures,
        (reference, injected),
        fold_plan,
        order_plan,
        permissive_policy(),
        toy_factory(),
        mask_contract=mask_contract(reference, fold_plan, order_plan),
    )


def test_fold_result_constructor_rejects_evaluation_epoch_substitution() -> None:
    result = valid_constructor_fixture()
    fold = result.trials[0].fold_results[0]
    evaluation = fold.evaluation_rv
    assert evaluation is not None
    substituted = RVState(
        invocation_sha256=evaluation.invocation_sha256,
        state_index=evaluation.state_index,
        role="evaluation",
        epoch_ids=fold.invocation.training_epoch_ids,
        order_ids=evaluation.order_ids,
        values=np.zeros((len(fold.invocation.training_epoch_ids), len(evaluation.order_ids))),
        valid_mask=np.ones(
            (len(fold.invocation.training_epoch_ids), len(evaluation.order_ids)),
            dtype=bool,
        ),
    )

    with pytest.raises(TemplateChainDataError, match="evaluation RV state/epoch/order"):
        FoldChainResult(
            invocation=fold.invocation,
            session_token=fold.session_token,
            template_states=fold.template_states,
            training_rv_states=fold.training_rv_states,
            adjacent_template_noise_scales=fold.adjacent_template_noise_scales,
            convergence=fold.convergence,
            evaluation_rv=substituted,
        )


def test_trial_constructor_rejects_cross_plan_fold_substitution_and_missing_roster() -> None:
    result = valid_constructor_fixture()
    first, second = result.trials
    with pytest.raises(TemplateChainDataError, match="another injection"):
        InjectionTrialResult(
            applied_injection=second.applied_injection,
            roster=result.roster,
            mask_contract=result.mask_contract,
            fold_results=first.fold_results,
        )
    with pytest.raises(TemplateChainDataError, match="fold_results must contain"):
        InjectionTrialResult(
            applied_injection=first.applied_injection,
            roster=result.roster,
            mask_contract=result.mask_contract,
            fold_results=(),
        )


def test_trial_constructor_requires_the_unique_complete_arm_fold_roster() -> None:
    control = control_fixture()
    fold_plan = make_disjoint_fold_plan(("e0", "e1"), ("e2", "e3"), fold_id="split")
    order_plan = common_orders()
    reference = plan("complete-roster", (0.0, 0.0, 0.0, 0.0))
    result = _run_template_chain_ensemble(
        control.exposures,
        (reference,),
        fold_plan,
        order_plan,
        permissive_policy(),
        toy_factory(),
        mask_contract=mask_contract(reference, fold_plan, order_plan),
    )
    trial = result.trials[0]
    assert len(trial.fold_results) == 2

    with pytest.raises(TemplateChainDataError, match="complete arm/fold roster"):
        InjectionTrialResult(
            applied_injection=trial.applied_injection,
            roster=result.roster,
            mask_contract=result.mask_contract,
            fold_results=trial.fold_results[:1],
        )
    with pytest.raises(TemplateChainDataError, match="semantic roster"):
        InjectionTrialResult(
            applied_injection=trial.applied_injection,
            roster=result.roster,
            mask_contract=result.mask_contract,
            fold_results=(trial.fold_results[0], trial.fold_results[0]),
        )


def test_ensemble_constructor_rejects_duplicate_trial_and_application() -> None:
    result = valid_constructor_fixture()
    trial = result.trials[0]
    with pytest.raises(TemplateChainDataError, match="duplicate injection trial"):
        TemplateChainEnsembleResult(
            ensemble_nonce=result.ensemble_nonce,
            source_exposure_sha256=result.source_exposure_sha256,
            roster=result.roster,
            mask_contract=result.mask_contract,
            trials=(trial, trial),
        )


def test_ensemble_recursive_integrity_replays_global_invariants() -> None:
    result = valid_constructor_fixture()

    result.verify_integrity()
    assert result.recompute_sha256() == result.result_sha256
    object.__setattr__(result, "trials", (result.trials[0], result.trials[0]))
    with pytest.raises(TemplateChainDataError, match="duplicate injection trial"):
        result.verify_integrity()
