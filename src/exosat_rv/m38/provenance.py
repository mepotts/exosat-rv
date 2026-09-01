"""Content-bound, append-only provenance primitives for control-only M38 development.

This module contains generic infrastructure only.  It does not know any target names,
scientific thresholds, or repository data locations.  Callers supply every file and every
piece of stage metadata explicitly.

The append helper and ``O_EXCL`` protect against cooperative accidental replacement on a
trusted local filesystem.  They are not a defence against a hostile or privileged filesystem
namespace, directory replacement, or TOCTOU races; callers still need trusted directories and
OS-level confinement.

The signature hooks deliberately do not choose a signing scheme.  A signer receives the
canonical payload bytes and returns JSON-serialisable signature details; a verifier receives
the same bytes and those details.  With no signer, a manifest is visibly labelled unsigned.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MANIFEST_SUFFIX = ".manifest.json"
_MAX_JSON_NESTING = 256
_ROOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MANIFEST_NAME = re.compile(r"([0-9]+)" + re.escape(MANIFEST_SUFFIX) + r"\Z")
_SUCCESS_STATUSES = frozenset({"complete", "success"})
_FAILURE_STATUSES = frozenset({"failed", "failure", "stopped"})
_PAYLOAD_FIELDS = frozenset(
    {
        "argv",
        "config",
        "dependencies",
        "ended_at",
        "exit_status",
        "failure_reason",
        "inputs",
        "outputs",
        "prior_manifest_sha256",
        "protocol",
        "schema_version",
        "seeds",
        "sequence",
        "source",
        "stage",
        "started_at",
        "status",
    }
)

Signer = Callable[[bytes], Mapping[str, Any] | str]
SignatureVerifier = Callable[[bytes, Mapping[str, Any]], bool]


class ProvenanceError(RuntimeError):
    """Base class for provenance construction and verification failures."""


class ManifestExistsError(ProvenanceError):
    """Raised when an append-only manifest path already exists."""


class ManifestVerificationError(ProvenanceError):
    """Raised when a manifest, chain link, signature, or bound file does not verify."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for strict, native JSON values only."""

    normalised = _strict_json_copy(value)
    text = json.dumps(
        normalised,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return text.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Hash a JSON value in its canonical representation."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Stream a regular file into SHA-256."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strict_json_copy(
    value: Any,
    *,
    location: str = "$",
    active_containers: set[int] | None = None,
    depth: int = 0,
) -> Any:
    """Validate native JSON types without json.dumps' lossy key coercions."""

    if depth > _MAX_JSON_NESTING:
        raise ProvenanceError(
            f"JSON value exceeds maximum nesting depth {_MAX_JSON_NESTING} at {location}"
        )
    value_type = type(value)
    if value is None or value_type in {bool, int, str}:
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise ProvenanceError(f"non-finite number at {location}")
        return value
    if value_type in {list, dict}:
        active = set() if active_containers is None else active_containers
        identity = id(value)
        if identity in active:
            raise ProvenanceError(f"JSON value contains a reference cycle at {location}")
        active.add(identity)
        try:
            if value_type is list:
                return [
                    _strict_json_copy(
                        child,
                        location=f"{location}[{index}]",
                        active_containers=active,
                        depth=depth + 1,
                    )
                    for index, child in enumerate(value)
                ]
            detached: dict[str, Any] = {}
            for key, child in value.items():
                if type(key) is not str:
                    raise ProvenanceError(f"JSON mapping key at {location} must be a native string")
                detached[key] = _strict_json_copy(
                    child,
                    location=f"{location}.{key}",
                    active_containers=active,
                    depth=depth + 1,
                )
            return detached
        finally:
            active.remove(identity)
    raise ProvenanceError(f"value at {location} has non-native JSON type {value_type.__name__}")


def _json_copy(value: Any) -> Any:
    """Validate and detach a caller-owned strict JSON value."""

    return _strict_json_copy(value)


def _normalise_hash(value: str, *, field_name: str) -> str:
    if type(value) is not str:
        raise ProvenanceError(f"{field_name} must be a lowercase SHA-256 digest string")
    result = value.lower()
    if not _SHA256.fullmatch(result):
        raise ProvenanceError(f"{field_name} must be a lowercase SHA-256 digest")
    return result


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _reject_symlink_components(candidate: Path, root: Path) -> None:
    """Reject symlinks from a lexical root through the candidate itself."""

    root_absolute = _absolute(root)
    candidate_absolute = _absolute(candidate)
    try:
        relative = candidate_absolute.relative_to(root_absolute)
    except ValueError as exc:
        raise ProvenanceError(f"file escapes bound root: {candidate}") from exc

    cursor = root_absolute
    if cursor.is_symlink():
        raise ProvenanceError(f"bound root is a symlink: {root}")
    for component in relative.parts:
        cursor /= component
        if cursor.is_symlink():
            raise ProvenanceError(f"symlink is not an immutable file binding: {cursor}")


def _resolve_bound_file(path: Path, root: Path) -> tuple[Path, str]:
    root_absolute = _absolute(root)
    if not root_absolute.is_dir():
        raise ProvenanceError(f"bound root is not a directory: {root}")

    candidate = path if path.is_absolute() else root_absolute / path
    _reject_symlink_components(candidate, root_absolute)
    try:
        resolved_root = root_absolute.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(resolved_root)
    except (FileNotFoundError, ValueError) as exc:
        raise ProvenanceError(f"file is missing or escapes bound root: {path}") from exc
    if not resolved.is_file():
        raise ProvenanceError(f"bound path is not a regular file: {path}")
    return resolved, relative.as_posix()


@dataclass(frozen=True)
class ImmutableFileRecord:
    """A root-relative immutable file identity suitable for a stage manifest."""

    root: str
    path: str
    size_bytes: int
    sha256: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.root) is not str:
            raise ProvenanceError("file-record root must be a native string")
        if not _ROOT_ID.fullmatch(self.root):
            raise ProvenanceError(f"invalid root identifier: {self.root!r}")
        if type(self.path) is not str:
            raise ProvenanceError("file-record path must be a native string")
        relative = Path(self.path)
        if relative.is_absolute() or ".." in relative.parts or self.path != relative.as_posix():
            raise ProvenanceError(f"file-record path must be normalised and relative: {self.path}")
        if type(self.size_bytes) is not int:
            raise ProvenanceError("file-record size must be a native integer")
        if self.size_bytes < 0:
            raise ProvenanceError("file-record size cannot be negative")
        if type(self.metadata) is not dict:
            raise ProvenanceError("file-record metadata must be a native JSON object")
        object.__setattr__(self, "sha256", _normalise_hash(self.sha256, field_name="sha256"))
        object.__setattr__(self, "metadata", _json_copy(self.metadata))

    @classmethod
    def from_path(
        cls,
        path: str | os.PathLike[str],
        *,
        root: str | os.PathLike[str],
        root_id: str = "workspace",
        metadata: Mapping[str, Any] | None = None,
    ) -> ImmutableFileRecord:
        resolved, relative = _resolve_bound_file(Path(path), Path(root))
        return cls(
            root=root_id,
            path=relative,
            size_bytes=resolved.stat().st_size,
            sha256=sha256_file(resolved),
            metadata={} if metadata is None else metadata,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "metadata": _json_copy(self.metadata),
            "path": self.path,
            "root": self.root,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def immutable_file_record(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    root_id: str = "workspace",
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper returning a plain-JSON immutable file record."""

    return ImmutableFileRecord.from_path(
        path,
        root=root,
        root_id=root_id,
        metadata=metadata,
    ).as_dict()


def _coerce_record(record: ImmutableFileRecord | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, ImmutableFileRecord):
        return record.as_dict()
    if type(record) is not dict:
        raise ProvenanceError("immutable file records must be native JSON objects")
    expected_fields = {"root", "path", "size_bytes", "sha256", "metadata"}
    if set(record) != expected_fields:
        missing = sorted(expected_fields - set(record))
        unexpected = sorted(set(record) - expected_fields)
        raise ProvenanceError(
            f"immutable file record schema mismatch; missing={missing}, unexpected={unexpected}"
        )
    try:
        parsed = ImmutableFileRecord(
            root=record["root"],
            path=record["path"],
            size_bytes=record["size_bytes"],
            sha256=record["sha256"],
            metadata=record["metadata"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProvenanceError(f"invalid immutable file record: {record!r}") from exc
    return parsed.as_dict()


def verify_file_record(
    record: ImmutableFileRecord | Mapping[str, Any],
    *,
    bound_roots: Mapping[str, str | os.PathLike[str]],
) -> Path:
    """Re-resolve and rehash one immutable file record."""

    parsed = _coerce_record(record)
    try:
        root = Path(bound_roots[parsed["root"]])
    except KeyError as exc:
        raise ManifestVerificationError(f"no bound root supplied for {parsed['root']!r}") from exc
    try:
        resolved, relative = _resolve_bound_file(Path(parsed["path"]), root)
    except ProvenanceError as exc:
        raise ManifestVerificationError(str(exc)) from exc
    if relative != parsed["path"]:
        raise ManifestVerificationError(f"file path changed after resolution: {parsed['path']}")
    actual_size = resolved.stat().st_size
    if actual_size != parsed["size_bytes"]:
        raise ManifestVerificationError(
            f"size mismatch for {parsed['path']}: {actual_size} != {parsed['size_bytes']}"
        )
    actual_hash = sha256_file(resolved)
    if actual_hash != parsed["sha256"]:
        raise ManifestVerificationError(f"hash mismatch for {parsed['path']}")
    return resolved


def _signature_record(payload_bytes: bytes, signer: Signer | None) -> dict[str, Any]:
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()
    if signer is None:
        return {
            "reason": "no signature callback supplied",
            "signed_content_sha256": payload_hash,
            "status": "unsigned",
        }
    details = signer(payload_bytes)
    if isinstance(details, str):
        details = {"value": details}
    if not isinstance(details, Mapping) or not details:
        raise ProvenanceError("signature callback must return a non-empty mapping or string")
    detached = _json_copy(details)
    if "status" in detached or "signed_content_sha256" in detached:
        raise ProvenanceError("signature details may not override reserved fields")
    return {
        "details": detached,
        "signed_content_sha256": payload_hash,
        "status": "signed",
    }


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Hash the whole manifest except its self-referential hash field."""

    body = _json_copy(manifest)
    if type(body) is not dict:
        raise ProvenanceError("manifest must be a native JSON object")
    body.pop("manifest_sha256", None)
    return canonical_sha256(body)


def build_stage_manifest(
    *,
    stage: str,
    sequence: int,
    protocol: Mapping[str, Any],
    source: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    config: Mapping[str, Any],
    inputs: Iterable[ImmutableFileRecord | Mapping[str, Any]],
    outputs: Iterable[ImmutableFileRecord | Mapping[str, Any]],
    argv: Sequence[str],
    seeds: Mapping[str, Any] | Sequence[Any],
    status: str,
    failure_reason: str | None,
    prior_manifest_sha256: str | None,
    started_at: str,
    ended_at: str,
    exit_status: int,
    signer: Signer | None = None,
) -> dict[str, Any]:
    """Build a deterministic stage manifest that binds every caller-supplied input."""

    if type(stage) is not str or not stage:
        raise ProvenanceError("stage must be a non-empty string")
    if type(sequence) is not int or sequence < 0:
        raise ProvenanceError("sequence must be a non-negative integer")
    if not protocol or not source:
        raise ProvenanceError("protocol and source identities must be non-empty")
    if type(config) is not dict:
        raise ProvenanceError("config must be a native JSON object")
    if isinstance(argv, str) or not argv or any(type(argument) is not str for argument in argv):
        raise ProvenanceError("argv must be a non-empty sequence of strings")
    if type(started_at) is not str or type(ended_at) is not str or not started_at or not ended_at:
        raise ProvenanceError("stage start and end times are required")
    if type(exit_status) is not int:
        raise ProvenanceError("exit_status must be an integer")
    if type(status) is not str:
        raise ProvenanceError("status must be a string")
    normal_status = status.lower()
    if normal_status not in _SUCCESS_STATUSES | _FAILURE_STATUSES:
        raise ProvenanceError(f"unsupported stage status: {status!r}")
    if normal_status in _FAILURE_STATUSES and (
        type(failure_reason) is not str or not failure_reason
    ):
        raise ProvenanceError("failed or stopped stages require a failure reason")
    if normal_status in _SUCCESS_STATUSES and failure_reason is not None:
        raise ProvenanceError("successful stages may not carry a failure reason")
    if prior_manifest_sha256 is not None:
        prior_manifest_sha256 = _normalise_hash(
            prior_manifest_sha256,
            field_name="prior_manifest_sha256",
        )

    payload = {
        "argv": list(argv),
        "config": _json_copy(config),
        "dependencies": _json_copy(dependencies),
        "ended_at": ended_at,
        "exit_status": exit_status,
        "failure_reason": failure_reason,
        "inputs": [_coerce_record(record) for record in inputs],
        "outputs": [_coerce_record(record) for record in outputs],
        "prior_manifest_sha256": prior_manifest_sha256,
        "protocol": _json_copy(protocol),
        "schema_version": SCHEMA_VERSION,
        "seeds": _json_copy(seeds),
        "sequence": sequence,
        "source": _json_copy(source),
        "stage": stage,
        "started_at": started_at,
        "status": normal_status,
    }
    try:
        _validate_manifest_payload(payload)
    except ManifestVerificationError as exc:
        raise ProvenanceError(str(exc)) from exc
    payload_bytes = canonical_json_bytes(payload)
    manifest = payload | {
        "integrity": {
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "signature": _signature_record(payload_bytes, signer),
        }
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    return manifest


def _manifest_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    payload.pop("integrity", None)
    return payload


def _validate_manifest_payload(payload: Mapping[str, Any]) -> None:
    if type(payload) is not dict:
        raise ManifestVerificationError("manifest payload must be a native JSON object")
    fields = set(payload)
    if fields != _PAYLOAD_FIELDS:
        missing = sorted(_PAYLOAD_FIELDS - fields)
        unexpected = sorted(fields - _PAYLOAD_FIELDS)
        raise ManifestVerificationError(
            f"manifest payload schema mismatch; missing={missing}, unexpected={unexpected}"
        )
    schema_version = payload["schema_version"]
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise ManifestVerificationError("unsupported manifest schema version")
    if type(payload["stage"]) is not str or not payload["stage"]:
        raise ManifestVerificationError("manifest stage is invalid")
    sequence = payload["sequence"]
    if type(sequence) is not int or sequence < 0:
        raise ManifestVerificationError("manifest sequence is invalid")
    if type(payload["protocol"]) is not dict or not payload["protocol"]:
        raise ManifestVerificationError("manifest protocol identity is missing")
    if type(payload["source"]) is not dict or not payload["source"]:
        raise ManifestVerificationError("manifest source identity is missing")
    if type(payload["dependencies"]) not in {list, dict}:
        raise ManifestVerificationError("manifest dependencies must be a list or mapping")
    if type(payload["config"]) is not dict:
        raise ManifestVerificationError("manifest config must be a mapping")
    if type(payload["seeds"]) not in {list, dict}:
        raise ManifestVerificationError("manifest seeds must be a list or mapping")
    if (
        type(payload["argv"]) is not list
        or not payload["argv"]
        or any(type(argument) is not str for argument in payload["argv"])
    ):
        raise ManifestVerificationError("manifest argv must be a non-empty string list")
    if type(payload["started_at"]) is not str or not payload["started_at"]:
        raise ManifestVerificationError("manifest start time is missing")
    if type(payload["ended_at"]) is not str or not payload["ended_at"]:
        raise ManifestVerificationError("manifest end time is missing")
    if type(payload["exit_status"]) is not int:
        raise ManifestVerificationError("manifest exit status must be an integer")
    status = payload["status"]
    if type(status) is not str or status not in _SUCCESS_STATUSES | _FAILURE_STATUSES:
        raise ManifestVerificationError("manifest status is invalid")
    failure_reason = payload["failure_reason"]
    if status in _FAILURE_STATUSES and (type(failure_reason) is not str or not failure_reason):
        raise ManifestVerificationError("failed manifest lacks a failure reason")
    if status in _SUCCESS_STATUSES and failure_reason is not None:
        raise ManifestVerificationError("successful manifest carries a failure reason")
    prior = payload["prior_manifest_sha256"]
    if prior is not None and (type(prior) is not str or not _SHA256.fullmatch(prior)):
        raise ManifestVerificationError("prior manifest hash is invalid")
    for group_name in ("inputs", "outputs"):
        records = payload[group_name]
        if type(records) is not list:
            raise ManifestVerificationError(f"manifest {group_name} must be a list")
        try:
            for record in records:
                _coerce_record(record)
        except ProvenanceError as exc:
            raise ManifestVerificationError(str(exc)) from exc


def verify_stage_manifest(
    manifest: Mapping[str, Any],
    *,
    bound_roots: Mapping[str, str | os.PathLike[str]] | None,
    signature_verifier: SignatureVerifier | None = None,
    require_signature: bool = False,
    rehash_files: bool = True,
) -> dict[str, Any]:
    """Verify one manifest's hashes, signature label, schema, and bound files."""

    try:
        detached = _json_copy(manifest)
    except ProvenanceError as exc:
        raise ManifestVerificationError(str(exc)) from exc
    if type(detached) is not dict:
        raise ManifestVerificationError("manifest must be a native JSON object")
    schema_version = detached.get("schema_version")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise ManifestVerificationError("unsupported manifest schema version")
    expected_manifest_hash = detached.get("manifest_sha256")
    if type(expected_manifest_hash) is not str or not _SHA256.fullmatch(expected_manifest_hash):
        raise ManifestVerificationError("manifest_sha256 is missing or invalid")
    if manifest_sha256(detached) != expected_manifest_hash:
        raise ManifestVerificationError("manifest self-hash mismatch")

    integrity = detached.get("integrity")
    if type(integrity) is not dict:
        raise ManifestVerificationError("manifest integrity block is missing")
    payload = _manifest_payload(detached)
    _validate_manifest_payload(payload)
    payload_bytes = canonical_json_bytes(payload)
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()
    if integrity.get("payload_sha256") != payload_hash:
        raise ManifestVerificationError("manifest payload hash mismatch")

    signature = integrity.get("signature")
    if type(signature) is not dict:
        raise ManifestVerificationError("manifest signature label is missing")
    if signature.get("signed_content_sha256") != payload_hash:
        raise ManifestVerificationError("signature content hash mismatch")
    signature_status = signature.get("status")
    if signature_status == "unsigned":
        if require_signature:
            raise ManifestVerificationError("manifest is explicitly unsigned")
    elif signature_status == "signed":
        details = signature.get("details")
        if type(details) is not dict:
            raise ManifestVerificationError("signed manifest lacks signature details")
        if signature_verifier is None:
            raise ManifestVerificationError("signed manifest requires a signature verifier")
        verification_result = signature_verifier(payload_bytes, details)
        if verification_result is not True:
            raise ManifestVerificationError("signature verification failed")
    else:
        raise ManifestVerificationError("unknown signature status")

    if rehash_files:
        if bound_roots is None and (detached.get("inputs") or detached.get("outputs")):
            raise ManifestVerificationError("bound roots are required to rehash manifest files")
        roots = bound_roots or {}
        for group_name in ("inputs", "outputs"):
            records = detached.get(group_name)
            if type(records) is not list:
                raise ManifestVerificationError(f"manifest {group_name} must be a list")
            for record in records:
                verify_file_record(record, bound_roots=roots)
    return detached


def write_manifest_exclusive(path: str | os.PathLike[str], manifest: Mapping[str, Any]) -> Path:
    """Create once with ``O_EXCL`` on a caller-trusted, non-hostile filesystem.

    ``O_EXCL`` refuses an existing final pathname, but is not OS confinement and cannot by
    itself defeat malicious directory replacement, privileged writers, or namespace races.
    """

    final_path = Path(path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        json.dumps(
            _json_copy(manifest),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(final_path, flags, 0o600)
    except FileExistsError as exc:
        raise ManifestExistsError(f"manifest already exists: {final_path}") from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            final_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return final_path


def manifest_filename(sequence: int) -> str:
    if type(sequence) is not int or sequence < 0:
        raise ProvenanceError("sequence must be a non-negative integer")
    return f"{sequence:06d}{MANIFEST_SUFFIX}"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _manifest_path_sequence(path: Path) -> int:
    match = _MANIFEST_NAME.fullmatch(path.name)
    if match is None:
        raise ManifestVerificationError(f"invalid manifest filename: {path.name}")
    sequence = int(match.group(1))
    if path.name != manifest_filename(sequence):
        raise ManifestVerificationError(f"non-canonical manifest filename: {path.name}")
    return sequence


def load_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ManifestVerificationError(f"manifest path is not a regular nonsymlink file: {path}")
    try:
        value = json.loads(
            candidate.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, ValueError) as exc:
        raise ManifestVerificationError(f"cannot load manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestVerificationError(f"manifest is not a JSON object: {path}")
    return value


def append_stage_manifest(
    directory: str | os.PathLike[str],
    manifest: Mapping[str, Any],
    *,
    bound_roots: Mapping[str, str | os.PathLike[str]],
    signature_verifier: SignatureVerifier | None = None,
    require_signatures: bool = False,
) -> Path:
    """Rehash all bindings, then append to a sequence-named append-only directory."""

    detached = verify_stage_manifest(
        manifest,
        bound_roots=bound_roots,
        signature_verifier=signature_verifier,
        require_signature=require_signatures,
    )
    chain_dir = Path(directory)
    chain_dir.mkdir(parents=True, exist_ok=True)
    existing = _chain_paths(chain_dir)
    if existing:
        verified_existing: list[dict[str, Any]] = []
        for path in existing:
            current = verify_stage_manifest(
                load_manifest(path),
                bound_roots=bound_roots,
                signature_verifier=signature_verifier,
                require_signature=require_signatures,
            )
            if _manifest_path_sequence(path) != current["sequence"]:
                raise ManifestVerificationError(
                    f"manifest filename does not match its sequence: {path}"
                )
            if verified_existing:
                previous = verified_existing[-1]
                if current["sequence"] != previous["sequence"] + 1:
                    raise ManifestVerificationError(
                        "existing manifest chain is out of order or has a gap"
                    )
                if current["prior_manifest_sha256"] != previous["manifest_sha256"]:
                    raise ManifestVerificationError("existing manifest chain link is invalid")
            elif current["sequence"] != 0:
                raise ManifestVerificationError("existing chain must begin at sequence zero")
            elif current["prior_manifest_sha256"] is not None:
                raise ManifestVerificationError("existing chain begins with a prior link")
            verified_existing.append(current)
        previous = verified_existing[-1]
        if detached["sequence"] != previous["sequence"] + 1:
            raise ManifestVerificationError("new manifest sequence is not the next chain position")
        if detached.get("prior_manifest_sha256") != previous["manifest_sha256"]:
            raise ManifestVerificationError("new manifest does not link to the current chain tip")
    elif detached["sequence"] != 0:
        raise ManifestVerificationError("the first manifest in a chain must have sequence zero")
    elif detached.get("prior_manifest_sha256") is not None:
        raise ManifestVerificationError("the first manifest in a chain must not have a prior link")
    target = chain_dir / manifest_filename(detached["sequence"])
    return write_manifest_exclusive(target, detached)


def _chain_paths(
    manifests: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
) -> list[Path]:
    if isinstance(manifests, (str, os.PathLike)):
        path = Path(manifests)
        if path.is_dir():
            candidates = list(path.glob(f"*{MANIFEST_SUFFIX}"))
            return sorted(candidates, key=_manifest_path_sequence)
        return [path]
    return [Path(path) for path in manifests]


def verify_manifest_chain(
    manifests: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
    *,
    bound_roots: Mapping[str, str | os.PathLike[str]],
    signature_verifier: SignatureVerifier | None = None,
    require_signatures: bool = False,
) -> list[dict[str, Any]]:
    """Verify file bindings, signatures, strict order, and every prior-stage link."""

    directory_source = isinstance(manifests, (str, os.PathLike)) and Path(manifests).is_dir()
    paths = _chain_paths(manifests)
    if not paths:
        raise ManifestVerificationError("manifest chain is empty")
    verified: list[dict[str, Any]] = []
    for path in paths:
        current = verify_stage_manifest(
            load_manifest(path),
            bound_roots=bound_roots,
            signature_verifier=signature_verifier,
            require_signature=require_signatures,
        )
        if directory_source and path.name != manifest_filename(current["sequence"]):
            raise ManifestVerificationError(
                f"manifest filename does not match its sequence: {path.name}"
            )
        if verified:
            previous = verified[-1]
            if current["sequence"] != previous["sequence"] + 1:
                raise ManifestVerificationError("manifest sequence is out of order or has a gap")
            if current.get("prior_manifest_sha256") != previous["manifest_sha256"]:
                raise ManifestVerificationError("prior-manifest chain link mismatch")
        elif current["sequence"] != 0:
            raise ManifestVerificationError("manifest chain must begin at sequence zero")
        elif current.get("prior_manifest_sha256") is not None:
            raise ManifestVerificationError("first manifest unexpectedly has a prior link")
        verified.append(current)
    return verified


__all__ = [
    "ImmutableFileRecord",
    "ManifestExistsError",
    "ManifestVerificationError",
    "ProvenanceError",
    "append_stage_manifest",
    "build_stage_manifest",
    "canonical_json_bytes",
    "canonical_sha256",
    "immutable_file_record",
    "load_manifest",
    "manifest_filename",
    "manifest_sha256",
    "sha256_file",
    "verify_file_record",
    "verify_manifest_chain",
    "verify_stage_manifest",
    "write_manifest_exclusive",
]
