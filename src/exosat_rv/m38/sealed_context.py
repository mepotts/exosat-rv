"""Canonical build-context bytes for target-free M38 runtime experiments.

The existing :mod:`exosat_rv.m38.runtime_policy` audit binds the five files in the
dedicated probe directory, but a later directory-based Docker build could observe
different bytes.  This module closes that local hand-off gap by constructing one
canonical tar stream, hashing that exact stream, and placing the same immutable bytes
in a build request.

This is engineering evidence, not an external trust boundary.  In particular it does
not prove that a Docker daemon consumed the bytes, avoided registry access, produced a
particular image, or resisted a hostile host.  Those facts require separately captured
builder and runtime attestations.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .provenance import ProvenanceError, canonical_json_bytes, canonical_sha256
from .runtime_policy import (
    RuntimeContextAudit,
    RuntimePolicyError,
    audit_runtime_context,
    load_runtime_contract,
)

SEALED_CONTEXT_SCHEMA_VERSION = 1
SEALED_CONTEXT_PLATFORM = "linux/amd64"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PINNED_IMAGE = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}\Z")
_CANONICAL_MODE = 0o644
_CANONICAL_UID = 0
_CANONICAL_GID = 0
_READ_CHUNK_BYTES = 1024 * 1024
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


class SealedContextError(RuntimeError):
    """Raised when audited source files cannot produce one canonical tar stream."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _strict_json_object(payload: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(payload, object_pairs_hook=_unique_object)
        detached = json.loads(canonical_json_bytes(value))
    except (UnicodeError, ValueError, ProvenanceError) as exc:
        raise SealedContextError(f"{label} is not strict JSON: {exc}") from exc
    if type(detached) is not dict:
        raise SealedContextError(f"{label} must be a native JSON object")
    return detached


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _native_object(value: object, *, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise SealedContextError(f"{label} must be a native JSON object")
    return value


def _reported_sha256(value: object, *, label: str) -> str:
    digest = _native_object(value, label=label).get("sha256")
    if type(digest) is not str or not _SHA256.fullmatch(digest):
        raise SealedContextError(f"{label} must report one lowercase SHA-256 digest")
    return digest


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return fields that must remain stable throughout one source-file read."""

    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
    )


def _read_stable_regular_file(path: Path) -> bytes:
    """Read a nonsymlink regular file and reject identity or metadata drift."""

    try:
        before = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(before.st_mode):
            raise SealedContextError(f"sealed context entry is not a regular nonsymlink: {path}")
        chunks: list[bytes] = []
        with path.open("rb", buffering=0) as handle:
            opened_before = os.fstat(handle.fileno())
            while True:
                chunk = handle.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                chunks.append(chunk)
            opened_after = os.fstat(handle.fileno())
        after = path.lstat()
    except SealedContextError:
        raise
    except OSError as exc:
        raise SealedContextError(f"cannot read sealed context entry {path}: {exc}") from exc

    identities = {
        _stat_identity(before),
        _stat_identity(opened_before),
        _stat_identity(opened_after),
        _stat_identity(after),
    }
    if len(identities) != 1:
        raise SealedContextError(f"context entry changed while it was being sealed: {path}")
    # Windows may report a handle-specific ctime value that differs from path stat even
    # when the file is unchanged.  Compare ctime only within each observation method.
    if (
        before.st_ctime_ns != after.st_ctime_ns
        or opened_before.st_ctime_ns != opened_after.st_ctime_ns
    ):
        raise SealedContextError(
            f"context entry metadata changed while it was being sealed: {path}"
        )
    payload = b"".join(chunks)
    if len(payload) != before.st_size:
        raise SealedContextError(f"context entry size changed while it was being sealed: {path}")
    return payload


def _validate_archive_names(paths: tuple[str, ...]) -> None:
    if type(paths) is not tuple or not paths:
        raise SealedContextError("archive paths must be a non-empty native tuple")
    collision_keys: set[str] = set()
    previous: str | None = None
    for path in paths:
        if type(path) is not str or not path or "\x00" in path:
            raise SealedContextError("archive paths must be non-empty native strings")
        if path.startswith("/") or "\\" in path or path in {".", ".."}:
            raise SealedContextError(f"archive path is not canonical POSIX-relative: {path!r}")
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise SealedContextError(f"archive path is not canonical POSIX-relative: {path!r}")
        if unicodedata.normalize("NFC", path) != path:
            raise SealedContextError(f"archive path is not NFC-normalised: {path!r}")
        collision_key = unicodedata.normalize("NFC", path).casefold()
        if collision_key in collision_keys:
            raise SealedContextError(f"case/Unicode-colliding archive path: {path!r}")
        collision_keys.add(collision_key)
        if previous is not None and path <= previous:
            raise SealedContextError("archive paths must be strictly bytewise sorted")
        previous = path


def _canonical_tar(entries: tuple[tuple[str, bytes], ...]) -> bytes:
    paths = tuple(path for path, _payload in entries)
    _validate_archive_names(paths)
    stream = io.BytesIO()
    with tarfile.open(
        fileobj=stream,
        mode="w",
        format=tarfile.USTAR_FORMAT,
        encoding="utf-8",
        errors="strict",
    ) as archive:
        for path, payload in entries:
            if type(payload) is not bytes:
                raise SealedContextError("canonical archive payloads must be exact bytes")
            info = tarfile.TarInfo(path)
            info.size = len(payload)
            info.mode = _CANONICAL_MODE
            info.uid = _CANONICAL_UID
            info.gid = _CANONICAL_GID
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            info.type = tarfile.REGTYPE
            info.pax_headers = {}
            archive.addfile(info, io.BytesIO(payload))
    return stream.getvalue()


def _archive_entries(payload: bytes) -> tuple[tuple[str, bytes], ...]:
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
            entries: list[tuple[str, bytes]] = []
            for member in members:
                if not member.isfile() or member.type != tarfile.REGTYPE:
                    raise SealedContextError("canonical context tar may contain only regular files")
                if (
                    member.mode != _CANONICAL_MODE
                    or member.uid != _CANONICAL_UID
                    or member.gid != _CANONICAL_GID
                    or member.uname != ""
                    or member.gname != ""
                    or member.mtime != 0
                    or member.pax_headers
                ):
                    raise SealedContextError("canonical context tar contains noncanonical metadata")
                handle = archive.extractfile(member)
                if handle is None:
                    raise SealedContextError("canonical context tar member has no payload")
                content = handle.read()
                if len(content) != member.size:
                    raise SealedContextError("canonical context tar member size is inconsistent")
                entries.append((member.name, content))
    except SealedContextError:
        raise
    except (OSError, tarfile.TarError, UnicodeError) as exc:
        raise SealedContextError(f"cannot parse canonical context tar: {exc}") from exc
    return tuple(entries)


@dataclass(frozen=True, slots=True)
class SealedRuntimeContext:
    """Exact canonical tar bytes bound to the successful static runtime audit."""

    audit: RuntimeContextAudit
    base_image: str
    tar_bytes: bytes = field(repr=False)
    platform: str = SEALED_CONTEXT_PLATFORM
    tar_sha256: str = field(init=False)
    tar_size_bytes: int = field(init=False)

    def __post_init__(self) -> None:
        if type(self.audit) is not RuntimeContextAudit:
            raise SealedContextError("audit must be an exact RuntimeContextAudit")
        if type(self.base_image) is not str or not _PINNED_IMAGE.fullmatch(self.base_image):
            raise SealedContextError("base_image must be pinned by a lowercase SHA-256")
        if type(self.tar_bytes) is not bytes:
            raise SealedContextError("tar_bytes must be exact immutable bytes")
        if type(self.platform) is not str or self.platform != SEALED_CONTEXT_PLATFORM:
            raise SealedContextError(f"platform must be exactly {SEALED_CONTEXT_PLATFORM!r}")

        entries = _archive_entries(self.tar_bytes)
        if _canonical_tar(entries) != self.tar_bytes:
            raise SealedContextError("tar_bytes are not the exact canonical USTAR encoding")
        records = tuple((path, len(content), _sha256(content)) for path, content in entries)
        if records != self.audit.file_records:
            raise SealedContextError("canonical tar members do not match the static audit")
        entry_payloads = dict(entries)
        contract_payload = entry_payloads.get("runtime-contract.json")
        if contract_payload is None:
            raise SealedContextError("canonical tar does not contain the runtime contract")
        contract = _strict_json_object(contract_payload, label="embedded runtime contract")
        embedded_base_image = contract.get("base_image")
        if (
            type(embedded_base_image) is not str
            or not _PINNED_IMAGE.fullmatch(embedded_base_image)
            or self.base_image != embedded_base_image
        ):
            raise SealedContextError("base_image does not match the canonical tar runtime contract")
        object.__setattr__(self, "tar_sha256", _sha256(self.tar_bytes))
        object.__setattr__(self, "tar_size_bytes", len(self.tar_bytes))

    def as_dict(self) -> dict[str, object]:
        return {
            "audit_sha256": self.audit.audit_sha256,
            "base_image": self.base_image,
            "context_sha256": self.audit.context_sha256,
            "file_records": [
                {"path": path, "sha256": digest, "size_bytes": size}
                for path, size, digest in self.audit.file_records
            ],
            "not_proven": [
                "builder consumed the supplied stdin bytes",
                "registry egress was disabled",
                "base image was already local",
                "image identity or runtime enforcement",
                "external attestation or observer blindness",
            ],
            "platform": self.platform,
            "schema_version": SEALED_CONTEXT_SCHEMA_VERSION,
            "tar_sha256": self.tar_sha256,
            "tar_size_bytes": self.tar_size_bytes,
        }

    @property
    def seal_sha256(self) -> str:
        return canonical_sha256(self.as_dict())


@dataclass(frozen=True, slots=True)
class DockerBuildRequest:
    """Fixed Docker invocation paired with the exact sealed stdin bytes.

    Constructing this request performs no build.  ``--network=none`` applies to
    Dockerfile ``RUN`` instructions, and ``--pull=false`` disables pull-always; neither
    option proves that the builder made no registry connection.
    """

    sealed_context: SealedRuntimeContext
    iid_file: str
    metadata_file: str

    def __post_init__(self) -> None:
        if type(self.sealed_context) is not SealedRuntimeContext:
            raise SealedContextError("sealed_context must be an exact SealedRuntimeContext")
        for label, value in (("iid_file", self.iid_file), ("metadata_file", self.metadata_file)):
            if type(value) is not str or not value or "\x00" in value:
                raise SealedContextError(f"{label} must be a non-empty native path string")
            if not Path(value).is_absolute():
                raise SealedContextError(f"{label} must be absolute")
        if os.path.normcase(os.path.abspath(self.iid_file)) == os.path.normcase(
            os.path.abspath(self.metadata_file)
        ):
            raise SealedContextError("iid_file and metadata_file must be distinct")

    @property
    def arguments(self) -> tuple[str, ...]:
        return (
            "docker",
            "buildx",
            "build",
            f"--platform={self.sealed_context.platform}",
            "--network=none",
            "--pull=false",
            "--progress=plain",
            "--load",
            "--iidfile",
            self.iid_file,
            "--metadata-file",
            self.metadata_file,
            "-",
        )

    @property
    def stdin_bytes(self) -> bytes:
        return self.sealed_context.tar_bytes

    def as_dict(self) -> dict[str, object]:
        return {
            "arguments": list(self.arguments),
            "audit_sha256": self.sealed_context.audit.audit_sha256,
            "base_image": self.sealed_context.base_image,
            "context_tar_sha256": self.sealed_context.tar_sha256,
            "context_tar_size_bytes": self.sealed_context.tar_size_bytes,
            "pull_always": False,
            "registry_egress_disabled_proven": False,
            "run_instruction_network_mode": "none",
            "schema_version": SEALED_CONTEXT_SCHEMA_VERSION,
            "sealed_context_sha256": self.sealed_context.seal_sha256,
        }

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self.as_dict())


@dataclass(frozen=True, slots=True)
class DockerBuildResult:
    """Locally observed result of streaming a sealed request to Docker.

    The record binds process outputs but remains unauthenticated host evidence.  It does
    not promote the builder's local image ID to a registry/OCI manifest digest.
    """

    request: DockerBuildRequest
    image_id: str
    metadata_bytes: bytes = field(repr=False)
    stdout_bytes: bytes = field(repr=False)
    stderr_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.request) is not DockerBuildRequest:
            raise SealedContextError("request must be an exact DockerBuildRequest")
        if type(self.image_id) is not str or not _IMAGE_ID.fullmatch(self.image_id):
            raise SealedContextError("image_id must be a sha256-prefixed digest")
        for label, value in (
            ("metadata_bytes", self.metadata_bytes),
            ("stdout_bytes", self.stdout_bytes),
            ("stderr_bytes", self.stderr_bytes),
        ):
            if type(value) is not bytes:
                raise SealedContextError(f"{label} must be exact immutable bytes")
        metadata = _strict_json_object(self.metadata_bytes, label="build metadata")
        identifiers = {
            value
            for value in (
                metadata.get("containerimage.config.digest"),
                metadata.get("containerimage.digest"),
                metadata.get("containerimage.descriptor", {}).get("digest")
                if type(metadata.get("containerimage.descriptor")) is dict
                else None,
            )
            if type(value) is str and _IMAGE_ID.fullmatch(value)
        }
        if self.image_id not in identifiers:
            raise SealedContextError("build metadata does not bind the IID file image identity")
        self._builder_reported_bindings(metadata)

    def _builder_reported_bindings(self, metadata: dict[str, object]) -> dict[str, object]:
        """Validate host-reported BuildKit bindings without treating them as attestation."""

        provenance = _native_object(
            metadata.get("buildx.build.provenance"),
            label="build provenance",
        )
        if provenance.get("buildType") != "https://mobyproject.org/buildkit@v1":
            raise SealedContextError("build provenance has an unexpected build type")
        invocation = _native_object(provenance.get("invocation"), label="build invocation")
        config_source = _native_object(
            invocation.get("configSource"),
            label="build config source",
        )
        context_uri = config_source.get("uri")
        if type(context_uri) is not str or not context_uri:
            raise SealedContextError("build config source must report a non-empty URI")
        if config_source.get("entryPoint") != "Dockerfile":
            raise SealedContextError("build config source did not report Dockerfile")
        context_sha256 = _reported_sha256(
            config_source.get("digest"),
            label="build config-source digest",
        )
        if context_sha256 != self.request.sealed_context.tar_sha256:
            raise SealedContextError("build provenance does not bind the sealed context tar")

        parameters = _native_object(
            invocation.get("parameters"),
            label="build invocation parameters",
        )
        parameter_args = _native_object(
            parameters.get("args"),
            label="build invocation arguments",
        )
        root = _native_object(parameters.get("root"), label="build invocation root")
        root_source = _native_object(
            root.get("configSource"),
            label="build root config source",
        )
        root_request = _native_object(
            root.get("request"),
            label="build root request",
        )
        root_request_args = _native_object(
            root_request.get("args"),
            label="build root request arguments",
        )
        if (
            parameter_args.get("force-network-mode") != "none"
            or root_request_args.get("force-network-mode") != "none"
        ):
            raise SealedContextError("build provenance does not report RUN network mode none")
        if (
            root_source.get("uri") != context_uri
            or root_source.get("path") != "Dockerfile"
            or _reported_sha256(
                root_source.get("digest"),
                label="build root config-source digest",
            )
            != context_sha256
        ):
            raise SealedContextError("build provenance reports inconsistent context roots")

        environment = _native_object(
            invocation.get("environment"),
            label="build invocation environment",
        )
        if environment.get("platform") != self.request.sealed_context.platform:
            raise SealedContextError("build provenance does not bind the requested platform")

        materials = provenance.get("materials")
        if type(materials) is not list:
            raise SealedContextError("build provenance materials must be a native JSON list")
        base_digest = self.request.sealed_context.base_image.rsplit("@sha256:", 1)[1]
        base_matches = 0
        context_matches = 0
        for material_value in materials:
            material = _native_object(material_value, label="build provenance material")
            material_uri = material.get("uri")
            material_digest = _reported_sha256(
                material.get("digest"),
                label="build provenance material digest",
            )
            if material_digest == base_digest:
                base_matches += 1
            if material_uri == context_uri and material_digest == context_sha256:
                context_matches += 1
        if base_matches != 1:
            raise SealedContextError("build provenance does not uniquely bind the base material")
        if context_matches != 1:
            raise SealedContextError("build provenance does not uniquely bind the context material")
        return {
            "base_material_sha256": base_digest,
            "context_tar_sha256": context_sha256,
            "platform": self.request.sealed_context.platform,
            "run_instruction_network_mode": "none",
        }

    @property
    def metadata(self) -> dict[str, object]:
        return _strict_json_object(self.metadata_bytes, label="build metadata")

    @property
    def builder_reported_bindings(self) -> dict[str, object]:
        """Return validated but unauthenticated bindings reported by BuildKit."""

        return self._builder_reported_bindings(self.metadata)

    def as_dict(self) -> dict[str, object]:
        return {
            "authentication": "none; local engineering observation",
            "builder_reported_bindings": self.builder_reported_bindings,
            "image_id": self.image_id,
            "limitations": [
                "Docker daemon and host are not an independent trust domain",
                "registry egress was not independently disabled or measured",
                "image-ID semantics depend on the local builder and image store",
            ],
            "metadata_sha256": _sha256(self.metadata_bytes),
            "request_sha256": self.request.request_sha256,
            "schema_version": SEALED_CONTEXT_SCHEMA_VERSION,
            "stderr_sha256": _sha256(self.stderr_bytes),
            "stdout_sha256": _sha256(self.stdout_bytes),
        }

    @property
    def result_sha256(self) -> str:
        return canonical_sha256(self.as_dict())


def _validate_fresh_output_path(value: str, label: str) -> Path:
    path = Path(value)
    try:
        if path.exists() or path.is_symlink():
            raise SealedContextError(f"{label} must not already exist")
        absolute = Path(os.path.abspath(os.fspath(path)))
        parent = absolute.parent
        resolved_parent = parent.resolve(strict=True)
        if not resolved_parent.is_dir():
            raise SealedContextError(f"{label} parent must be a regular existing directory")
        if os.path.normcase(os.fspath(parent)) != os.path.normcase(os.fspath(resolved_parent)):
            raise SealedContextError(f"{label} parent may not traverse a symlink or junction")
    except SealedContextError:
        raise
    except (OSError, RuntimeError) as exc:
        raise SealedContextError(f"cannot validate {label}: {exc}") from exc
    return absolute


def execute_docker_build(
    request: DockerBuildRequest,
    *,
    timeout_seconds: int = 300,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> DockerBuildResult:
    """Stream the sealed tar bytes to one fixed Docker build invocation.

    The caller must independently inspect the resulting image and runtime.  Output files
    are required fresh so a failed or ambiguous call cannot be mistaken for earlier
    evidence.
    """

    if type(request) is not DockerBuildRequest:
        raise SealedContextError("request must be an exact DockerBuildRequest")
    if type(timeout_seconds) is not int or timeout_seconds <= 0:
        raise SealedContextError("timeout_seconds must be a positive native integer")
    iid_path = _validate_fresh_output_path(request.iid_file, "iid_file")
    metadata_path = _validate_fresh_output_path(request.metadata_file, "metadata_file")
    try:
        completed = runner(
            request.arguments,
            input=request.stdin_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SealedContextError(
            f"Docker build invocation did not complete: {type(exc).__name__}"
        ) from exc

    returncode = getattr(completed, "returncode", None)
    stdout = getattr(completed, "stdout", None)
    stderr = getattr(completed, "stderr", None)
    if type(returncode) is not int or type(stdout) is not bytes or type(stderr) is not bytes:
        raise SealedContextError("Docker runner returned an invalid process result")
    if returncode != 0:
        raise SealedContextError(f"Docker build failed with exit code {returncode}")
    if not iid_path.is_file() or iid_path.is_symlink():
        raise SealedContextError("successful Docker build did not produce a regular IID file")
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise SealedContextError("successful Docker build did not produce a regular metadata file")

    iid_payload = _read_stable_regular_file(iid_path)
    metadata_payload = _read_stable_regular_file(metadata_path)
    try:
        image_id = iid_payload.decode("ascii")
    except UnicodeError as exc:
        raise SealedContextError("Docker IID file is not ASCII") from exc
    return DockerBuildResult(
        request=request,
        image_id=image_id,
        metadata_bytes=metadata_payload,
        stdout_bytes=stdout,
        stderr_bytes=stderr,
    )


def seal_runtime_context(context_root: str | os.PathLike[str]) -> SealedRuntimeContext:
    """Audit *context_root* and freeze its exact content into canonical USTAR bytes."""

    try:
        audit = audit_runtime_context(context_root)
        root = Path(context_root).resolve(strict=True)
        contract = load_runtime_contract(root / "runtime-contract.json")
    except RuntimePolicyError as exc:
        raise SealedContextError(f"runtime context failed static audit: {exc}") from exc
    except (OSError, RuntimeError) as exc:
        raise SealedContextError(f"cannot resolve runtime context: {exc}") from exc

    entries: list[tuple[str, bytes]] = []
    for path, expected_size, expected_digest in audit.file_records:
        content = _read_stable_regular_file(root / path)
        if len(content) != expected_size or _sha256(content) != expected_digest:
            raise SealedContextError(f"context entry changed after static audit: {path}")
        entries.append((path, content))

    try:
        after = audit_runtime_context(root)
    except RuntimePolicyError as exc:
        raise SealedContextError(f"runtime context changed during sealing: {exc}") from exc
    if after.audit_sha256 != audit.audit_sha256:
        raise SealedContextError("runtime context audit identity changed during sealing")

    return SealedRuntimeContext(
        audit=audit,
        base_image=contract["base_image"],
        tar_bytes=_canonical_tar(tuple(entries)),
    )


__all__ = [
    "SEALED_CONTEXT_PLATFORM",
    "SEALED_CONTEXT_SCHEMA_VERSION",
    "DockerBuildRequest",
    "DockerBuildResult",
    "SealedContextError",
    "SealedRuntimeContext",
    "execute_docker_build",
    "seal_runtime_context",
]
