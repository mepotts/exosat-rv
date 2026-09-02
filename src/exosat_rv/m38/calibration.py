"""Report-only calibration grids for synthetic and declared M38 controls.

The orchestration in this module exhaustively evaluates caller-supplied candidates against
caller-supplied cases.  It retains every planned failure, binds every cell to canonical
content identities and deterministic seeds, and returns complete comparison tables.  It does
not rank candidates, optimize thresholds, refine grids, or adopt a scientific setting.

Execution attestations provide exact structural bindings and are accepted only through a
caller-supplied external verifier.  This module does not implement a signature algorithm,
authenticate executor keys, or prove that the verifier or executor is independent; those are
cryptographic and governance responsibilities outside this in-process harness.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import InitVar, dataclass
from dataclasses import field as dataclass_field
from typing import Literal, Protocol, TypeAlias

import numpy as np

from .control_suite import SignatureMetadata
from .provenance import canonical_json_bytes, canonical_sha256

CalibrationDomain: TypeAlias = Literal["convergence", "selection", "search"]

_CALIBRATION_SEED_DOMAIN = 0x4D333843
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DIAGNOSTIC = re.compile(r"diagnostic_sha256:[0-9a-f]{64}\Z")
_DIAGNOSTIC_FALLBACK = hashlib.sha256(b"m38-safe-diagnostic-unavailable-v1").hexdigest()
_FAILURE_CODES = frozenset(
    {
        "calibration_attestation_rejected",
        "calibration_attestation_verifier_exception",
        "calibration_evaluator_exception",
        "calibration_outcome_invalid",
    }
)
_NUMPY_INTEGER_TYPES = frozenset(
    np.dtype(name).type
    for name in (
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
    )
)
_NUMPY_FLOAT_TYPES = frozenset(
    np.dtype(name).type for name in ("float16", "float32", "float64", "longdouble")
)
_NUMPY_REAL_TYPES = _NUMPY_INTEGER_TYPES | _NUMPY_FLOAT_TYPES

_REQUIRED_METRICS: dict[CalibrationDomain, tuple[str, ...]] = {
    "convergence": (
        "false_convergence_rate",
        "nonconvergence_rate",
        "signal_attenuation_fraction",
        "signal_bias",
    ),
    "selection": (
        "attrition_rate",
        "false_eligibility_rate",
        "false_pass_rate",
        "interval_coverage",
    ),
    "search": (
        "association_error_rate",
        "detection_completeness",
        "familywise_false_alarm_rate",
    ),
}

_UNIT_INTERVAL_METRICS = frozenset(
    {
        "association_error_rate",
        "attrition_rate",
        "detection_completeness",
        "false_convergence_rate",
        "false_eligibility_rate",
        "false_pass_rate",
        "familywise_false_alarm_rate",
        "interval_coverage",
        "nonconvergence_rate",
        "signal_attenuation_fraction",
    }
)


class CalibrationError(ValueError):
    """Raised for an invalid or incomplete calibration declaration."""


def _native_identifier(value: str, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a native string")
    if not value or value.strip() != value:
        raise ValueError(f"{name} must be non-empty with no surrounding whitespace")
    return value


def _sha256(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _finite_real(value: object, name: str) -> float:
    if type(value) not in {int, float} and type(value) not in _NUMPY_REAL_TYPES:
        raise TypeError(f"{name} must be a native or NumPy real scalar")
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _canonical_payload(value: object, name: str) -> bytes:
    try:
        result = canonical_json_bytes(value)
    except Exception as exc:
        raise CalibrationError(
            f"{name} must be strict native JSON; "
            f"{_diagnostic_message(exc, failure_code='strict_json_invalid')}"
        ) from exc
    if json.loads(result) is None:
        raise CalibrationError(f"{name} must not be JSON null")
    return result


def _payload_copy(payload: bytes) -> object:
    return json.loads(payload)


def _nonnegative_seed(value: int, name: str) -> int:
    if type(value) is not int and type(value) not in _NUMPY_INTEGER_TYPES:
        raise ValueError(f"{name} must be a non-negative integer")
    if int(value) < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return int(value)


def _safe_diagnostic_sha256(exc: BaseException | None, *, failure_code: str) -> str:
    """Hash bounded primitive diagnostics without invoking exception rendering hooks."""

    try:
        digest = hashlib.sha256()
        digest.update(failure_code.encode("ascii", errors="strict")[:128])
        if exc is not None:
            exc_type = type(exc)
            for value in (
                getattr(exc_type, "__module__", None),
                getattr(exc_type, "__qualname__", None),
            ):
                if type(value) is str:
                    digest.update(value[:128].encode("utf-8", errors="surrogatepass"))
            args = BaseException.args.__get__(exc)
            if type(args) is tuple:
                for argument in args[:8]:
                    if type(argument) is str:
                        digest.update(argument[:512].encode("utf-8", errors="surrogatepass"))
                    elif type(argument) is bytes:
                        digest.update(argument[:512])
                    elif argument is None or type(argument) in {bool, int, float}:
                        digest.update(
                            json.dumps(
                                argument,
                                allow_nan=False,
                                separators=(",", ":"),
                            ).encode("ascii")
                        )
                    else:
                        argument_type = type(argument)
                        for value in (
                            getattr(argument_type, "__module__", None),
                            getattr(argument_type, "__qualname__", None),
                        ):
                            if type(value) is str:
                                digest.update(value[:128].encode("utf-8", errors="surrogatepass"))
        return digest.hexdigest()
    except BaseException:  # noqa: BLE001 - diagnostic fallback must itself be fail-safe.
        return _DIAGNOSTIC_FALLBACK


def _diagnostic_message(exc: BaseException | None, *, failure_code: str) -> str:
    return f"diagnostic_sha256:{_safe_diagnostic_sha256(exc, failure_code=failure_code)}"


@dataclass(frozen=True, slots=True)
class CalibrationCandidate:
    """Content-identified caller-supplied policy, contract, or search design."""

    candidate_id: str
    definition_json: bytes

    def __post_init__(self) -> None:
        _native_identifier(self.candidate_id, "candidate_id")
        if type(self.definition_json) is not bytes:
            raise TypeError("definition_json must be canonical bytes from from_definition")
        canonical = _canonical_payload(_payload_copy(self.definition_json), "candidate definition")
        if canonical != self.definition_json:
            raise CalibrationError("definition_json is not in canonical form")

    @classmethod
    def from_definition(cls, candidate_id: str, definition: object) -> CalibrationCandidate:
        """Create a detached candidate from strict JSON definition data."""

        return cls(
            candidate_id=_native_identifier(candidate_id, "candidate_id"),
            definition_json=_canonical_payload(definition, "candidate definition"),
        )

    @property
    def definition(self) -> object:
        """Return a fresh detached view of the candidate definition."""

        return _payload_copy(self.definition_json)

    @property
    def identity(self) -> str:
        """Canonical candidate content identity including its declared label."""

        return canonical_sha256(
            {"candidate_id": self.candidate_id, "definition": self.definition, "schema": 1}
        )


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    """Content-identified synthetic or declared-control evaluation case."""

    case_id: str
    truth_json: bytes

    def __post_init__(self) -> None:
        _native_identifier(self.case_id, "case_id")
        if type(self.truth_json) is not bytes:
            raise TypeError("truth_json must be canonical bytes from from_truth")
        canonical = _canonical_payload(_payload_copy(self.truth_json), "case truth")
        if canonical != self.truth_json:
            raise CalibrationError("truth_json is not in canonical form")

    @classmethod
    def from_truth(cls, case_id: str, truth: object) -> CalibrationCase:
        """Create a detached case from strict JSON truth metadata."""

        return cls(
            case_id=_native_identifier(case_id, "case_id"),
            truth_json=_canonical_payload(truth, "case truth"),
        )

    @property
    def truth(self) -> object:
        """Return a fresh detached view of the declared truth metadata."""

        return _payload_copy(self.truth_json)

    @property
    def identity(self) -> str:
        """Canonical case content identity including its declared label."""

        return canonical_sha256({"case_id": self.case_id, "schema": 1, "truth": self.truth})


def _normalize_metrics(
    metrics: tuple[tuple[str, float], ...],
) -> tuple[tuple[str, float], ...]:
    if type(metrics) is not tuple or not metrics:
        raise TypeError("metrics must be a non-empty tuple")
    normalized: list[tuple[str, float]] = []
    names: list[str] = []
    for item in metrics:
        if type(item) is not tuple or len(item) != 2:
            raise TypeError("every metric must be a (name, value) tuple")
        name = _native_identifier(item[0], "metric name")
        value = _finite_real(item[1], f"metric {name!r}")
        names.append(name)
        normalized.append((name, value))
    if len(set(names)) != len(names):
        raise ValueError("metric names must be unique")
    return tuple(sorted(normalized))


def _result_sha256(
    trial_id: str,
    metrics: tuple[tuple[str, float], ...],
) -> str:
    return canonical_sha256(
        {
            "metrics": [{"name": name, "value": value} for name, value in metrics],
            "schema": 1,
            "trial_id": trial_id,
        }
    )


def calibration_result_sha256(trial_id: str, metrics: dict[str, float]) -> str:
    """Return the canonical hash an execution attestation must bind for one result."""

    _native_identifier(trial_id, "outcome trial_id")
    if type(metrics) is not dict:
        raise TypeError("metrics must be a native dictionary")
    return _result_sha256(trial_id, _normalize_metrics(tuple(metrics.items())))


def _execution_signature_payload_sha256(
    *,
    plan_sha256: str,
    evaluator_sha256: str,
    attestation_verifier_sha256: str,
    trial_sha256: str,
    result_sha256: str,
    executor_identity_sha256: str,
    executor_key_sha256: str,
    signature_scheme: str,
    signed_at: str,
) -> str:
    return canonical_sha256(
        {
            "attestation_verifier_sha256": attestation_verifier_sha256,
            "evaluator_sha256": evaluator_sha256,
            "executor_identity_sha256": executor_identity_sha256,
            "executor_key_sha256": executor_key_sha256,
            "plan_sha256": plan_sha256,
            "result_sha256": result_sha256,
            "schema_version": 1,
            "signature_scheme": signature_scheme,
            "signed_at": signed_at,
            "trial_sha256": trial_sha256,
        }
    )


@dataclass(frozen=True, slots=True)
class CalibrationExecutionAttestation:
    """Exact-schema, externally verifiable binding of one executed cell and result.

    This structure validates canonical content bindings.  Authenticity and executor
    independence are established only when a caller-supplied external verifier accepts the
    signature; an in-process callback cannot by itself make those properties trustworthy.
    """

    schema_version: int
    plan_sha256: str
    evaluator_sha256: str
    attestation_verifier_sha256: str
    trial_sha256: str
    result_sha256: str
    executor_identity_sha256: str
    executor_key_sha256: str
    signature: SignatureMetadata

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise CalibrationError("unsupported calibration execution attestation schema")
        for field in (
            "plan_sha256",
            "evaluator_sha256",
            "attestation_verifier_sha256",
            "trial_sha256",
            "result_sha256",
            "executor_identity_sha256",
            "executor_key_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if type(self.signature) is not SignatureMetadata:
            raise TypeError("attestation signature must be exact SignatureMetadata")
        signature = SignatureMetadata(
            scheme=self.signature.scheme,
            key_id=self.signature.key_id,
            signature=self.signature.signature,
            signed_content_sha256=self.signature.signed_content_sha256,
            signed_at=self.signature.signed_at,
        )
        object.__setattr__(self, "signature", signature)
        if signature.key_id != self.executor_key_sha256:
            raise CalibrationError("attestation signature key does not bind the executor key")
        if signature.signed_content_sha256 != self.signature_payload_sha256:
            raise CalibrationError("attestation signature does not bind the exact payload")

    @classmethod
    def from_execution(
        cls,
        *,
        plan_sha256: str,
        evaluator_sha256: str,
        attestation_verifier_sha256: str,
        trial_sha256: str,
        result_sha256: str,
        executor_identity_sha256: str,
        executor_key_sha256: str,
        signature_scheme: str,
        signature: str,
        signed_at: str,
    ) -> CalibrationExecutionAttestation:
        """Build exact metadata around a signature supplied by an external executor."""

        payload_sha256 = _execution_signature_payload_sha256(
            plan_sha256=plan_sha256,
            evaluator_sha256=evaluator_sha256,
            attestation_verifier_sha256=attestation_verifier_sha256,
            trial_sha256=trial_sha256,
            result_sha256=result_sha256,
            executor_identity_sha256=executor_identity_sha256,
            executor_key_sha256=executor_key_sha256,
            signature_scheme=signature_scheme,
            signed_at=signed_at,
        )
        return cls(
            schema_version=1,
            plan_sha256=plan_sha256,
            evaluator_sha256=evaluator_sha256,
            attestation_verifier_sha256=attestation_verifier_sha256,
            trial_sha256=trial_sha256,
            result_sha256=result_sha256,
            executor_identity_sha256=executor_identity_sha256,
            executor_key_sha256=executor_key_sha256,
            signature=SignatureMetadata(
                scheme=signature_scheme,
                key_id=executor_key_sha256,
                signature=signature,
                signed_content_sha256=payload_sha256,
                signed_at=signed_at,
            ),
        )

    @property
    def signature_payload_sha256(self) -> str:
        """Canonical payload hash the external signature must cover."""

        return _execution_signature_payload_sha256(
            plan_sha256=self.plan_sha256,
            evaluator_sha256=self.evaluator_sha256,
            attestation_verifier_sha256=self.attestation_verifier_sha256,
            trial_sha256=self.trial_sha256,
            result_sha256=self.result_sha256,
            executor_identity_sha256=self.executor_identity_sha256,
            executor_key_sha256=self.executor_key_sha256,
            signature_scheme=self.signature.scheme,
            signed_at=self.signature.signed_at,
        )

    @property
    def identity(self) -> str:
        """Canonical identity including external signature metadata."""

        return canonical_sha256(
            {
                "attestation_verifier_sha256": self.attestation_verifier_sha256,
                "evaluator_sha256": self.evaluator_sha256,
                "executor_identity_sha256": self.executor_identity_sha256,
                "executor_key_sha256": self.executor_key_sha256,
                "plan_sha256": self.plan_sha256,
                "result_sha256": self.result_sha256,
                "schema_version": self.schema_version,
                "signature": self.signature.as_dict(),
                "trial_sha256": self.trial_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class CalibrationTrial:
    """One deterministic candidate-by-case request."""

    trial_id: str
    plan_id: str
    domain: CalibrationDomain
    candidate: CalibrationCandidate
    case: CalibrationCase
    trial_seed: int
    evaluator_sha256: str
    attestation_verifier_sha256: str

    def __post_init__(self) -> None:
        _native_identifier(self.trial_id, "trial_id")
        plan_id = _sha256(self.plan_id, "plan_id")
        if type(self.domain) is not str or self.domain not in _REQUIRED_METRICS:
            raise ValueError("unsupported calibration domain")
        if type(self.candidate) is not CalibrationCandidate:
            raise TypeError("candidate must be an exact CalibrationCandidate")
        if type(self.case) is not CalibrationCase:
            raise TypeError("case must be an exact CalibrationCase")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "trial_seed", _nonnegative_seed(self.trial_seed, "trial_seed"))
        object.__setattr__(
            self,
            "evaluator_sha256",
            _sha256(self.evaluator_sha256, "evaluator_sha256"),
        )
        object.__setattr__(
            self,
            "attestation_verifier_sha256",
            _sha256(
                self.attestation_verifier_sha256,
                "attestation_verifier_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class CalibrationOutcome:
    """Strict finite metric vector returned by a calibration evaluator."""

    trial_id: str
    metrics: tuple[tuple[str, float], ...]
    execution_attestation: CalibrationExecutionAttestation | None = None

    def __post_init__(self) -> None:
        _native_identifier(self.trial_id, "outcome trial_id")
        object.__setattr__(self, "metrics", _normalize_metrics(self.metrics))
        if self.execution_attestation is not None and (
            type(self.execution_attestation) is not CalibrationExecutionAttestation
        ):
            raise TypeError(
                "execution_attestation must be exact CalibrationExecutionAttestation when present"
            )
        if self.execution_attestation is not None:
            attestation = CalibrationExecutionAttestation(
                schema_version=self.execution_attestation.schema_version,
                plan_sha256=self.execution_attestation.plan_sha256,
                evaluator_sha256=self.execution_attestation.evaluator_sha256,
                attestation_verifier_sha256=(
                    self.execution_attestation.attestation_verifier_sha256
                ),
                trial_sha256=self.execution_attestation.trial_sha256,
                result_sha256=self.execution_attestation.result_sha256,
                executor_identity_sha256=(self.execution_attestation.executor_identity_sha256),
                executor_key_sha256=self.execution_attestation.executor_key_sha256,
                signature=self.execution_attestation.signature,
            )
            object.__setattr__(self, "execution_attestation", attestation)

    @classmethod
    def from_metrics(
        cls,
        trial_id: str,
        metrics: dict[str, float],
        *,
        execution_attestation: CalibrationExecutionAttestation | None = None,
    ) -> CalibrationOutcome:
        """Create an immutable outcome from an explicit native dictionary."""

        if type(metrics) is not dict:
            raise TypeError("metrics must be a native dictionary")
        return cls(
            trial_id=trial_id,
            metrics=tuple(metrics.items()),
            execution_attestation=execution_attestation,
        )

    @property
    def result_sha256(self) -> str:
        """Canonical identity of the full trial ID and sorted metric vector."""

        return _result_sha256(self.trial_id, self.metrics)

    def metric(self, name: str) -> float:
        """Return one declared metric by exact name."""

        requested = _native_identifier(name, "metric name")
        for metric_name, value in self.metrics:
            if metric_name == requested:
                return value
        raise KeyError(requested)


class CalibrationEvaluator(Protocol):
    """Callable that evaluates one candidate on one case with fresh state."""

    def __call__(self, trial: CalibrationTrial, /) -> CalibrationOutcome: ...


class CalibrationAttestationVerifier(Protocol):
    """External verifier for one exact execution attestation."""

    def __call__(self, attestation: CalibrationExecutionAttestation, /) -> bool: ...


@dataclass(frozen=True, slots=True)
class CalibrationFailure:
    """Auditable failure for one planned candidate-by-case cell."""

    trial_id: str
    exception_type: str
    message: str

    def __post_init__(self) -> None:
        _native_identifier(self.trial_id, "failure trial_id")
        _native_identifier(self.exception_type, "exception_type")
        if self.exception_type not in _FAILURE_CODES:
            raise ValueError("unsupported calibration failure code")
        if type(self.message) is not str or _DIAGNOSTIC.fullmatch(self.message) is None:
            raise ValueError("failure message must be a safe diagnostic SHA-256")


def _validate_outcome_attestation(
    trial: CalibrationTrial,
    outcome: CalibrationOutcome,
) -> CalibrationExecutionAttestation:
    attestation = outcome.execution_attestation
    if type(attestation) is not CalibrationExecutionAttestation:
        raise CalibrationError("successful outcome requires an execution attestation")
    expected = {
        "plan_sha256": trial.plan_id,
        "evaluator_sha256": trial.evaluator_sha256,
        "attestation_verifier_sha256": trial.attestation_verifier_sha256,
        "trial_sha256": trial.trial_id,
        "result_sha256": outcome.result_sha256,
    }
    for field, value in expected.items():
        if getattr(attestation, field) != value:
            raise CalibrationError(f"execution attestation does not bind {field}")
    return attestation


def _verify_outcome_attestation(
    trial: CalibrationTrial,
    outcome: CalibrationOutcome,
    verifier: CalibrationAttestationVerifier,
    verifier_identity: str,
) -> None:
    identity = _sha256(verifier_identity, "attestation_verifier_identity")
    if identity != trial.attestation_verifier_sha256:
        raise CalibrationError("attestation verifier identity does not match the trial plan")
    if not callable(verifier):
        raise TypeError("attestation_verifier must be callable")
    attestation = _validate_outcome_attestation(trial, outcome)
    verifier_input = CalibrationExecutionAttestation(
        schema_version=attestation.schema_version,
        plan_sha256=attestation.plan_sha256,
        evaluator_sha256=attestation.evaluator_sha256,
        attestation_verifier_sha256=attestation.attestation_verifier_sha256,
        trial_sha256=attestation.trial_sha256,
        result_sha256=attestation.result_sha256,
        executor_identity_sha256=attestation.executor_identity_sha256,
        executor_key_sha256=attestation.executor_key_sha256,
        signature=attestation.signature,
    )
    try:
        verified = verifier(verifier_input)
    except Exception as exc:  # noqa: BLE001 - external verifier failures must fail closed.
        raise CalibrationError(
            "execution attestation verifier failed; "
            f"{_diagnostic_message(exc, failure_code='attestation_verifier_failure')}"
        ) from None
    if verified is not True:
        raise CalibrationError("execution attestation verifier rejected the evidence")


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    """One planned cell whose successful outcome was accepted by the bound verifier."""

    trial: CalibrationTrial
    outcome: CalibrationOutcome | None
    failure: CalibrationFailure | None
    attestation_verifier: InitVar[CalibrationAttestationVerifier]
    attestation_verifier_identity: InitVar[str]
    verification_status: Literal["accepted", "not_applicable"] = dataclass_field(init=False)

    def __post_init__(
        self,
        attestation_verifier: CalibrationAttestationVerifier,
        attestation_verifier_identity: str,
    ) -> None:
        if type(self.trial) is not CalibrationTrial:
            raise TypeError("trial must be an exact CalibrationTrial")
        trial = CalibrationTrial(
            trial_id=self.trial.trial_id,
            plan_id=self.trial.plan_id,
            domain=self.trial.domain,
            candidate=self.trial.candidate,
            case=self.trial.case,
            trial_seed=self.trial.trial_seed,
            evaluator_sha256=self.trial.evaluator_sha256,
            attestation_verifier_sha256=self.trial.attestation_verifier_sha256,
        )
        object.__setattr__(self, "trial", trial)
        if self.outcome is not None:
            if type(self.outcome) is not CalibrationOutcome:
                raise TypeError("outcome must be an exact CalibrationOutcome when present")
            outcome = CalibrationOutcome(
                trial_id=self.outcome.trial_id,
                metrics=self.outcome.metrics,
                execution_attestation=self.outcome.execution_attestation,
            )
            object.__setattr__(self, "outcome", outcome)
        if self.failure is not None:
            if type(self.failure) is not CalibrationFailure:
                raise TypeError("failure must be an exact CalibrationFailure when present")
            failure = CalibrationFailure(
                trial_id=self.failure.trial_id,
                exception_type=self.failure.exception_type,
                message=self.failure.message,
            )
            object.__setattr__(self, "failure", failure)
        if (self.outcome is None) == (self.failure is None):
            raise ValueError("a calibration record must contain exactly one outcome or failure")
        if self.outcome is not None and self.outcome.trial_id != trial.trial_id:
            raise ValueError("outcome trial ID does not match the planned trial")
        if self.outcome is not None:
            _validate_outcome_attestation(trial, self.outcome)
            _verify_outcome_attestation(
                trial,
                self.outcome,
                attestation_verifier,
                attestation_verifier_identity,
            )
            object.__setattr__(self, "verification_status", "accepted")
        if self.failure is not None and self.failure.trial_id != trial.trial_id:
            raise ValueError("failure trial ID does not match the planned trial")
        if self.failure is not None:
            identity = _sha256(
                attestation_verifier_identity,
                "attestation_verifier_identity",
            )
            if identity != trial.attestation_verifier_sha256:
                raise CalibrationError(
                    "attestation verifier identity does not match the failed trial plan"
                )
            if not callable(attestation_verifier):
                raise TypeError("attestation_verifier must be callable")
            object.__setattr__(self, "verification_status", "not_applicable")

    @property
    def structurally_successful(self) -> bool:
        """Whether a structurally matching outcome and attestation are retained."""

        return self.outcome is not None and self.failure is None

    @property
    def verified_successful(self) -> bool:
        """Whether the retained structural outcome was accepted by the bound verifier."""

        return self.structurally_successful and self.verification_status == "accepted"

    def verify_integrity(
        self,
        attestation_verifier: CalibrationAttestationVerifier,
        *,
        attestation_verifier_identity: str,
    ) -> CalibrationRecord:
        """Reconstruct this record and rerun the externally controlled verifier."""

        return CalibrationRecord(
            trial=self.trial,
            outcome=self.outcome,
            failure=self.failure,
            attestation_verifier=attestation_verifier,
            attestation_verifier_identity=attestation_verifier_identity,
        )


def _plan_payload(
    domain: CalibrationDomain,
    candidates: tuple[CalibrationCandidate, ...],
    cases: tuple[CalibrationCase, ...],
    *,
    evaluator_sha256: str,
    attestation_verifier_sha256: str,
    seed: int,
) -> dict[str, object]:
    return {
        "candidates": [
            {"candidate_id": candidate.candidate_id, "identity": candidate.identity}
            for candidate in candidates
        ],
        "cases": [{"case_id": case.case_id, "identity": case.identity} for case in cases],
        "domain": domain,
        "evaluator_sha256": evaluator_sha256,
        "attestation_verifier_sha256": attestation_verifier_sha256,
        "required_metrics": list(_REQUIRED_METRICS[domain]),
        "schema": 3,
        "seed": seed,
        "seed_derivation": "numpy-seed-sequence-uint64-v1",
    }


def _trial_seeds(seed: int, count: int) -> tuple[int, ...]:
    children = np.random.SeedSequence([seed, _CALIBRATION_SEED_DOMAIN]).spawn(count)
    result = tuple(int(child.generate_state(1, dtype=np.uint64)[0]) for child in children)
    if len(set(result)) != count:
        raise RuntimeError("calibration child-seed derivation produced a duplicate")
    return result


def _trial_id(
    *,
    plan_id: str,
    candidate: CalibrationCandidate,
    case: CalibrationCase,
    trial_seed: int,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "candidate_identity": candidate.identity,
                "case_identity": case.identity,
                "plan_id": plan_id,
                "trial_seed": trial_seed,
            }
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Verifier-accepted comparison table with no automatic scientific selection."""

    plan_id: str
    domain: CalibrationDomain
    experiment_identity: str
    attestation_verifier_identity: str
    master_seed: int
    required_metrics: tuple[str, ...]
    candidates: tuple[CalibrationCandidate, ...]
    cases: tuple[CalibrationCase, ...]
    records: tuple[CalibrationRecord, ...]
    failures: tuple[CalibrationFailure, ...]
    attestation_verifier: InitVar[CalibrationAttestationVerifier]

    def __post_init__(self, attestation_verifier: CalibrationAttestationVerifier) -> None:
        plan_id = _sha256(self.plan_id, "plan_id")
        if type(self.domain) is not str or self.domain not in _REQUIRED_METRICS:
            raise ValueError("unsupported calibration domain")
        evaluator_sha256 = _sha256(self.experiment_identity, "experiment_identity")
        verifier_sha256 = _sha256(
            self.attestation_verifier_identity,
            "attestation_verifier_identity",
        )
        master_seed = _nonnegative_seed(self.master_seed, "master_seed")
        required = _REQUIRED_METRICS[self.domain]
        if type(self.required_metrics) is not tuple or self.required_metrics != required:
            raise ValueError("required_metrics do not match the calibration domain")
        if (
            type(self.candidates) is not tuple
            or not self.candidates
            or any(type(candidate) is not CalibrationCandidate for candidate in self.candidates)
        ):
            raise TypeError("candidates must be a non-empty tuple of CalibrationCandidate values")
        if (
            type(self.cases) is not tuple
            or not self.cases
            or any(type(case) is not CalibrationCase for case in self.cases)
        ):
            raise TypeError("cases must be a non-empty tuple of CalibrationCase values")
        if len({candidate.candidate_id for candidate in self.candidates}) != len(self.candidates):
            raise ValueError("candidate IDs must be unique")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        expected_plan_id = canonical_sha256(
            _plan_payload(
                self.domain,
                self.candidates,
                self.cases,
                evaluator_sha256=evaluator_sha256,
                attestation_verifier_sha256=verifier_sha256,
                seed=master_seed,
            )
        )
        if plan_id != expected_plan_id:
            raise ValueError("plan_id does not bind the complete calibration plan")
        expected_count = len(self.candidates) * len(self.cases)
        if (
            type(self.records) is not tuple
            or len(self.records) != expected_count
            or any(type(record) is not CalibrationRecord for record in self.records)
        ):
            raise ValueError("records must cover every candidate-by-case cell")
        records = tuple(
            CalibrationRecord(
                trial=record.trial,
                outcome=record.outcome,
                failure=record.failure,
                attestation_verifier=attestation_verifier,
                attestation_verifier_identity=verifier_sha256,
            )
            for record in self.records
        )
        seeds = _trial_seeds(master_seed, expected_count)
        index = 0
        for candidate in self.candidates:
            for case in self.cases:
                record = records[index]
                trial_seed = seeds[index]
                index += 1
                expected_trial_id = _trial_id(
                    plan_id=plan_id,
                    candidate=candidate,
                    case=case,
                    trial_seed=trial_seed,
                )
                if (
                    record.trial.trial_id != expected_trial_id
                    or record.trial.plan_id != plan_id
                    or record.trial.domain != self.domain
                    or record.trial.candidate != candidate
                    or record.trial.case != case
                    or record.trial.trial_seed != trial_seed
                    or record.trial.evaluator_sha256 != evaluator_sha256
                    or record.trial.attestation_verifier_sha256 != verifier_sha256
                ):
                    raise ValueError("calibration record does not match its planned cell")
                if record.outcome is not None:
                    supplied_names = tuple(name for name, _ in record.outcome.metrics)
                    if supplied_names != tuple(sorted(required)):
                        raise ValueError("outcome metrics do not match the complete domain schema")
                    for metric_name, value in record.outcome.metrics:
                        if metric_name in _UNIT_INTERVAL_METRICS and not 0.0 <= value <= 1.0:
                            raise ValueError(
                                f"rate metric {metric_name!r} must lie in the unit interval"
                            )
        if len({record.trial.trial_id for record in records}) != expected_count:
            raise ValueError("calibration records must have unique trial IDs")
        derived_failures = tuple(record.failure for record in records if record.failure is not None)
        if type(self.failures) is not tuple or self.failures != derived_failures:
            raise ValueError("failure list does not match retained calibration records")
        object.__setattr__(self, "plan_id", plan_id)
        object.__setattr__(self, "experiment_identity", evaluator_sha256)
        object.__setattr__(self, "attestation_verifier_identity", verifier_sha256)
        object.__setattr__(self, "master_seed", master_seed)
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "failures", derived_failures)

    @property
    def structurally_complete(self) -> bool:
        """Whether every cell retains a structurally matching outcome and attestation."""

        return (
            not self.failures
            and len(self.records) == len(self.candidates) * len(self.cases)
            and all(record.structurally_successful for record in self.records)
        )

    @property
    def verified_complete(self) -> bool:
        """Whether every structural outcome was accepted by the bound external verifier."""

        return self.structurally_complete and all(
            record.verified_successful for record in self.records
        )

    @property
    def complete(self) -> bool:
        """Backward-compatible alias for verifier-accepted completeness."""

        return self.verified_complete

    def verify_integrity(
        self,
        attestation_verifier: CalibrationAttestationVerifier,
        *,
        attestation_verifier_identity: str,
    ) -> CalibrationReport:
        """Reconstruct the report and rerun the exact bound verifier for every success."""

        identity = _sha256(
            attestation_verifier_identity,
            "attestation_verifier_identity",
        )
        if identity != self.attestation_verifier_identity:
            raise CalibrationError("revalidation verifier identity does not match the report")
        return CalibrationReport(
            plan_id=self.plan_id,
            domain=self.domain,
            experiment_identity=self.experiment_identity,
            attestation_verifier_identity=self.attestation_verifier_identity,
            master_seed=self.master_seed,
            required_metrics=self.required_metrics,
            candidates=self.candidates,
            cases=self.cases,
            records=self.records,
            failures=self.failures,
            attestation_verifier=attestation_verifier,
        )

    def metric_table(self, metric: str) -> tuple[tuple[str, str, float | None], ...]:
        """Return all candidate/case values, retaining failed cells as None."""

        requested = _native_identifier(metric, "metric")
        if requested not in self.required_metrics:
            raise KeyError(requested)
        rows: list[tuple[str, str, float | None]] = []
        for record in self.records:
            value = None if record.outcome is None else record.outcome.metric(requested)
            rows.append((record.trial.candidate.candidate_id, record.trial.case.case_id, value))
        return tuple(rows)


def _evaluate_grid(
    domain: CalibrationDomain,
    candidates: tuple[CalibrationCandidate, ...],
    cases: tuple[CalibrationCase, ...],
    evaluator: CalibrationEvaluator,
    *,
    seed: int,
    experiment_identity: str,
    attestation_verifier: CalibrationAttestationVerifier,
    attestation_verifier_identity: str,
) -> CalibrationReport:
    if domain not in _REQUIRED_METRICS:
        raise ValueError("unsupported calibration domain")
    if type(candidates) is not tuple or not candidates:
        raise TypeError("candidates must be a non-empty tuple")
    if type(cases) is not tuple or not cases:
        raise TypeError("cases must be a non-empty tuple")
    if any(type(candidate) is not CalibrationCandidate for candidate in candidates):
        raise TypeError("every candidate must be a CalibrationCandidate")
    if any(type(case) is not CalibrationCase for case in cases):
        raise TypeError("every case must be a CalibrationCase")
    if not callable(evaluator):
        raise TypeError("evaluator must be callable")
    if not callable(attestation_verifier):
        raise TypeError("attestation_verifier must be callable")
    master_seed = _nonnegative_seed(seed, "seed")
    identity = _sha256(experiment_identity, "experiment_identity")
    verifier_identity = _sha256(
        attestation_verifier_identity,
        "attestation_verifier_identity",
    )
    candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
    case_ids = tuple(case.case_id for case in cases)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ValueError("candidate IDs must be unique")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("case IDs must be unique")
    required_metrics = _REQUIRED_METRICS[domain]
    plan_id = canonical_sha256(
        _plan_payload(
            domain,
            candidates,
            cases,
            evaluator_sha256=identity,
            attestation_verifier_sha256=verifier_identity,
            seed=master_seed,
        )
    )
    trial_count = len(candidates) * len(cases)
    trial_seeds = _trial_seeds(master_seed, trial_count)

    records: list[CalibrationRecord] = []
    failures: list[CalibrationFailure] = []
    seed_index = 0
    for candidate in candidates:
        for case in cases:
            trial_seed = trial_seeds[seed_index]
            seed_index += 1
            trial_id = _trial_id(
                plan_id=plan_id,
                candidate=candidate,
                case=case,
                trial_seed=trial_seed,
            )
            trial = CalibrationTrial(
                trial_id=trial_id,
                plan_id=plan_id,
                domain=domain,
                candidate=candidate,
                case=case,
                trial_seed=trial_seed,
                evaluator_sha256=identity,
                attestation_verifier_sha256=verifier_identity,
            )
            outcome: CalibrationOutcome | None = None
            failure: CalibrationFailure | None = None
            try:
                supplied = evaluator(trial)
            except Exception as exc:  # noqa: BLE001 - every planned failure is evidence.
                failure_code = "calibration_evaluator_exception"
                failure = CalibrationFailure(
                    trial_id=trial.trial_id,
                    exception_type=failure_code,
                    message=_diagnostic_message(exc, failure_code=failure_code),
                )
            else:
                try:
                    if type(supplied) is not CalibrationOutcome:
                        raise TypeError("evaluator must return CalibrationOutcome")
                    if supplied.trial_id != trial.trial_id:
                        raise CalibrationError("evaluator returned a stale trial ID")
                    supplied_names = tuple(name for name, _ in supplied.metrics)
                    if supplied_names != tuple(sorted(required_metrics)):
                        raise CalibrationError(
                            "outcome metrics must match the complete required metric schema"
                        )
                    for metric_name, value in supplied.metrics:
                        if metric_name in _UNIT_INTERVAL_METRICS and not 0.0 <= value <= 1.0:
                            raise CalibrationError(
                                f"rate metric {metric_name!r} must lie in the unit interval"
                            )
                    attestation = _validate_outcome_attestation(trial, supplied)
                except Exception as exc:  # noqa: BLE001 - invalid evidence remains accounted.
                    failure_code = "calibration_outcome_invalid"
                    failure = CalibrationFailure(
                        trial_id=trial.trial_id,
                        exception_type=failure_code,
                        message=_diagnostic_message(exc, failure_code=failure_code),
                    )
                else:
                    verifier_input = CalibrationExecutionAttestation(
                        schema_version=attestation.schema_version,
                        plan_sha256=attestation.plan_sha256,
                        evaluator_sha256=attestation.evaluator_sha256,
                        attestation_verifier_sha256=(attestation.attestation_verifier_sha256),
                        trial_sha256=attestation.trial_sha256,
                        result_sha256=attestation.result_sha256,
                        executor_identity_sha256=attestation.executor_identity_sha256,
                        executor_key_sha256=attestation.executor_key_sha256,
                        signature=attestation.signature,
                    )
                    try:
                        verified = attestation_verifier(verifier_input)
                    except Exception as exc:  # noqa: BLE001 - verifier failure is evidence.
                        failure_code = "calibration_attestation_verifier_exception"
                        failure = CalibrationFailure(
                            trial_id=trial.trial_id,
                            exception_type=failure_code,
                            message=_diagnostic_message(exc, failure_code=failure_code),
                        )
                    else:
                        if verified is not True:
                            failure_code = "calibration_attestation_rejected"
                            failure = CalibrationFailure(
                                trial_id=trial.trial_id,
                                exception_type=failure_code,
                                message=_diagnostic_message(None, failure_code=failure_code),
                            )
                        else:
                            outcome = supplied
            if failure is not None:
                failures.append(failure)
            records.append(
                CalibrationRecord(
                    trial=trial,
                    outcome=outcome,
                    failure=failure,
                    attestation_verifier=attestation_verifier,
                    attestation_verifier_identity=verifier_identity,
                )
            )

    return CalibrationReport(
        plan_id=plan_id,
        domain=domain,
        experiment_identity=identity,
        attestation_verifier_identity=verifier_identity,
        master_seed=master_seed,
        required_metrics=required_metrics,
        candidates=candidates,
        cases=cases,
        records=tuple(records),
        failures=tuple(failures),
        attestation_verifier=attestation_verifier,
    )


def evaluate_convergence_grid(
    candidates: tuple[CalibrationCandidate, ...],
    cases: tuple[CalibrationCase, ...],
    evaluator: CalibrationEvaluator,
    *,
    seed: int,
    experiment_identity: str,
    attestation_verifier: CalibrationAttestationVerifier,
    attestation_verifier_identity: str,
) -> CalibrationReport:
    """Evaluate every declared convergence policy on every declared case."""

    return _evaluate_grid(
        "convergence",
        candidates,
        cases,
        evaluator,
        seed=seed,
        experiment_identity=experiment_identity,
        attestation_verifier=attestation_verifier,
        attestation_verifier_identity=attestation_verifier_identity,
    )


def evaluate_selection_grid(
    candidates: tuple[CalibrationCandidate, ...],
    cases: tuple[CalibrationCase, ...],
    evaluator: CalibrationEvaluator,
    *,
    seed: int,
    experiment_identity: str,
    attestation_verifier: CalibrationAttestationVerifier,
    attestation_verifier_identity: str,
) -> CalibrationReport:
    """Evaluate every declared selection contract on every declared case."""

    return _evaluate_grid(
        "selection",
        candidates,
        cases,
        evaluator,
        seed=seed,
        experiment_identity=experiment_identity,
        attestation_verifier=attestation_verifier,
        attestation_verifier_identity=attestation_verifier_identity,
    )


def evaluate_search_design_grid(
    candidates: tuple[CalibrationCandidate, ...],
    cases: tuple[CalibrationCase, ...],
    evaluator: CalibrationEvaluator,
    *,
    seed: int,
    experiment_identity: str,
    attestation_verifier: CalibrationAttestationVerifier,
    attestation_verifier_identity: str,
) -> CalibrationReport:
    """Evaluate every declared search design on every declared case."""

    return _evaluate_grid(
        "search",
        candidates,
        cases,
        evaluator,
        seed=seed,
        experiment_identity=experiment_identity,
        attestation_verifier=attestation_verifier,
        attestation_verifier_identity=attestation_verifier_identity,
    )


__all__ = [
    "CalibrationAttestationVerifier",
    "CalibrationCandidate",
    "CalibrationCase",
    "CalibrationDomain",
    "CalibrationError",
    "CalibrationEvaluator",
    "CalibrationExecutionAttestation",
    "CalibrationFailure",
    "CalibrationOutcome",
    "CalibrationRecord",
    "CalibrationReport",
    "CalibrationTrial",
    "calibration_result_sha256",
    "evaluate_convergence_grid",
    "evaluate_search_design_grid",
    "evaluate_selection_grid",
]
