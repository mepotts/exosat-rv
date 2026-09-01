"""Synthetic-only tests for the generic M38 adjacent-iteration convergence metrics."""

import numpy as np
import pytest

from exosat_rv.m38.convergence import (
    ConvergenceDataError,
    ConvergencePolicy,
    evaluate_convergence,
    rv_change_metric,
    template_change_metric,
)


def synthetic_states(
    adjacent_changes: list[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    template = np.zeros((2, 7), dtype=float)
    rv_pattern = np.array(
        [
            [-1.0, 1.0],
            [-2.0, 2.0],
            [-3.0, 3.0],
        ]
    )
    rv = rv_pattern.copy()
    templates = [template.copy()]
    rvs = [rv.copy()]
    for change in adjacent_changes:
        template = template + change
        rv = rv + change * rv_pattern
        templates.append(template.copy())
        rvs.append(rv.copy())
    noises = np.ones((len(adjacent_changes), 2, 7), dtype=float)
    return np.stack(templates), noises, np.stack(rvs)


def test_template_metric_is_robust_noise_normalized_and_declares_aggregate() -> None:
    previous = np.zeros((2, 5))
    current = np.array(
        [
            [1.0, 1.0, 1.0, 1.0, 1000.0],
            [4.0, 4.0, 4.0, 4.0, 2000.0],
        ]
    )
    noise = np.array(
        [
            [2.0, 2.0, 2.0, 2.0, 2.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
        ]
    )

    median_metric = template_change_metric(
        previous,
        current,
        noise,
        aggregate="median",
    )
    maximum_metric = template_change_metric(
        previous,
        current,
        noise,
        aggregate="maximum",
    )

    assert median_metric.per_order == pytest.approx([0.5, 2.0])
    assert median_metric.aggregate == pytest.approx(1.25)
    assert median_metric.aggregate_method == "median"
    assert median_metric.valid_pixel_counts.tolist() == [5, 5]
    assert maximum_metric.aggregate == pytest.approx(2.0)
    assert not median_metric.per_order.flags.writeable


def test_rv_metric_is_invariant_to_independent_iteration_zero_points() -> None:
    previous = np.array(
        [
            [np.nan, -2.0, 1.0],
            [3.0, 5.0, 8.0],
        ]
    )
    current = np.array(
        [
            [np.nan, -1.5, 0.0],
            [4.0, 4.5, 8.5],
        ]
    )

    baseline = rv_change_metric(previous, current)
    independently_offset = rv_change_metric(previous + 71.0, current - 113.0)

    assert independently_offset.value == pytest.approx(baseline.value, abs=1e-12)
    assert baseline.valid_cell_count == 5
    assert independently_offset.previous_zero_point == pytest.approx(
        baseline.previous_zero_point + 71.0
    )
    assert independently_offset.current_zero_point == pytest.approx(
        baseline.current_zero_point - 113.0
    )


def test_first_converged_iteration_requires_q_consecutive_joint_passes() -> None:
    templates, noises, rvs = synthetic_states([0.40, 0.05, 0.03])
    policy = ConvergencePolicy(
        d_template_limit=0.10,
        d_rv_limit=0.11,
        q_conv=2,
        k_max=3,
        template_aggregate="median",
    )

    result = evaluate_convergence(templates, noises, rvs, policy)

    assert result.converged
    assert result.converged_iteration == 3
    assert result.failure_code is None
    assert [update.jointly_passed for update in result.history] == [False, True, True]
    assert [update.consecutive_joint_passes for update in result.history] == [0, 1, 2]
    assert [update.iteration for update in result.history] == [1, 2, 3]


def test_failure_at_k_max_keeps_complete_metric_history() -> None:
    templates, noises, rvs = synthetic_states([0.40, 0.30, 0.20])
    policy = ConvergencePolicy(
        d_template_limit=0.10,
        d_rv_limit=0.10,
        q_conv=2,
        k_max=3,
        template_aggregate="maximum",
    )

    result = evaluate_convergence(templates, noises, rvs, policy)

    assert not result.converged
    assert result.converged_iteration is None
    assert result.failure_code == "maximum_iterations"
    assert "k_max=3" in result.failure_reason
    assert len(result.history) == 3
    assert all(update.template_metric is not None for update in result.history)
    assert all(update.rv_metric is not None for update in result.history)


def test_too_few_updates_is_not_mislabeled_as_k_max_nonconvergence() -> None:
    templates, noises, rvs = synthetic_states([0.04])
    policy = ConvergencePolicy(
        d_template_limit=0.10,
        d_rv_limit=0.10,
        q_conv=2,
        k_max=3,
        template_aggregate="median",
    )

    result = evaluate_convergence(templates, noises, rvs, policy)

    assert not result.converged
    assert result.failure_code == "insufficient_updates"
    assert len(result.history) == 1
    assert result.history[0].jointly_passed


def test_rv_finite_mask_change_fails_closed_at_the_changed_update() -> None:
    templates, noises, rvs = synthetic_states([0.40, 0.05, 0.03])
    rvs[2, 0, 0] = np.nan
    policy = ConvergencePolicy(
        d_template_limit=1.0,
        d_rv_limit=1.0,
        q_conv=3,
        k_max=3,
        template_aggregate="median",
    )

    result = evaluate_convergence(templates, noises, rvs, policy)

    assert not result.converged
    assert result.failure_code == "invalid_data"
    assert "finite mask changed" in result.failure_reason
    assert len(result.history) == 2
    assert result.history[-1].iteration == 2
    assert result.history[-1].template_metric is not None
    assert result.history[-1].rv_metric is None


def test_template_finite_mask_change_fails_closed() -> None:
    templates, noises, rvs = synthetic_states([0.40, 0.05])
    templates[1, 0, 2] = np.nan
    policy = ConvergencePolicy(
        d_template_limit=1.0,
        d_rv_limit=1.0,
        q_conv=2,
        k_max=2,
        template_aggregate="median",
    )

    result = evaluate_convergence(templates, noises, rvs, policy)

    assert result.failure_code == "invalid_data"
    assert "finite mask changed" in result.failure_reason
    assert len(result.history) == 1
    assert result.history[0].template_metric is None


def test_preexisting_common_nan_mask_is_allowed_but_cannot_be_selected() -> None:
    previous = np.zeros((2, 3))
    current = np.full((2, 3), 0.05)
    noise = np.ones((2, 3))
    previous[0, 1] = np.nan
    current[0, 1] = np.nan

    metric = template_change_metric(
        previous,
        current,
        noise,
        aggregate="median",
    )
    assert metric.valid_pixel_counts.tolist() == [2, 3]
    assert metric.aggregate == pytest.approx(0.05)

    with pytest.raises(ConvergenceDataError, match="selects a non-finite cell"):
        template_change_metric(
            previous,
            current,
            noise,
            aggregate="median",
            valid_mask=np.ones((2, 3), dtype=bool),
        )


@pytest.mark.parametrize("bad_noise", [0.0, -1.0, np.nan, np.inf])
def test_invalid_noise_scale_is_rejected(bad_noise: float) -> None:
    noise = np.ones((2, 3))
    noise[0, 0] = bad_noise
    with pytest.raises(ConvergenceDataError, match="noise_scale"):
        template_change_metric(
            np.zeros((2, 3)),
            np.ones((2, 3)),
            noise,
            aggregate="median",
        )


def test_shape_changes_and_ragged_state_series_fail_closed() -> None:
    with pytest.raises(ConvergenceDataError, match="shape changed"):
        rv_change_metric(np.zeros((2, 2)), np.zeros((2, 3)))

    policy = ConvergencePolicy(
        d_template_limit=1.0,
        d_rv_limit=1.0,
        q_conv=1,
        k_max=2,
        template_aggregate="median",
    )
    ragged_templates = [np.zeros((2, 3)), np.zeros((2, 4))]
    result = evaluate_convergence(
        ragged_templates,
        np.ones((1, 2, 3)),
        np.zeros((2, 2, 2)),
        policy,
    )

    assert result.failure_code == "invalid_data"
    assert "rectangular" in result.failure_reason
    assert result.history == ()


def test_template_and_rv_order_count_mismatch_fails_before_metrics() -> None:
    templates, noises, rvs = synthetic_states([0.05, 0.04])
    mismatched_rvs = np.concatenate((rvs, rvs[:, :, :1]), axis=2)
    policy = ConvergencePolicy(
        d_template_limit=0.10,
        d_rv_limit=0.10,
        q_conv=2,
        k_max=2,
        template_aggregate="median",
    )

    result = evaluate_convergence(templates, noises, mismatched_rvs, policy)

    assert result.failure_code == "invalid_data"
    assert result.failure_reason == "template and RV order counts differ"
    assert result.history == ()


def test_numeric_conversion_and_metric_overflow_fail_closed() -> None:
    huge_integer = 10**10_000
    maximum = np.finfo(np.float64).max

    with pytest.raises(ValueError, match="finite non-negative"):
        ConvergencePolicy(
            d_template_limit=huge_integer,
            d_rv_limit=1.0,
            q_conv=1,
            k_max=1,
            template_aggregate="median",
        )
    with pytest.raises(ConvergenceDataError, match="rectangular numeric"):
        template_change_metric(
            [[0.0, huge_integer]],
            [[0.0, 1.0]],
            [[1.0, 1.0]],
            aggregate="median",
        )
    with pytest.raises(ConvergenceDataError, match="D_T calculation overflowed"):
        template_change_metric(
            np.array([[-maximum, -maximum]]),
            np.array([[maximum, maximum]]),
            np.ones((1, 2)),
            aggregate="median",
        )
    with pytest.raises(ConvergenceDataError, match="D_RV calculation overflowed"):
        rv_change_metric(
            np.array([[-maximum, maximum], [-maximum, maximum]]),
            np.array([[maximum, -maximum], [maximum, -maximum]]),
        )

    templates, noises, rvs = synthetic_states([0.05])
    overflowing_templates = templates.astype(object)
    overflowing_templates[0, 0, 0] = huge_integer
    policy = ConvergencePolicy(
        d_template_limit=0.10,
        d_rv_limit=0.10,
        q_conv=1,
        k_max=1,
        template_aggregate="median",
    )
    result = evaluate_convergence(overflowing_templates, noises, rvs, policy)
    assert result.failure_code == "invalid_data"
    assert "rectangular numeric" in result.failure_reason


@pytest.mark.parametrize(
    "policy_kwargs",
    [
        {
            "d_template_limit": np.nan,
            "d_rv_limit": 1.0,
            "q_conv": 1,
            "k_max": 1,
            "template_aggregate": "median",
        },
        {
            "d_template_limit": 1.0,
            "d_rv_limit": -0.1,
            "q_conv": 1,
            "k_max": 1,
            "template_aggregate": "median",
        },
        {
            "d_template_limit": 1.0,
            "d_rv_limit": 1.0,
            "q_conv": 2,
            "k_max": 1,
            "template_aggregate": "median",
        },
        {
            "d_template_limit": 1.0,
            "d_rv_limit": 1.0,
            "q_conv": 1,
            "k_max": 1,
            "template_aggregate": "undeclared",
        },
    ],
)
def test_policy_rejects_unresolved_or_invalid_values(policy_kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ConvergencePolicy(**policy_kwargs)
