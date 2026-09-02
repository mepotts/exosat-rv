"""Target-free tests for the dedicated M38 runtime policy and context."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from exosat_rv.m38.runtime_policy import (
    RuntimeLaunchContract,
    RuntimePolicyError,
    audit_runtime_context,
    load_runtime_contract,
)


def committed_context() -> Path:
    return Path(__file__).resolve().parents[1] / "containers" / "m38"


def copied_context(tmp_path: Path) -> Path:
    destination = tmp_path / "m38-context"
    shutil.copytree(committed_context(), destination)
    return destination


def rewrite_contract(context: Path, change) -> None:
    path = context / "runtime-contract.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    change(contract)
    path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_committed_context_is_exact_target_free_allowlist_with_honest_scope():
    audit = audit_runtime_context(committed_context())

    assert {record[0] for record in audit.file_records} == {
        ".dockerignore",
        ".m38-target-free-context",
        "Dockerfile",
        "entrypoint.py",
        "runtime-contract.json",
    }
    assert audit.dedicated_allowlist_context_proven is True
    assert audit.dockerfile_non_root_user_proven is True
    assert audit.launch_contract.container_user == "65532:65532"
    result = audit.as_dict()
    assert result["application_firewall_is_os_confinement"] is False
    assert "audit-to-build and image-digest linkage" in result["not_proven_by_static_audit"]
    assert (
        "build-context stability during or after the point-in-time audit"
        in result["not_proven_by_static_audit"]
    )
    assert "launch-time network isolation" in result["not_proven_by_static_audit"]
    assert len(audit.context_sha256) == 64
    assert len(audit.audit_sha256) == 64


def test_launch_contract_emits_fail_closed_arguments_without_claiming_observation():
    contract = audit_runtime_context(committed_context()).launch_contract

    assert contract.docker_run_arguments() == (
        "--network=none",
        "--read-only",
        "--user=65532:65532",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
    )
    assert contract.as_dict()["network_mode"] == "none"


def test_repository_root_and_unexpected_context_file_are_rejected(tmp_path):
    with pytest.raises(RuntimePolicyError, match="marker|allowlist"):
        audit_runtime_context(committed_context().parents[1])

    context = copied_context(tmp_path)
    (context / "unexpected.bin").write_bytes(b"synthetic")
    with pytest.raises(RuntimePolicyError, match="differs from allowlist"):
        audit_runtime_context(context)


def test_context_marker_and_symlink_fail_closed(tmp_path):
    context = copied_context(tmp_path)
    (context / ".m38-target-free-context").write_text("wrong\n", encoding="utf-8")
    with pytest.raises(RuntimePolicyError, match="marker"):
        audit_runtime_context(context)

    context = copied_context(tmp_path / "second")
    source = context / "entrypoint.py"
    source.unlink()
    try:
        source.symlink_to(context / "Dockerfile")
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    with pytest.raises(RuntimePolicyError, match="symlink"):
        audit_runtime_context(context)


def test_descendant_directory_and_junction_fail_closed(tmp_path, monkeypatch):
    context = copied_context(tmp_path)
    (context / "empty").mkdir()
    with pytest.raises(RuntimePolicyError, match="descendant directories"):
        audit_runtime_context(context)

    context = copied_context(tmp_path / "second")
    monkeypatch.setattr(
        Path,
        "is_junction",
        lambda self: self.name == "entrypoint.py",
        raising=False,
    )
    with pytest.raises(RuntimePolicyError, match="junction"):
        audit_runtime_context(context)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("container_user", "0:0", "non-zero"),
        ("read_only_root_filesystem_required", False, "read-only"),
        ("network_mode_required", "bridge", "network mode"),
        ("drop_all_capabilities_required", False, "capabilities"),
        ("no_new_privileges_required", False, "no-new-privileges"),
        ("application_firewall_is_os_confinement", True, "OS confinement"),
        ("runtime_observation_required", False, "observation"),
        ("base_image", "python:3.11-slim", "pinned"),
    ],
)
def test_insecure_contract_values_are_rejected(tmp_path, field, value, message):
    context = copied_context(tmp_path)
    rewrite_contract(context, lambda contract: contract.__setitem__(field, value))

    with pytest.raises(RuntimePolicyError, match=message):
        audit_runtime_context(context)


def test_contract_duplicate_keys_and_extra_schema_fields_are_rejected(tmp_path):
    context = copied_context(tmp_path)
    path = context / "runtime-contract.json"
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("{", '{"schema_version": 1,', 1), encoding="utf-8")
    with pytest.raises(RuntimePolicyError, match="duplicate JSON key"):
        load_runtime_contract(path)

    context = copied_context(tmp_path / "second")
    rewrite_contract(context, lambda contract: contract.__setitem__("unexpected", True))
    with pytest.raises(RuntimePolicyError, match="schema mismatch"):
        audit_runtime_context(context)


def test_dockerfile_must_remain_pinned_non_root_and_build_network_free(tmp_path):
    context = copied_context(tmp_path)
    dockerfile = context / "Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace("USER 65532:65532", "USER 0:0"),
        encoding="utf-8",
    )
    with pytest.raises(RuntimePolicyError, match="non-root user"):
        audit_runtime_context(context)

    context = copied_context(tmp_path / "second")
    dockerfile = context / "Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8") + "\nRUN python -m pip install something\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimePolicyError, match="forbidden directive"):
        audit_runtime_context(context)

    context = copied_context(tmp_path / "third")
    dockerfile = context / "Dockerfile"
    dockerfile.write_text(
        "# syntax=untrusted/frontend:latest\n" + dockerfile.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(RuntimePolicyError, match="parser directives are forbidden"):
        audit_runtime_context(context)


def test_allowlisted_filenames_must_match_the_approved_content_manifest(tmp_path):
    context = copied_context(tmp_path)
    (context / "entrypoint.py").write_text(
        'print("synthetic replacement")\n',
        encoding="utf-8",
    )

    with pytest.raises(RuntimePolicyError, match="source-audited frozen manifest"):
        audit_runtime_context(context)


def test_entrypoint_requires_the_exact_contracted_uid_and_gid(monkeypatch):
    namespace = {"__name__": "m38_entrypoint_test"}
    source = (committed_context() / "entrypoint.py").read_text(encoding="utf-8")
    # The static context audit content-pins this local test fixture before it can be built.
    exec(compile(source, "m38-entrypoint-test", "exec"), namespace)  # noqa: S102

    class ContractPath:
        def __init__(self, _path):
            pass

        def read_bytes(self):
            return b'{"container_user":"65532:65532"}'

    namespace["Path"] = ContractPath
    monkeypatch.setattr(os, "geteuid", lambda: 1, raising=False)
    monkeypatch.setattr(os, "getegid", lambda: 2, raising=False)
    assert namespace["main"]() == 70

    monkeypatch.setattr(os, "geteuid", lambda: 65532)
    monkeypatch.setattr(os, "getegid", lambda: 65532)
    assert namespace["main"]() == 0


def test_launch_contract_rejects_non_native_or_unsafe_direct_construction():
    class TruthyInt(int):
        pass

    with pytest.raises(RuntimePolicyError, match="read-only"):
        RuntimeLaunchContract(
            container_user="65532:65532",
            read_only_root_filesystem=TruthyInt(1),
            network_mode="none",
            drop_all_capabilities=True,
            no_new_privileges=True,
            tmpfs_mounts=("/tmp",),
        )
    with pytest.raises(RuntimePolicyError, match="approved /tmp"):
        RuntimeLaunchContract(
            container_user="65532:65532",
            read_only_root_filesystem=True,
            network_mode="none",
            drop_all_capabilities=True,
            no_new_privileges=True,
            tmpfs_mounts=("relative",),
        )
    with pytest.raises(RuntimePolicyError, match="approved /tmp"):
        RuntimeLaunchContract(
            container_user="65532:65532",
            read_only_root_filesystem=True,
            network_mode="none",
            drop_all_capabilities=True,
            no_new_privileges=True,
            tmpfs_mounts=("/tmp/../etc",),
        )
