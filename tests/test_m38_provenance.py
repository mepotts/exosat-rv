"""Synthetic-only tests for the M38 provenance manifest chain."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import exosat_rv.m38.provenance as provenance_module
from exosat_rv.m38.provenance import (
    ManifestExistsError,
    ManifestVerificationError,
    ProvenanceError,
    append_stage_manifest,
    build_stage_manifest,
    canonical_json_bytes,
    canonical_sha256,
    immutable_file_record,
    load_manifest,
    manifest_filename,
    manifest_sha256,
    verify_manifest_chain,
    verify_stage_manifest,
    write_manifest_exclusive,
)


class IntSubclass(int):
    """A JSON-looking scalar that strict provenance must reject."""


def reseal_unsigned(manifest):
    """Recompute hashes after an adversarial synthetic manifest mutation."""

    payload = {
        key: value for key, value in manifest.items() if key not in {"integrity", "manifest_sha256"}
    }
    payload_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    manifest["integrity"]["payload_sha256"] = payload_hash
    manifest["integrity"]["signature"]["signed_content_sha256"] = payload_hash
    manifest["manifest_sha256"] = manifest_sha256(manifest)


def stage_manifest(
    workspace: Path,
    *,
    sequence: int,
    stage: str,
    input_name: str,
    output_name: str,
    prior: str | None,
    signer=None,
):
    return build_stage_manifest(
        stage=stage,
        sequence=sequence,
        protocol={"path": "protocol.md", "sha256": "1" * 64},
        source={"commit": "abc123", "dirty_patch_sha256": "2" * 64},
        dependencies=[{"name": "synthetic-lib", "version": "1.0"}],
        config={"choice": "fixed", "nested": {"b": 2, "a": 1}},
        inputs=[immutable_file_record(workspace / input_name, root=workspace)],
        outputs=[
            immutable_file_record(
                workspace / output_name,
                root=workspace,
                metadata={"rows": 3, "orders": 2},
            )
        ],
        argv=["synthetic-runner", "--fixed"],
        seeds={"permutation": 42},
        status="complete",
        failure_reason=None,
        prior_manifest_sha256=prior,
        started_at="2030-01-01T00:00:00Z",
        ended_at="2030-01-01T00:01:00Z",
        exit_status=0,
        signer=signer,
    )


def test_canonical_json_and_manifest_are_deterministic(tmp_path):
    (tmp_path / "input.txt").write_text("input\n", encoding="utf-8")
    (tmp_path / "output.txt").write_text("output\n", encoding="utf-8")

    left = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )
    right = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )

    assert left == right
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    assert canonical_sha256({"a": 1}) == hashlib.sha256(b'{"a":1}').hexdigest()
    assert left["integrity"]["signature"]["status"] == "unsigned"
    assert left["manifest_sha256"] == canonical_sha256(
        {key: value for key, value in left.items() if key != "manifest_sha256"}
    )


@pytest.mark.parametrize(
    "value",
    [
        {1: "coerced-key"},
        {"value": (1, 2)},
        {"value": {1, 2}},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": IntSubclass(1)},
    ],
)
def test_canonical_json_rejects_lossy_or_non_native_values(value):
    with pytest.raises(ProvenanceError, match="JSON|finite|native"):
        canonical_json_bytes(value)


def test_canonical_json_is_cycle_and_depth_safe_but_allows_shared_values():
    shared = {"value": 1}
    assert canonical_json_bytes({"left": shared, "right": shared}) == (
        b'{"left":{"value":1},"right":{"value":1}}'
    )

    cycle = {}
    cycle["self"] = cycle
    with pytest.raises(ProvenanceError, match="reference cycle"):
        canonical_json_bytes(cycle)

    too_deep = {}
    cursor = too_deep
    for _ in range(300):
        child = {}
        cursor["child"] = child
        cursor = child
    with pytest.raises(ProvenanceError, match="maximum nesting depth"):
        canonical_json_bytes(too_deep)


@pytest.mark.parametrize(
    "content",
    [
        '{"schema_version":1,"schema_version":2}',
        '{"outer":{"value":1,"value":2}}',
    ],
)
def test_load_manifest_rejects_duplicate_object_keys(tmp_path, content):
    path = tmp_path / "duplicate.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ManifestVerificationError, match="duplicate JSON object key"):
        load_manifest(path)


def test_exclusive_manifest_write_refuses_overwrite(tmp_path):
    (tmp_path / "input.txt").write_text("input\n", encoding="utf-8")
    (tmp_path / "output.txt").write_text("output\n", encoding="utf-8")
    manifest = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )
    destination = tmp_path / "chain" / "first.json"

    write_manifest_exclusive(destination, manifest)
    original = destination.read_bytes()
    with pytest.raises(ManifestExistsError):
        write_manifest_exclusive(destination, manifest | {"status": "failed"})
    assert destination.read_bytes() == original


def test_append_and_verify_rehashes_files_and_links_stages(tmp_path):
    for name, content in {
        "input.txt": "input\n",
        "middle.txt": "middle\n",
        "output.txt": "output\n",
    }.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    chain = tmp_path / "chain"

    first = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="middle.txt",
        prior=None,
    )
    first_path = append_stage_manifest(chain, first, bound_roots={"workspace": tmp_path})
    second = stage_manifest(
        tmp_path,
        sequence=1,
        stage="validate",
        input_name="middle.txt",
        output_name="output.txt",
        prior=first["manifest_sha256"],
    )
    second_path = append_stage_manifest(chain, second, bound_roots={"workspace": tmp_path})

    verified = verify_manifest_chain(chain, bound_roots={"workspace": tmp_path})
    assert [item["stage"] for item in verified] == ["freeze", "validate"]
    assert second_path.name == "000001.manifest.json"
    assert first_path.name == "000000.manifest.json"

    (tmp_path / "middle.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="hash mismatch|size mismatch"):
        verify_manifest_chain(chain, bound_roots={"workspace": tmp_path})


def test_append_requires_roots_and_rehashes_new_and_existing_bindings(tmp_path):
    for name, content in {
        "first-input.txt": "first input\n",
        "middle.txt": "middle\n",
        "final.txt": "final\n",
        "fresh-input.txt": "fresh\n",
        "fresh-output.txt": "fresh output\n",
    }.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    fresh = stage_manifest(
        tmp_path,
        sequence=0,
        stage="fresh",
        input_name="fresh-input.txt",
        output_name="fresh-output.txt",
        prior=None,
    )
    with pytest.raises(TypeError, match="bound_roots"):
        append_stage_manifest(tmp_path / "missing-roots", fresh)

    (tmp_path / "fresh-output.txt").write_text("changed after sealing\n", encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="hash mismatch|size mismatch"):
        append_stage_manifest(
            tmp_path / "new-binding-chain",
            fresh,
            bound_roots={"workspace": tmp_path},
        )
    assert not (tmp_path / "new-binding-chain" / manifest_filename(0)).exists()

    first = stage_manifest(
        tmp_path,
        sequence=0,
        stage="first",
        input_name="first-input.txt",
        output_name="middle.txt",
        prior=None,
    )
    chain = tmp_path / "existing-binding-chain"
    append_stage_manifest(chain, first, bound_roots={"workspace": tmp_path})
    second = stage_manifest(
        tmp_path,
        sequence=1,
        stage="second",
        input_name="middle.txt",
        output_name="final.txt",
        prior=first["manifest_sha256"],
    )
    (tmp_path / "first-input.txt").write_text("old binding changed\n", encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="hash mismatch|size mismatch"):
        append_stage_manifest(chain, second, bound_roots={"workspace": tmp_path})
    assert not (chain / manifest_filename(1)).exists()


def test_chain_detects_manifest_tampering_wrong_link_and_wrong_order(tmp_path):
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    first = stage_manifest(
        tmp_path,
        sequence=0,
        stage="one",
        input_name="a.txt",
        output_name="b.txt",
        prior=None,
    )
    second = stage_manifest(
        tmp_path,
        sequence=1,
        stage="two",
        input_name="b.txt",
        output_name="c.txt",
        prior=first["manifest_sha256"],
    )
    first_path = write_manifest_exclusive(tmp_path / "one.json", first)
    second_path = write_manifest_exclusive(tmp_path / "two.json", second)

    with pytest.raises(ManifestVerificationError, match="order|gap|prior link|sequence zero"):
        verify_manifest_chain(
            [second_path, first_path],
            bound_roots={"workspace": tmp_path},
        )

    wrong_link = stage_manifest(
        tmp_path,
        sequence=1,
        stage="two",
        input_name="b.txt",
        output_name="c.txt",
        prior="0" * 64,
    )
    wrong_path = write_manifest_exclusive(tmp_path / "wrong.json", wrong_link)
    with pytest.raises(ManifestVerificationError, match="chain link"):
        verify_manifest_chain(
            [first_path, wrong_path],
            bound_roots={"workspace": tmp_path},
        )

    altered = load_manifest(second_path)
    altered["config"]["choice"] = "changed"
    second_path.write_text(json.dumps(altered), encoding="utf-8")
    with pytest.raises(ManifestVerificationError, match="self-hash"):
        verify_manifest_chain(
            [first_path, second_path],
            bound_roots={"workspace": tmp_path},
        )


def test_signature_callback_is_explicit_and_unsigned_can_be_rejected(tmp_path):
    (tmp_path / "input.txt").write_text("input", encoding="utf-8")
    (tmp_path / "output.txt").write_text("output", encoding="utf-8")
    unsigned = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )
    with pytest.raises(ManifestVerificationError, match="unsigned"):
        verify_stage_manifest(
            unsigned,
            bound_roots={"workspace": tmp_path},
            require_signature=True,
        )

    secret = b"synthetic signing key"

    def signer(payload: bytes):
        return {
            "algorithm": "sha256-prefix-test-only",
            "value": hashlib.sha256(secret + payload).hexdigest(),
        }

    def verifier(payload: bytes, details):
        return details["value"] == hashlib.sha256(secret + payload).hexdigest()

    signed = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
        signer=signer,
    )
    assert signed["integrity"]["signature"]["status"] == "signed"
    verify_stage_manifest(
        signed,
        bound_roots={"workspace": tmp_path},
        signature_verifier=verifier,
        require_signature=True,
    )
    signed_path = append_stage_manifest(
        tmp_path / "signed-chain",
        signed,
        bound_roots={"workspace": tmp_path},
        signature_verifier=verifier,
        require_signatures=True,
    )
    assert signed_path.name == "000000.manifest.json"
    with pytest.raises(ManifestVerificationError, match="requires a signature verifier"):
        verify_stage_manifest(signed, bound_roots={"workspace": tmp_path})

    for truthy_non_bool in (1, "verified"):
        with pytest.raises(ManifestVerificationError, match="signature verification failed"):
            verify_stage_manifest(
                signed,
                bound_roots={"workspace": tmp_path},
                signature_verifier=lambda _payload, _details, result=truthy_non_bool: result,
                require_signature=True,
            )


def test_self_consistent_manifest_still_must_satisfy_the_stage_schema(tmp_path):
    (tmp_path / "input.txt").write_text("input", encoding="utf-8")
    (tmp_path / "output.txt").write_text("output", encoding="utf-8")
    manifest = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )
    manifest.pop("argv")
    reseal_unsigned(manifest)

    with pytest.raises(ManifestVerificationError, match="schema mismatch"):
        verify_stage_manifest(manifest, bound_roots={"workspace": tmp_path})


def test_boolean_schema_version_is_not_accepted_as_integer_one(tmp_path):
    (tmp_path / "input.txt").write_text("input", encoding="utf-8")
    (tmp_path / "output.txt").write_text("output", encoding="utf-8")
    manifest = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )
    manifest["schema_version"] = True
    reseal_unsigned(manifest)

    with pytest.raises(ManifestVerificationError, match="schema version"):
        verify_stage_manifest(manifest, bound_roots={"workspace": tmp_path})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("root", 7, "root"),
        ("path", ["input.txt"], "path"),
        ("size_bytes", True, "size"),
        ("sha256", 7, "SHA-256"),
        ("metadata", [], "metadata"),
    ],
)
def test_self_consistent_file_records_require_strict_field_types(
    tmp_path,
    field,
    value,
    message,
):
    (tmp_path / "input.txt").write_text("input", encoding="utf-8")
    (tmp_path / "output.txt").write_text("output", encoding="utf-8")
    manifest = stage_manifest(
        tmp_path,
        sequence=0,
        stage="freeze",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )
    manifest["inputs"][0][field] = value
    reseal_unsigned(manifest)

    with pytest.raises(ManifestVerificationError, match=message):
        verify_stage_manifest(manifest, bound_roots={"workspace": tmp_path})


def test_manifest_chains_require_zero_genesis_and_sort_numeric_filenames(tmp_path):
    (tmp_path / "input.txt").write_text("input", encoding="utf-8")
    (tmp_path / "output.txt").write_text("output", encoding="utf-8")
    orphan = stage_manifest(
        tmp_path,
        sequence=1,
        stage="orphan",
        input_name="input.txt",
        output_name="output.txt",
        prior=None,
    )

    with pytest.raises(ManifestVerificationError, match="sequence zero"):
        append_stage_manifest(
            tmp_path / "append-orphan",
            orphan,
            bound_roots={"workspace": tmp_path},
        )

    orphan_path = write_manifest_exclusive(
        tmp_path / "verify-orphan" / manifest_filename(1),
        orphan,
    )
    with pytest.raises(ManifestVerificationError, match="sequence zero"):
        verify_manifest_chain([orphan_path], bound_roots={"workspace": tmp_path})

    names = tmp_path / "numeric-names"
    names.mkdir()
    high = names / manifest_filename(1_000_000)
    low = names / manifest_filename(999_999)
    high.write_text("{}", encoding="utf-8")
    low.write_text("{}", encoding="utf-8")
    assert provenance_module._chain_paths(names) == [low, high]


def test_failure_manifest_requires_reason_and_records_it(tmp_path):
    (tmp_path / "input.txt").write_text("input", encoding="utf-8")
    (tmp_path / "output.txt").write_text("partial", encoding="utf-8")
    common = {
        "stage": "failed-stage",
        "sequence": 0,
        "protocol": {"sha256": "1" * 64},
        "source": {"commit": "abc"},
        "dependencies": [],
        "config": {},
        "inputs": [immutable_file_record(tmp_path / "input.txt", root=tmp_path)],
        "outputs": [immutable_file_record(tmp_path / "output.txt", root=tmp_path)],
        "argv": ["runner"],
        "seeds": {},
        "status": "failed",
        "prior_manifest_sha256": None,
        "started_at": "2030-01-01T00:00:00Z",
        "ended_at": "2030-01-01T00:00:01Z",
        "exit_status": 2,
    }
    with pytest.raises(ProvenanceError, match="failure reason"):
        build_stage_manifest(**common, failure_reason=None)
    manifest = build_stage_manifest(**common, failure_reason="synthetic failure")
    assert manifest["failure_reason"] == "synthetic failure"
    assert manifest["exit_status"] == 2


def test_symlink_cannot_be_bound_as_an_immutable_file(tmp_path):
    source = tmp_path / "source.txt"
    link = tmp_path / "link.txt"
    source.write_text("content", encoding="utf-8")
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")

    with pytest.raises(ProvenanceError, match="symlink"):
        immutable_file_record(link, root=tmp_path)
