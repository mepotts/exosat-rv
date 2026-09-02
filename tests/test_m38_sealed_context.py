"""Target-free tests for canonical M38 build-context byte sealing."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

import exosat_rv.m38.sealed_context as sealed_module
from exosat_rv.m38.sealed_context import (
    DockerBuildRequest,
    DockerBuildResult,
    SealedContextError,
    SealedRuntimeContext,
    execute_docker_build,
    seal_runtime_context,
)


def committed_context() -> Path:
    return Path(__file__).resolve().parents[1] / "containers" / "m38"


def copied_context(tmp_path: Path) -> Path:
    destination = tmp_path / "m38-context"
    shutil.copytree(committed_context(), destination)
    return destination


def build_metadata(request: DockerBuildRequest, image_id: str) -> bytes:
    context_digest = request.sealed_context.tar_sha256
    base_digest = request.sealed_context.base_image.rsplit("@sha256:", 1)[1]
    context_uri = "http://buildkit-session/test-context"
    return json.dumps(
        {
            "buildx.build.provenance": {
                "buildType": "https://mobyproject.org/buildkit@v1",
                "materials": [
                    {
                        "uri": "pkg:docker/python@3.11-slim",
                        "digest": {"sha256": base_digest},
                    },
                    {
                        "uri": context_uri,
                        "digest": {"sha256": context_digest},
                    },
                ],
                "invocation": {
                    "configSource": {
                        "uri": context_uri,
                        "digest": {"sha256": context_digest},
                        "entryPoint": "Dockerfile",
                    },
                    "parameters": {
                        "args": {"force-network-mode": "none"},
                        "root": {
                            "configSource": {
                                "uri": context_uri,
                                "digest": {"sha256": context_digest},
                                "path": "Dockerfile",
                            },
                            "request": {"args": {"force-network-mode": "none"}},
                        },
                    },
                    "environment": {"platform": "linux/amd64"},
                },
            },
            "containerimage.digest": image_id,
        },
        sort_keys=True,
    ).encode("utf-8")


def test_seal_is_deterministic_and_binds_exact_canonical_tar_bytes(tmp_path):
    first = seal_runtime_context(committed_context())
    copied = copied_context(tmp_path)
    for index, path in enumerate(sorted(copied.iterdir(), reverse=True)):
        os.utime(path, ns=(1_000_000_000 + index, 2_000_000_000 + index))

    second = seal_runtime_context(copied)

    assert first.tar_bytes == second.tar_bytes
    assert first.tar_sha256 == second.tar_sha256
    assert first.seal_sha256 == second.seal_sha256
    assert first.tar_size_bytes % 10240 == 0
    assert first.as_dict()["not_proven"] == [
        "builder consumed the supplied stdin bytes",
        "registry egress was disabled",
        "base image was already local",
        "image identity or runtime enforcement",
        "external attestation or observer blindness",
    ]

    with tarfile.open(fileobj=io.BytesIO(first.tar_bytes), mode="r:") as archive:
        members = archive.getmembers()
    assert [member.name for member in members] == [record[0] for record in first.audit.file_records]
    assert all(member.isfile() for member in members)
    assert all(member.mode == 0o644 for member in members)
    assert all(member.uid == member.gid == member.mtime == 0 for member in members)
    assert all(member.uname == member.gname == "" for member in members)


def test_build_request_uses_the_same_bytes_and_states_network_limits(tmp_path):
    sealed = seal_runtime_context(committed_context())
    request = DockerBuildRequest(
        sealed_context=sealed,
        iid_file=str((tmp_path / "image.iid").resolve()),
        metadata_file=str((tmp_path / "build-metadata.json").resolve()),
    )

    assert request.stdin_bytes is sealed.tar_bytes
    assert request.arguments[-1] == "-"
    assert "--platform=linux/amd64" in request.arguments
    assert "--network=none" in request.arguments
    assert "--pull=false" in request.arguments
    assert request.as_dict()["run_instruction_network_mode"] == "none"
    assert request.as_dict()["registry_egress_disabled_proven"] is False
    assert request.as_dict()["audit_sha256"] == sealed.audit.audit_sha256
    assert request.as_dict()["sealed_context_sha256"] == sealed.seal_sha256
    assert len(request.request_sha256) == 64


def test_sealed_context_rejects_changed_noncanonical_or_extra_tar_bytes():
    sealed = seal_runtime_context(committed_context())

    with pytest.raises(SealedContextError, match="does not match.*runtime contract"):
        SealedRuntimeContext(
            audit=sealed.audit,
            base_image="example.invalid/python@sha256:" + "f" * 64,
            tar_bytes=sealed.tar_bytes,
        )

    changed = bytearray(sealed.tar_bytes)
    changed[600] ^= 1
    with pytest.raises(SealedContextError):
        SealedRuntimeContext(
            audit=sealed.audit,
            base_image=sealed.base_image,
            tar_bytes=bytes(changed),
        )

    with pytest.raises(SealedContextError, match="canonical USTAR"):
        SealedRuntimeContext(
            audit=sealed.audit,
            base_image=sealed.base_image,
            tar_bytes=sealed.tar_bytes + b"trailing",
        )


def test_sealing_rejects_post_audit_mutation(tmp_path, monkeypatch):
    context = copied_context(tmp_path)
    original = sealed_module._read_stable_regular_file
    mutated = False

    def mutate_after_read(path: Path) -> bytes:
        nonlocal mutated
        payload = original(path)
        if path.name == "entrypoint.py" and not mutated:
            path.write_bytes(payload + b"\n")
            mutated = True
        return payload

    monkeypatch.setattr(sealed_module, "_read_stable_regular_file", mutate_after_read)
    with pytest.raises(SealedContextError, match="changed during sealing"):
        seal_runtime_context(context)


def test_archive_name_validation_rejects_aliases_and_noncanonical_paths():
    with pytest.raises(SealedContextError, match="case/Unicode-colliding"):
        sealed_module._canonical_tar((("File", b"a"), ("file", b"b")))
    with pytest.raises(SealedContextError, match="NFC-normalised"):
        sealed_module._canonical_tar((("e\N{COMBINING ACUTE ACCENT}", b"a"),))
    with pytest.raises(SealedContextError, match="POSIX-relative"):
        sealed_module._canonical_tar((("../escape", b"a"),))


def test_build_request_rejects_ambiguous_output_paths(tmp_path):
    sealed = seal_runtime_context(committed_context())
    output = str((tmp_path / "same").resolve())
    with pytest.raises(SealedContextError, match="distinct"):
        DockerBuildRequest(sealed, output, output)
    with pytest.raises(SealedContextError, match="absolute"):
        DockerBuildRequest(sealed, "relative.iid", str((tmp_path / "metadata").resolve()))


def test_execute_build_rejects_output_parent_alias(tmp_path):
    sealed = seal_runtime_context(committed_context())
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    try:
        alias_parent.symlink_to(real_parent, target_is_directory=True)
    except OSError:
        pytest.skip("this host cannot create a directory symlink")
    request = DockerBuildRequest(
        sealed,
        str(alias_parent / "image.iid"),
        str(alias_parent / "metadata.json"),
    )
    with pytest.raises(SealedContextError, match="symlink or junction"):
        execute_docker_build(request, runner=lambda *_args, **_kwargs: None)


def test_execute_build_streams_the_exact_tar_and_binds_fresh_outputs(tmp_path):
    sealed = seal_runtime_context(committed_context())
    iid_path = (tmp_path / "image.iid").resolve()
    metadata_path = (tmp_path / "metadata.json").resolve()
    request = DockerBuildRequest(sealed, str(iid_path), str(metadata_path))
    image_id = "sha256:" + "a" * 64
    observed: dict[str, object] = {}

    def runner(arguments, **kwargs):
        observed["arguments"] = arguments
        observed["input"] = kwargs["input"]
        iid_path.write_text(image_id, encoding="ascii")
        metadata_path.write_bytes(build_metadata(request, image_id))
        return subprocess.CompletedProcess(arguments, 0, b"stdout", b"stderr")

    result = execute_docker_build(request, runner=runner)

    assert type(result) is DockerBuildResult
    assert observed == {"arguments": request.arguments, "input": sealed.tar_bytes}
    assert result.image_id == image_id
    assert result.metadata["containerimage.digest"] == image_id
    assert result.builder_reported_bindings["context_tar_sha256"] == sealed.tar_sha256
    assert result.builder_reported_bindings["platform"] == "linux/amd64"
    assert result.as_dict()["request_sha256"] == request.request_sha256
    assert len(result.result_sha256) == 64


def test_execute_build_fails_closed_on_stale_outputs_bad_runner_and_iid_mismatch(tmp_path):
    sealed = seal_runtime_context(committed_context())
    iid_path = (tmp_path / "image.iid").resolve()
    metadata_path = (tmp_path / "metadata.json").resolve()
    request = DockerBuildRequest(sealed, str(iid_path), str(metadata_path))

    iid_path.write_text("stale", encoding="ascii")
    with pytest.raises(SealedContextError, match="must not already exist"):
        execute_docker_build(request, runner=lambda *_args, **_kwargs: None)
    iid_path.unlink()

    def failed_runner(arguments, **_kwargs):
        return subprocess.CompletedProcess(arguments, 9, b"", b"sensitive output")

    with pytest.raises(SealedContextError, match="exit code 9"):
        execute_docker_build(request, runner=failed_runner)

    def mismatched_runner(arguments, **_kwargs):
        iid_path.write_text("sha256:" + "a" * 64, encoding="ascii")
        metadata_path.write_bytes(build_metadata(request, "sha256:" + "b" * 64))
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    with pytest.raises(SealedContextError, match="does not bind"):
        execute_docker_build(request, runner=mismatched_runner)

    iid_path.unlink()
    metadata_path.unlink()

    def padded_iid_runner(arguments, **_kwargs):
        iid_path.write_text("sha256:" + "a" * 64 + "\n", encoding="ascii")
        metadata_path.write_bytes(build_metadata(request, "sha256:" + "a" * 64))
        return subprocess.CompletedProcess(arguments, 0, b"", b"")

    with pytest.raises(SealedContextError, match="image_id"):
        execute_docker_build(request, runner=padded_iid_runner)


def test_build_result_rejects_unbound_builder_provenance(tmp_path):
    sealed = seal_runtime_context(committed_context())
    request = DockerBuildRequest(
        sealed,
        str((tmp_path / "image.iid").resolve()),
        str((tmp_path / "metadata.json").resolve()),
    )
    image_id = "sha256:" + "a" * 64
    metadata = json.loads(build_metadata(request, image_id))

    metadata["buildx.build.provenance"]["invocation"]["configSource"]["digest"]["sha256"] = "b" * 64
    with pytest.raises(SealedContextError, match="sealed context tar"):
        DockerBuildResult(request, image_id, json.dumps(metadata).encode(), b"", b"")

    metadata = json.loads(build_metadata(request, image_id))
    metadata["buildx.build.provenance"]["invocation"]["environment"]["platform"] = "linux/arm64"
    with pytest.raises(SealedContextError, match="requested platform"):
        DockerBuildResult(request, image_id, json.dumps(metadata).encode(), b"", b"")

    metadata = json.loads(build_metadata(request, image_id))
    metadata["buildx.build.provenance"]["materials"][0]["digest"]["sha256"] = "c" * 64
    with pytest.raises(SealedContextError, match="base material"):
        DockerBuildResult(request, image_id, json.dumps(metadata).encode(), b"", b"")
