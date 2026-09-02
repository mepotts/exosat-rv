from __future__ import annotations

import json
from dataclasses import replace

import numpy as np
import pytest

from exosat_rv.m38.calibration import (
    CalibrationCandidate,
    CalibrationCase,
    CalibrationError,
    CalibrationExecutionAttestation,
    CalibrationOutcome,
    CalibrationRecord,
    CalibrationTrial,
    calibration_result_sha256,
    evaluate_convergence_grid,
    evaluate_search_design_grid,
    evaluate_selection_grid,
)

EVALUATOR_SHA256 = "e" * 64
ALTERNATE_EVALUATOR_SHA256 = "f" * 64
VERIFIER_SHA256 = "a" * 64
EXECUTOR_SHA256 = "b" * 64
EXECUTOR_KEY_SHA256 = "c" * 64


def _outcome(
    trial: CalibrationTrial,
    metrics: dict[str, float],
    *,
    trial_id: str | None = None,
) -> CalibrationOutcome:
    outcome_trial_id = trial.trial_id if trial_id is None else trial_id
    attestation = CalibrationExecutionAttestation.from_execution(
        plan_sha256=trial.plan_id,
        evaluator_sha256=trial.evaluator_sha256,
        attestation_verifier_sha256=trial.attestation_verifier_sha256,
        trial_sha256=trial.trial_id,
        result_sha256=calibration_result_sha256(outcome_trial_id, metrics),
        executor_identity_sha256=EXECUTOR_SHA256,
        executor_key_sha256=EXECUTOR_KEY_SHA256,
        signature_scheme="test-external-signature-v1",
        signature="detached-test-signature",
        signed_at="2030-01-01T00:00:00Z",
    )
    return CalibrationOutcome.from_metrics(
        outcome_trial_id,
        metrics,
        execution_attestation=attestation,
    )


def _accept_attestation(attestation: CalibrationExecutionAttestation) -> bool:
    return type(attestation) is CalibrationExecutionAttestation


def _verification_kwargs() -> dict[str, object]:
    return {
        "attestation_verifier": _accept_attestation,
        "attestation_verifier_identity": VERIFIER_SHA256,
    }


def _candidates() -> tuple[CalibrationCandidate, ...]:
    return (
        CalibrationCandidate.from_definition(
            "policy-a",
            {"d_rv_limit": 0.1, "d_template_limit": 0.2},
        ),
        CalibrationCandidate.from_definition(
            "policy-b",
            {"d_rv_limit": 0.2, "d_template_limit": 0.4},
        ),
    )


def _cases() -> tuple[CalibrationCase, ...]:
    return (
        CalibrationCase.from_truth("stable", {"shift": 0.0, "snr": 20.0}),
        CalibrationCase.from_truth("moving", {"shift": 1.5, "snr": 8.0}),
    )


def test_convergence_grid_invokes_every_cell_and_returns_no_winner() -> None:
    seen: list[tuple[str, str, int]] = []

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        seen.append((trial.candidate.candidate_id, trial.case.case_id, trial.trial_seed))
        moving = trial.case.case_id == "moving"
        return _outcome(
            trial,
            {
                "false_convergence_rate": 0.05 if moving else 0.0,
                "nonconvergence_rate": 0.1,
                "signal_attenuation_fraction": 0.2 if moving else 0.0,
                "signal_bias": -0.1 if moving else 0.0,
            },
        )

    report = evaluate_convergence_grid(
        _candidates(),
        _cases(),
        evaluator,
        seed=501,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )

    assert report.complete
    assert len(seen) == 4
    assert len({seed for _, _, seed in seen}) == 4
    assert len(report.records) == 4
    assert len(report.metric_table("signal_bias")) == 4
    assert not hasattr(report, "winner")
    assert not hasattr(report, "ranked_candidates")


def test_candidate_and_case_payloads_are_detached_and_content_bound() -> None:
    definition = {"nested": {"limit": 0.1}}
    truth = {"velocity": [0.0, 1.0]}
    candidate = CalibrationCandidate.from_definition("candidate", definition)
    case = CalibrationCase.from_truth("case", truth)
    candidate_identity = candidate.identity
    case_identity = case.identity

    definition["nested"]["limit"] = 99.0
    truth["velocity"].append(2.0)
    candidate_view = candidate.definition
    case_view = case.truth
    assert isinstance(candidate_view, dict)
    assert isinstance(case_view, dict)
    candidate_view["nested"]["limit"] = -1.0
    case_view["velocity"].append(3.0)

    assert candidate.identity == candidate_identity
    assert case.identity == case_identity
    assert candidate.definition == {"nested": {"limit": 0.1}}
    assert case.truth == {"velocity": [0.0, 1.0]}
    assert (
        candidate.identity
        != CalibrationCandidate.from_definition("candidate", {"nested": {"limit": 0.2}}).identity
    )


def test_strict_payloads_reject_non_native_and_noncanonical_values() -> None:
    with pytest.raises(CalibrationError, match="strict native JSON"):
        CalibrationCandidate.from_definition("bad", {"value": (1, 2)})
    with pytest.raises(CalibrationError, match="strict native JSON"):
        CalibrationCase.from_truth("bad", {"value": float("nan")})
    with pytest.raises(CalibrationError, match="not in canonical form"):
        CalibrationCandidate("bad", b'{"z":1,"a":2}')
    with pytest.raises((CalibrationError, json.JSONDecodeError)):
        CalibrationCase("bad", b'{"value":')


def test_failures_and_missing_metrics_remain_in_the_complete_table() -> None:
    candidates = _candidates()
    cases = _cases()

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        if trial.candidate.candidate_id == "policy-a" and trial.case.case_id == "moving":
            raise RuntimeError("declared synthetic failure")
        if trial.candidate.candidate_id == "policy-b" and trial.case.case_id == "stable":
            return _outcome(
                trial,
                {
                    "false_convergence_rate": 0.0,
                    "nonconvergence_rate": 0.0,
                    "signal_attenuation_fraction": 0.0,
                },
            )
        return _outcome(
            trial,
            {
                "false_convergence_rate": 0.0,
                "nonconvergence_rate": 0.0,
                "signal_attenuation_fraction": 0.0,
                "signal_bias": 0.0,
            },
        )

    report = evaluate_convergence_grid(
        candidates,
        cases,
        evaluator,
        seed=502,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )
    rows = report.metric_table("signal_bias")

    assert not report.complete
    assert len(report.records) == 4
    assert len(report.failures) == 2
    assert sum(value is None for _, _, value in rows) == 2
    assert {failure.exception_type for failure in report.failures} == {
        "calibration_evaluator_exception",
        "calibration_outcome_invalid",
    }
    assert all(failure.message.startswith("diagnostic_sha256:") for failure in report.failures)


def test_stale_trial_ids_and_out_of_range_rates_fail_closed() -> None:
    outcomes = iter(("stale", "range"))

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        mode = next(outcomes)
        return _outcome(
            trial,
            {
                "association_error_rate": 0.0,
                "detection_completeness": 1.2 if mode == "range" else 0.5,
                "familywise_false_alarm_rate": 0.1,
            },
            trial_id="wrong-id" if mode == "stale" else trial.trial_id,
        )

    report = evaluate_search_design_grid(
        (CalibrationCandidate.from_definition("search", {"model": "caller-supplied"}),),
        (
            CalibrationCase.from_truth("case-a", {"truth": "a"}),
            CalibrationCase.from_truth("case-b", {"truth": "b"}),
        ),
        evaluator,
        seed=503,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )

    assert not report.complete
    assert [failure.exception_type for failure in report.failures] == [
        "calibration_outcome_invalid",
        "calibration_outcome_invalid",
    ]


def test_domain_wrappers_bind_distinct_metric_schemas_and_plan_ids() -> None:
    candidate = (CalibrationCandidate.from_definition("candidate", {"value": 1}),)
    case = (CalibrationCase.from_truth("case", {"truth": 1}),)

    def selection_evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        return _outcome(
            trial,
            {
                "attrition_rate": 0.1,
                "false_eligibility_rate": 0.0,
                "false_pass_rate": 0.0,
                "interval_coverage": 0.95,
            },
        )

    def search_evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        return _outcome(
            trial,
            {
                "association_error_rate": 0.05,
                "detection_completeness": 0.8,
                "familywise_false_alarm_rate": 0.02,
            },
        )

    selection = evaluate_selection_grid(
        candidate,
        case,
        selection_evaluator,
        seed=504,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )
    search = evaluate_search_design_grid(
        candidate,
        case,
        search_evaluator,
        seed=504,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )

    assert selection.complete
    assert search.complete
    assert selection.plan_id != search.plan_id
    assert selection.required_metrics != search.required_metrics


def test_duplicate_candidate_or_case_ids_are_rejected_before_evaluation() -> None:
    candidate = CalibrationCandidate.from_definition("duplicate", {"value": 1})
    case = CalibrationCase.from_truth("duplicate", {"truth": 1})

    with pytest.raises(ValueError, match="candidate IDs must be unique"):
        evaluate_convergence_grid(
            (candidate, candidate),
            (case,),
            lambda trial: CalibrationOutcome.from_metrics(trial.trial_id, {}),
            seed=505,
            experiment_identity=ALTERNATE_EVALUATOR_SHA256,
            **_verification_kwargs(),
        )
    with pytest.raises(ValueError, match="case IDs must be unique"):
        evaluate_convergence_grid(
            (candidate,),
            (case, case),
            lambda trial: CalibrationOutcome.from_metrics(trial.trial_id, {}),
            seed=505,
            experiment_identity=ALTERNATE_EVALUATOR_SHA256,
            **_verification_kwargs(),
        )


def test_report_cannot_be_forged_complete_and_evaluator_identity_is_content_bound() -> None:
    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        return _outcome(
            trial,
            {
                "false_convergence_rate": 0.0,
                "nonconvergence_rate": 0.0,
                "signal_attenuation_fraction": 0.0,
                "signal_bias": 0.0,
            },
        )

    first = evaluate_convergence_grid(
        _candidates(),
        _cases(),
        evaluator,
        seed=506,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )
    second = evaluate_convergence_grid(
        _candidates(),
        _cases(),
        evaluator,
        seed=506,
        experiment_identity=ALTERNATE_EVALUATOR_SHA256,
        **_verification_kwargs(),
    )

    assert first.plan_id != second.plan_id
    with pytest.raises(ValueError, match="planned cell"):
        replace(
            first,
            records=(first.records[0],) * len(first.records),
            attestation_verifier=_accept_attestation,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        evaluate_convergence_grid(
            _candidates(),
            _cases(),
            evaluator,
            seed=506,
            experiment_identity="human-readable-label-only",
            **_verification_kwargs(),
        )


@pytest.mark.parametrize("value", [True, "0.5"])
def test_metric_values_reject_boolean_and_string_coercion(value: object) -> None:
    with pytest.raises(TypeError, match="real scalar"):
        CalibrationOutcome.from_metrics("trial", {"false_pass_rate": value})


def test_hostile_native_and_numpy_numeric_subclasses_are_rejected_before_conversion() -> None:
    class HostileNativeFloat(float):
        def __float__(self) -> float:
            raise AssertionError("hostile native float conversion must not run")

    class HostileNumpyFloat(np.float64):
        def __float__(self) -> float:
            raise AssertionError("hostile NumPy float conversion must not run")

    class HostileNumpyInt(np.int64):
        def __int__(self) -> int:
            raise AssertionError("hostile NumPy integer conversion must not run")

    for value in (HostileNativeFloat(0.5), HostileNumpyFloat(0.5)):
        with pytest.raises(TypeError, match="native or NumPy real scalar"):
            CalibrationOutcome.from_metrics("trial", {"false_pass_rate": value})
    with pytest.raises(ValueError, match="non-negative integer"):
        evaluate_convergence_grid(
            (CalibrationCandidate.from_definition("candidate", {"value": 1}),),
            (CalibrationCase.from_truth("case", {"truth": 1}),),
            lambda trial: _outcome(trial, {}),
            seed=HostileNumpyInt(1),
            experiment_identity=EVALUATOR_SHA256,
            **_verification_kwargs(),
        )


def test_missing_or_mismatched_execution_attestation_cannot_become_success() -> None:
    candidate = (CalibrationCandidate.from_definition("candidate", {"value": 1}),)
    case = (CalibrationCase.from_truth("case", {"truth": 1}),)
    metrics = {
        "false_convergence_rate": 0.0,
        "nonconvergence_rate": 0.0,
        "signal_attenuation_fraction": 0.0,
        "signal_bias": 0.0,
    }

    missing = evaluate_convergence_grid(
        candidate,
        case,
        lambda trial: CalibrationOutcome.from_metrics(trial.trial_id, metrics),
        seed=507,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )

    def mismatched(trial: CalibrationTrial) -> CalibrationOutcome:
        attestation = CalibrationExecutionAttestation.from_execution(
            plan_sha256=trial.plan_id,
            evaluator_sha256=trial.evaluator_sha256,
            attestation_verifier_sha256=trial.attestation_verifier_sha256,
            trial_sha256=trial.trial_id,
            result_sha256="d" * 64,
            executor_identity_sha256=EXECUTOR_SHA256,
            executor_key_sha256=EXECUTOR_KEY_SHA256,
            signature_scheme="test-external-signature-v1",
            signature="detached-test-signature",
            signed_at="2030-01-01T00:00:00Z",
        )
        return CalibrationOutcome.from_metrics(
            trial.trial_id,
            metrics,
            execution_attestation=attestation,
        )

    wrong_result = evaluate_convergence_grid(
        candidate,
        case,
        mismatched,
        seed=507,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )

    assert not missing.complete and not wrong_result.complete
    assert missing.failures[0].exception_type == "calibration_outcome_invalid"
    assert wrong_result.failures[0].exception_type == "calibration_outcome_invalid"
    with pytest.raises(CalibrationError, match="requires an execution attestation"):
        replace(
            missing.records[0],
            outcome=CalibrationOutcome.from_metrics(
                missing.records[0].trial.trial_id,
                metrics,
            ),
            failure=None,
            attestation_verifier=_accept_attestation,
            attestation_verifier_identity=VERIFIER_SHA256,
        )


def test_external_attestation_verifier_must_return_exact_true() -> None:
    candidate = (CalibrationCandidate.from_definition("candidate", {"value": 1}),)
    case = (CalibrationCase.from_truth("case", {"truth": 1}),)

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        return _outcome(
            trial,
            {
                "false_convergence_rate": 0.0,
                "nonconvergence_rate": 0.0,
                "signal_attenuation_fraction": 0.0,
                "signal_bias": 0.0,
            },
        )

    rejected = evaluate_convergence_grid(
        candidate,
        case,
        evaluator,
        seed=508,
        experiment_identity=EVALUATOR_SHA256,
        attestation_verifier=lambda attestation: 1,
        attestation_verifier_identity=VERIFIER_SHA256,
    )

    assert not rejected.complete
    assert rejected.failures[0].exception_type == "calibration_attestation_rejected"


def test_malicious_exception_rendering_cannot_abort_or_leak_calibration_accounting() -> None:
    secret = "do-not-render-this-calibration-secret"

    class UnrenderableError(RuntimeError):
        def __str__(self) -> str:
            raise AssertionError("exception rendering must never be invoked")

    candidate = (CalibrationCandidate.from_definition("candidate", {"value": 1}),)
    case = (CalibrationCase.from_truth("case", {"truth": 1}),)

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        return _outcome(
            trial,
            {
                "false_convergence_rate": 0.0,
                "nonconvergence_rate": 0.0,
                "signal_attenuation_fraction": 0.0,
                "signal_bias": 0.0,
            },
        )

    def verifier(attestation: CalibrationExecutionAttestation) -> bool:
        raise UnrenderableError(secret)

    report = evaluate_convergence_grid(
        candidate,
        case,
        evaluator,
        seed=509,
        experiment_identity=EVALUATOR_SHA256,
        attestation_verifier=verifier,
        attestation_verifier_identity=VERIFIER_SHA256,
    )

    assert not report.complete
    assert report.failures[0].exception_type == ("calibration_attestation_verifier_exception")
    assert report.failures[0].message.startswith("diagnostic_sha256:")
    assert secret not in report.failures[0].message

    def broken_evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        raise UnrenderableError(secret)

    evaluator_report = evaluate_convergence_grid(
        candidate,
        case,
        broken_evaluator,
        seed=509,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )
    assert evaluator_report.failures[0].exception_type == "calibration_evaluator_exception"
    assert evaluator_report.failures[0].message.startswith("diagnostic_sha256:")
    assert secret not in evaluator_report.failures[0].message


def test_attestation_verifier_identity_is_plan_bound() -> None:
    candidate = (CalibrationCandidate.from_definition("candidate", {"value": 1}),)
    case = (CalibrationCase.from_truth("case", {"truth": 1}),)

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        return _outcome(
            trial,
            {
                "false_convergence_rate": 0.0,
                "nonconvergence_rate": 0.0,
                "signal_attenuation_fraction": 0.0,
                "signal_bias": 0.0,
            },
        )

    first = evaluate_convergence_grid(
        candidate,
        case,
        evaluator,
        seed=510,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )
    second = evaluate_convergence_grid(
        candidate,
        case,
        evaluator,
        seed=510,
        experiment_identity=EVALUATOR_SHA256,
        attestation_verifier=_accept_attestation,
        attestation_verifier_identity="9" * 64,
    )

    assert first.complete and second.complete
    assert first.plan_id != second.plan_id


def test_rejected_outcome_cannot_be_rewrapped_without_the_exact_verifier() -> None:
    candidate = (CalibrationCandidate.from_definition("candidate", {"value": 1}),)
    case = (CalibrationCase.from_truth("case", {"truth": 1}),)
    retained: list[CalibrationOutcome] = []

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        outcome = _outcome(
            trial,
            {
                "false_convergence_rate": 0.0,
                "nonconvergence_rate": 0.0,
                "signal_attenuation_fraction": 0.0,
                "signal_bias": 0.0,
            },
        )
        retained.append(outcome)
        return outcome

    rejected = evaluate_convergence_grid(
        candidate,
        case,
        evaluator,
        seed=511,
        experiment_identity=EVALUATOR_SHA256,
        attestation_verifier=lambda attestation: False,
        attestation_verifier_identity=VERIFIER_SHA256,
    )
    trial = rejected.records[0].trial

    assert not rejected.structurally_complete
    assert not rejected.verified_complete
    with pytest.raises(TypeError):
        CalibrationRecord(trial=trial, outcome=retained[0], failure=None)
    with pytest.raises(CalibrationError, match="rejected"):
        CalibrationRecord(
            trial=trial,
            outcome=retained[0],
            failure=None,
            attestation_verifier=lambda attestation: False,
            attestation_verifier_identity=VERIFIER_SHA256,
        )
    with pytest.raises(CalibrationError, match="identity"):
        CalibrationRecord(
            trial=trial,
            outcome=retained[0],
            failure=None,
            attestation_verifier=_accept_attestation,
            attestation_verifier_identity="8" * 64,
        )


def test_report_revalidation_reruns_verifier_and_rejects_post_construction_mutation() -> None:
    candidate = (CalibrationCandidate.from_definition("candidate", {"value": 1}),)
    case = (CalibrationCase.from_truth("case", {"truth": 1}),)

    def evaluator(trial: CalibrationTrial) -> CalibrationOutcome:
        return _outcome(
            trial,
            {
                "false_convergence_rate": 0.0,
                "nonconvergence_rate": 0.0,
                "signal_attenuation_fraction": 0.0,
                "signal_bias": 0.0,
            },
        )

    report = evaluate_convergence_grid(
        candidate,
        case,
        evaluator,
        seed=512,
        experiment_identity=EVALUATOR_SHA256,
        **_verification_kwargs(),
    )
    assert report.structurally_complete and report.verified_complete and report.complete
    with pytest.raises(CalibrationError, match="rejected"):
        report.verify_integrity(
            lambda attestation: False,
            attestation_verifier_identity=VERIFIER_SHA256,
        )
    with pytest.raises(CalibrationError, match="identity"):
        report.verify_integrity(
            _accept_attestation,
            attestation_verifier_identity="7" * 64,
        )

    outcome = report.records[0].outcome
    assert outcome is not None
    object.__setattr__(
        outcome,
        "metrics",
        tuple(
            (name, 0.5 if name == "false_convergence_rate" else value)
            for name, value in outcome.metrics
        ),
    )
    with pytest.raises(CalibrationError, match="does not bind result_sha256"):
        report.verify_integrity(
            _accept_attestation,
            attestation_verifier_identity=VERIFIER_SHA256,
        )
