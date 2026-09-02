"""Static runtime-policy audit for the target-free M38 container context.

This module deliberately separates facts that can be established from files in a build
context from launch-time requirements that need an external container/runtime audit.  A
successful :func:`audit_runtime_context` call proves that the supplied context exactly matches
the source-audited content manifest and that its Dockerfile selects a non-root user.  It does
*not* prove that the directory remained unchanged during or after this point-in-time audit,
that a later builder consumed those exact bytes, or that an image/platform digest was produced
from them.  It also does not prove that an eventual process had a read-only root filesystem,
no network namespace, or OS confinement.  A sealed content-addressed build transaction and
launch-time properties must be independently observed and attested.

The application-level :mod:`exosat_rv.m38.firewall` remains defence in depth.  It is never
treated here as an operating-system security boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .provenance import ProvenanceError, canonical_json_bytes, canonical_sha256

RUNTIME_POLICY_SCHEMA_VERSION = 1
CONTEXT_MARKER = b"M38 dedicated target-free build context v1\n"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PINNED_IMAGE = re.compile(r"[^@\s]+@sha256:([0-9a-f]{64})\Z")
_NON_ROOT_USER = re.compile(r"([1-9][0-9]*):([1-9][0-9]*)\Z")
_APPROVED_TMPFS_MOUNTS = ("/tmp",)
_REQUIRED_CONTEXT_FILES = frozenset(
    {
        ".dockerignore",
        ".m38-target-free-context",
        "Dockerfile",
        "entrypoint.py",
        "runtime-contract.json",
    }
)
_APPROVED_CONTEXT_SHA256 = {
    ".dockerignore": "b7675ed240df7cc5362d2c17167ba6fbb15e5699f17929a0eada047692e12f39",
    ".m38-target-free-context": "1c6ececdbc94142063514808185676e29c99e299ae489126b236d39c9c568ee2",
    "Dockerfile": "486a855b13d5a8e1646cbea480df76ef59f8714e2e4c1cade485bbfbb7ddee51",
    "entrypoint.py": "bc74902b627b3aabaa352e77d803be46ce493126d711260559537700944fb633",
    "runtime-contract.json": "3f53f6eafff880b8bd90d39619c470426f5a6068995e7404b605f4d2327175e9",
}
_CONTRACT_FIELDS = frozenset(
    {
        "allowed_context_files",
        "application_firewall_is_os_confinement",
        "base_image",
        "container_user",
        "context_kind",
        "drop_all_capabilities_required",
        "network_mode_required",
        "no_new_privileges_required",
        "read_only_root_filesystem_required",
        "runtime_observation_required",
        "schema_version",
        "tmpfs_mounts",
    }
)


class RuntimePolicyError(RuntimeError):
    """Raised when a context or launch contract fails closed."""


def _strict_copy(value: Any) -> Any:
    try:
        return json.loads(canonical_json_bytes(value))
    except (ProvenanceError, ValueError) as exc:
        raise RuntimePolicyError(f"runtime policy must use strict native JSON: {exc}") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _normal_context_path(value: Any) -> str:
    if type(value) is not str or not value:
        raise RuntimePolicyError("allowed context paths must be non-empty native strings")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise RuntimePolicyError(f"context path is not normalised and relative: {value!r}")
    return value


def _is_junction(path: Path) -> bool:
    """Return whether *path* is a Windows junction when the runtime can detect it."""

    checker = getattr(path, "is_junction", None)
    try:
        if checker is not None and checker():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(attributes & reparse_flag)
    except OSError as exc:
        raise RuntimePolicyError(f"cannot inspect build-context entry: {path}: {exc}") from exc


@dataclass(frozen=True)
class RuntimeLaunchContract:
    """Requirements for an external launcher; construction does not prove enforcement."""

    container_user: str
    read_only_root_filesystem: bool
    network_mode: str
    drop_all_capabilities: bool
    no_new_privileges: bool
    tmpfs_mounts: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.container_user) is not str or not _NON_ROOT_USER.fullmatch(
            self.container_user
        ):
            raise RuntimePolicyError("container_user must be an explicit non-zero numeric UID:GID")
        if self.read_only_root_filesystem is not True:
            raise RuntimePolicyError("the root filesystem must be required read-only")
        if type(self.network_mode) is not str or self.network_mode != "none":
            raise RuntimePolicyError("the runtime network mode must be exactly 'none'")
        if self.drop_all_capabilities is not True:
            raise RuntimePolicyError("all Linux capabilities must be dropped")
        if self.no_new_privileges is not True:
            raise RuntimePolicyError("no-new-privileges must be required")
        if type(self.tmpfs_mounts) is not tuple:
            raise RuntimePolicyError("tmpfs_mounts must be an immutable tuple")
        if self.tmpfs_mounts != _APPROVED_TMPFS_MOUNTS:
            raise RuntimePolicyError("tmpfs_mounts must be exactly the approved /tmp mount")

    def as_dict(self) -> dict[str, Any]:
        return {
            "container_user": self.container_user,
            "drop_all_capabilities": self.drop_all_capabilities,
            "network_mode": self.network_mode,
            "no_new_privileges": self.no_new_privileges,
            "read_only_root_filesystem": self.read_only_root_filesystem,
            "tmpfs_mounts": list(self.tmpfs_mounts),
        }

    def docker_run_arguments(self) -> tuple[str, ...]:
        """Return security arguments; callers still must audit the launched container."""

        arguments = [
            "--network=none",
            "--read-only",
            f"--user={self.container_user}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
        ]
        arguments.extend(
            f"--tmpfs={mount}:rw,noexec,nosuid,nodev,size=64m" for mount in self.tmpfs_mounts
        )
        return tuple(arguments)


@dataclass(frozen=True)
class RuntimeContextAudit:
    """Content-bound result of a static, target-free build-context audit."""

    context_sha256: str
    file_records: tuple[tuple[str, int, str], ...]
    launch_contract: RuntimeLaunchContract
    dockerfile_non_root_user_proven: bool
    dedicated_allowlist_context_proven: bool

    def __post_init__(self) -> None:
        if type(self.context_sha256) is not str or not _SHA256.fullmatch(self.context_sha256):
            raise RuntimePolicyError("context_sha256 must be a lowercase SHA-256 digest")
        if type(self.file_records) is not tuple or not self.file_records:
            raise RuntimePolicyError("file_records must be a non-empty immutable tuple")
        previous_path: str | None = None
        serialised: list[dict[str, Any]] = []
        for record in self.file_records:
            if type(record) is not tuple or len(record) != 3:
                raise RuntimePolicyError("each file record must be a three-item native tuple")
            path, size, digest = record
            _normal_context_path(path)
            if previous_path is not None and path <= previous_path:
                raise RuntimePolicyError("file records must be strictly path-sorted")
            if type(size) is not int or size < 0:
                raise RuntimePolicyError("file-record size must be a non-negative native integer")
            if type(digest) is not str or not _SHA256.fullmatch(digest):
                raise RuntimePolicyError("file-record digest must be a lowercase SHA-256")
            serialised.append({"path": path, "sha256": digest, "size_bytes": size})
            previous_path = path
        if canonical_sha256(serialised) != self.context_sha256:
            raise RuntimePolicyError("context_sha256 does not bind the file records")
        if type(self.launch_contract) is not RuntimeLaunchContract:
            raise RuntimePolicyError("launch_contract must be a RuntimeLaunchContract")
        if self.dockerfile_non_root_user_proven is not True:
            raise RuntimePolicyError("a successful audit must prove a non-root Dockerfile user")
        if self.dedicated_allowlist_context_proven is not True:
            raise RuntimePolicyError("a successful audit must prove a dedicated allowlist context")

    def as_dict(self) -> dict[str, Any]:
        return {
            "application_firewall_is_os_confinement": False,
            "context_sha256": self.context_sha256,
            "file_records": [
                {"path": path, "sha256": digest, "size_bytes": size}
                for path, size, digest in self.file_records
            ],
            "launch_contract": self.launch_contract.as_dict(),
            "not_proven_by_static_audit": [
                "audit-to-build and image-digest linkage",
                "build-context stability during or after the point-in-time audit",
                "launch-time read-only-root enforcement",
                "launch-time network isolation",
                "operating-system confinement",
                "observer blindness",
            ],
            "proven": {
                "dedicated_allowlist_context": self.dedicated_allowlist_context_proven,
                "dockerfile_non_root_user": self.dockerfile_non_root_user_proven,
            },
            "schema_version": RUNTIME_POLICY_SCHEMA_VERSION,
        }

    @property
    def audit_sha256(self) -> str:
        return canonical_sha256(self.as_dict())


def load_runtime_contract(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load a duplicate-key-safe strict JSON runtime contract."""

    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimePolicyError("runtime contract must be a regular nonsymlink file")
    try:
        value = json.loads(
            candidate.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise RuntimePolicyError(f"cannot load runtime contract: {exc}") from exc
    detached = _strict_copy(value)
    if type(detached) is not dict:
        raise RuntimePolicyError("runtime contract must be a native JSON object")
    fields = set(detached)
    if fields != _CONTRACT_FIELDS:
        raise RuntimePolicyError(
            "runtime contract schema mismatch; "
            f"missing={sorted(_CONTRACT_FIELDS - fields)}, "
            f"unexpected={sorted(fields - _CONTRACT_FIELDS)}"
        )
    if (
        detached["schema_version"] != RUNTIME_POLICY_SCHEMA_VERSION
        or type(detached["schema_version"]) is not int
    ):
        raise RuntimePolicyError("unsupported runtime contract schema version")
    if (
        detached["context_kind"] != "dedicated-target-free-allowlist"
        or type(detached["context_kind"]) is not str
    ):
        raise RuntimePolicyError("context_kind must declare a dedicated target-free allowlist")
    if detached["application_firewall_is_os_confinement"] is not False:
        raise RuntimePolicyError("the application firewall must not be claimed as OS confinement")
    if detached["runtime_observation_required"] is not True:
        raise RuntimePolicyError("launch-time runtime observation must be required")
    base_image = detached["base_image"]
    if type(base_image) is not str or not _PINNED_IMAGE.fullmatch(base_image):
        raise RuntimePolicyError("base_image must be pinned by a lowercase SHA-256 digest")
    return detached


def _audit_dockerfile(dockerfile: str, *, base_image: str, container_user: str) -> None:
    physical_lines = dockerfile.replace("\r\n", "\n").splitlines()
    parser_directives = [
        line.strip()
        for line in physical_lines
        if line.lstrip().lower().startswith(("# syntax=", "# escape="))
    ]
    if parser_directives:
        raise RuntimePolicyError("Dockerfile parser directives are forbidden in the frozen context")
    logical_lines = [
        line.strip()
        for line in physical_lines
        if line.strip() and not line.lstrip().startswith("#")
    ]
    from_lines = [
        line.split(maxsplit=1)[1] for line in logical_lines if line.upper().startswith("FROM ")
    ]
    if from_lines != [base_image]:
        raise RuntimePolicyError("Dockerfile must use exactly the contract-pinned base image")
    user_lines = [
        line.split(maxsplit=1)[1] for line in logical_lines if line.upper().startswith("USER ")
    ]
    if user_lines != [container_user]:
        raise RuntimePolicyError("Dockerfile must select the contracted non-root user exactly once")
    allowed_directives = {"COPY", "ENTRYPOINT", "FROM", "USER"}
    directives = [line.split(maxsplit=1)[0].upper() for line in logical_lines]
    if any(directive not in allowed_directives for directive in directives):
        raise RuntimePolicyError("target-free Dockerfile contains a forbidden directive")
    copy_lines = {line for line in logical_lines if line.upper().startswith("COPY ")}
    expected_copy_lines = {
        f"COPY --chown={container_user} entrypoint.py /opt/m38/entrypoint.py",
        f"COPY --chown={container_user} runtime-contract.json /opt/m38/runtime-contract.json",
    }
    if copy_lines != expected_copy_lines or len(copy_lines) != 2:
        raise RuntimePolicyError(
            "Dockerfile COPY sources must be the two allowlisted runtime files"
        )
    entrypoints = [line for line in logical_lines if line.upper().startswith("ENTRYPOINT ")]
    if entrypoints != ['ENTRYPOINT ["python", "-I", "/opt/m38/entrypoint.py"]']:
        raise RuntimePolicyError("Dockerfile entrypoint must be the target-free bootstrap")


def _audit_dockerignore(content: str, allowed_files: tuple[str, ...]) -> None:
    lines = [line.strip() for line in content.replace("\r\n", "\n").splitlines() if line.strip()]
    if not lines or lines[0] != "*":
        raise RuntimePolicyError(".dockerignore must deny the context by default")
    expected = {f"!{path}" for path in allowed_files}
    if set(lines[1:]) != expected or len(lines[1:]) != len(expected):
        raise RuntimePolicyError(
            ".dockerignore exceptions must exactly match the context allowlist"
        )


def audit_runtime_context(context_root: str | os.PathLike[str]) -> RuntimeContextAudit:
    """Prove exact static context membership and return launch requirements.

    The caller must pass the dedicated ``containers/m38`` directory itself.  Passing a
    repository root fails because every additional file is outside the contract allowlist.
    """

    supplied = Path(context_root)
    if supplied.is_symlink() or _is_junction(supplied):
        raise RuntimePolicyError("build context root may not be a symlink or junction")
    try:
        root = supplied.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimePolicyError(f"cannot resolve build context: {exc}") from exc
    if not root.is_dir():
        raise RuntimePolicyError("build context must be a directory")

    marker = root / ".m38-target-free-context"
    if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != CONTEXT_MARKER:
        raise RuntimePolicyError("dedicated target-free context marker is missing or invalid")

    contract = load_runtime_contract(root / "runtime-contract.json")
    raw_allowed = contract["allowed_context_files"]
    if type(raw_allowed) is not list:
        raise RuntimePolicyError("allowed_context_files must be a native JSON list")
    allowed = tuple(_normal_context_path(value) for value in raw_allowed)
    if tuple(sorted(allowed)) != allowed or len(set(allowed)) != len(allowed):
        raise RuntimePolicyError("allowed_context_files must be sorted and unique")
    if set(allowed) != _REQUIRED_CONTEXT_FILES:
        raise RuntimePolicyError("runtime context allowlist does not match the minimal context")

    actual: list[str] = []
    for path in root.iterdir():
        if path.is_symlink() or _is_junction(path):
            raise RuntimePolicyError(
                f"symlinks and junctions are forbidden in the build context: {path}"
            )
        if path.is_dir():
            raise RuntimePolicyError(
                f"descendant directories are forbidden in the flat build context: {path}"
            )
        if not path.is_file():
            raise RuntimePolicyError(f"non-regular context entry is forbidden: {path}")
        actual.append(path.name)
    if tuple(sorted(actual)) != allowed:
        raise RuntimePolicyError(
            f"build context differs from allowlist; expected={list(allowed)}, actual={sorted(actual)}"
        )

    launch = RuntimeLaunchContract(
        container_user=contract["container_user"],
        read_only_root_filesystem=contract["read_only_root_filesystem_required"],
        network_mode=contract["network_mode_required"],
        drop_all_capabilities=contract["drop_all_capabilities_required"],
        no_new_privileges=contract["no_new_privileges_required"],
        tmpfs_mounts=tuple(contract["tmpfs_mounts"])
        if type(contract["tmpfs_mounts"]) is list
        else contract["tmpfs_mounts"],
    )
    _audit_dockerfile(
        (root / "Dockerfile").read_text(encoding="utf-8"),
        base_image=contract["base_image"],
        container_user=launch.container_user,
    )
    _audit_dockerignore((root / ".dockerignore").read_text(encoding="utf-8"), allowed)

    records: list[tuple[str, int, str]] = []
    for relative in allowed:
        content = (root / relative).read_bytes()
        records.append((relative, len(content), hashlib.sha256(content).hexdigest()))
    observed_digests = {path: digest for path, _size, digest in records}
    if observed_digests != _APPROVED_CONTEXT_SHA256:
        raise RuntimePolicyError(
            "build context content differs from the source-audited frozen manifest"
        )
    context_hash = canonical_sha256(
        [{"path": path, "sha256": digest, "size_bytes": size} for path, size, digest in records]
    )
    return RuntimeContextAudit(
        context_sha256=context_hash,
        file_records=tuple(records),
        launch_contract=launch,
        dockerfile_non_root_user_proven=True,
        dedicated_allowlist_context_proven=True,
    )


__all__ = [
    "CONTEXT_MARKER",
    "RUNTIME_POLICY_SCHEMA_VERSION",
    "RuntimeContextAudit",
    "RuntimeLaunchContract",
    "RuntimePolicyError",
    "audit_runtime_context",
    "load_runtime_contract",
]
