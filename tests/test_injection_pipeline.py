"""Regression tests for the script-level injection and M36 selection machinery."""

import base64
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    path = ROOT / "scripts" / "injection" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scorer():
    return load_script("inject_score2")


@pytest.fixture(scope="module")
def m36():
    return load_script("m36_blind_selection")


def write_rvo(path, rows):
    lines = ["rv2 e_rv2 rv3 e_rv3 file"]
    lines.extend(" ".join(map(str, row)) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def synthetic_injections(tmp_path, factor=1.123456789123):
    velocities = [-3.0, -1.0, 1.0, 3.0]
    plan = [{"file": f"epoch{i}.fits", "v": velocity} for i, velocity in enumerate(velocities)]
    reference_rows = []
    for i, velocity in enumerate(velocities):
        # Order 3 is invalid in the reference for the negative-velocity epochs but
        # remains valid in the injected fits. Its large zero point exposes a separate-mask
        # subtraction while having no effect when both means use their intersection.
        order3_error = "nan" if velocity < 0 else 1.0
        reference_rows.append((0.0, 1.0, 1000.0, order3_error, f"epoch{i}.fits"))
        write_rvo(
            tmp_path / f"arm_inj{i:02d}.rvo.dat",
            [
                (
                    factor * velocity,
                    1.0,
                    1000.0 + factor * velocity,
                    1.0,
                    f"epoch{i}.fits",
                )
            ],
        )
    reference = tmp_path / "reference.rvo.dat"
    write_rvo(reference, reference_rows)
    return reference, plan, factor


def test_epoch_means_use_the_intersection_of_valid_orders(tmp_path, scorer):
    reference, plan, factor = synthetic_injections(tmp_path)

    result = scorer.score_injections("arm", reference, plan, tmp_path)

    assert result["n_epochs"] == len(plan)
    assert result["slope"] == pytest.approx(factor, abs=1e-12)
    assert result["epochs"][0]["matched_orders"] == [2]
    assert result["epochs"][-1]["matched_orders"] == [2, 3]


def test_json_mode_preserves_unrounded_recovery_values(tmp_path, scorer, capsys):
    reference, plan, factor = synthetic_injections(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    assert (
        scorer.main(
            [
                "arm",
                str(reference),
                "--plan",
                str(plan_path),
                "--working-dir",
                str(tmp_path),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["slope"] == pytest.approx(factor, abs=1e-12)
    assert payload["slope"] != round(payload["slope"], 2)
    assert payload["schema_version"] == 1
    first_epoch = payload["epochs"][0]
    assert first_epoch["injected_velocity"] == plan[0]["v"]
    assert first_epoch["recovered_velocity"] == pytest.approx(
        factor * plan[0]["v"], abs=1e-12
    )
    assert first_epoch["per_order"] == [
        {"order": 2, "difference": pytest.approx(factor * plan[0]["v"], abs=1e-12)}
    ]


def _slope_from_pairs(pairs):
    injected = np.asarray([pair[0] for pair in pairs], dtype=float)
    recovered = np.asarray([pair[1] for pair in pairs], dtype=float)
    design = np.column_stack([injected, np.ones_like(injected)])
    return float(np.linalg.lstsq(design, recovered, rcond=None)[0][0])


def test_epoch_audit_values_reconstruct_aggregate_and_per_order_slopes(tmp_path, scorer):
    reference, plan, _ = synthetic_injections(tmp_path)

    result = scorer.score_injections("arm", reference, plan, tmp_path)
    used = [epoch for epoch in result["epochs"] if epoch["status"] == "used"]
    aggregate_pairs = [
        (epoch["injected_velocity"], epoch["recovered_velocity"]) for epoch in used
    ]

    assert _slope_from_pairs(aggregate_pairs) == pytest.approx(result["slope"], abs=1e-12)
    for epoch in used:
        assert epoch["recovered_velocity"] == pytest.approx(
            np.mean([row["difference"] for row in epoch["per_order"]]), abs=1e-12
        )

    stored_by_order = {}
    for epoch in used:
        for row in epoch["per_order"]:
            stored_by_order.setdefault(row["order"], []).append(
                (epoch["injected_velocity"], row["difference"])
            )
    for order_result in result["per_order"]:
        pairs = stored_by_order[order_result["order"]]
        assert len(pairs) == order_result["n_epochs"]
        if order_result["slope"] is None:
            assert len(pairs) < 4
        else:
            assert _slope_from_pairs(pairs) == pytest.approx(order_result["slope"], abs=1e-12)


def test_injection_induced_valid_order_attrition_is_recorded(tmp_path, scorer):
    velocities = [-3.0, -1.0, 1.0, 3.0]
    plan = [
        {"file": f"epoch{i}.fits", "v": velocity}
        for i, velocity in enumerate(velocities)
    ]
    reference_rows = []
    for index, velocity in enumerate(velocities):
        filename = f"epoch{index}.fits"
        reference_rows.append((0.0, 1.0, 1000.0, 1.0, filename))
        injection_order3_error = "nan" if velocity < 0 else 1.0
        write_rvo(
            tmp_path / f"arm_inj{index:02d}.rvo.dat",
            [
                (
                    velocity,
                    1.0,
                    1000.0 + velocity,
                    injection_order3_error,
                    filename,
                )
            ],
        )
    reference = tmp_path / "reference.rvo.dat"
    write_rvo(reference, reference_rows)

    result = scorer.score_injections("arm", reference, plan, tmp_path)

    assert result["n_epochs"] == len(plan)
    assert result["epochs"][0]["reference_valid_orders"] == [2, 3]
    assert result["epochs"][0]["injection_valid_orders"] == [2]
    assert result["epochs"][0]["matched_orders"] == [2]
    assert result["epochs"][0]["orders_lost_in_injection"] == [3]
    assert result["epochs"][-1]["orders_lost_in_injection"] == []


def option_value(argv, option):
    return argv[argv.index(option) + 1]


def test_m36_argv_explicitly_passes_every_held_fixed_setting(m36):
    config = dict(m36.grid("audit01")[0], _tpl=m36.TPL)
    tag = config["arm"] + "_ref"
    argv = m36.build_viper_command("cr2res_data/*.fits", tag, config)

    assert "-nocell" in argv
    assert option_value(argv, "-tag") == tag
    assert option_value(argv, "-chunks") == "1"
    assert option_value(argv, "-deg_norm") == "3"
    assert option_value(argv, "-deg_wave") == "3"
    assert option_value(argv, "-iset") == "380:1700"
    assert option_value(argv, "-oset") == config["oset"]
    assert option_value(argv, "-oversampling") == str(config["oversampling"])


def test_m36_replay_namespace_never_uses_historical_m36_tags(m36):
    run_id = "audit01"
    configs = m36.grid(run_id)
    namespace = m36.replay_namespace(run_id)
    all_tags = []
    for config in configs:
        all_tags.extend(
            [
                config["arm"],
                config["arm"] + "_ref",
                config["arm"] + "_inj00",
            ]
        )

    assert namespace == "M36PA_audit01"
    assert all(tag.startswith(namespace + "_") for tag in all_tags)
    assert all(not tag.startswith("M36_c") for tag in all_tags)
    assert m36.replay_template_dir(run_id).startswith(m36.INJECTION_ROOT)
    assert "M36PA_audit01" in m36.replay_template_dir(run_id)


@pytest.mark.parametrize("run_id", ["../escape", "has space", "a/b", "", "a" * 33])
def test_m36_run_id_rejects_path_aliases(run_id, m36):
    with pytest.raises(ValueError):
        m36.validate_run_id(run_id)


def test_m36_dry_run_exposes_effective_argv_in_new_namespace(m36, capsys):
    m36.main(["--dry-run", "--run-id", "audit01"])
    output = capsys.readouterr().out

    assert "POST-AUDIT REPLAY" in output
    assert "does not rehabilitate data/m36-selection.json" in output
    assert "m36-post-audit-replay-audit01.json" in output
    assert "M36PA_audit01_c00" in output
    assert "M36_c" not in output
    assert "deg_norm=3" in output
    assert "deg_wave=3" in output
    assert "-chunks 1" in output
    assert "-iset 380:1700" in output


def test_m36_consumes_full_precision_json_instead_of_rounded_text(m36, monkeypatch):
    exact_slope = 1.00123456789
    exact_stderr = 0.00987654321
    payload = {
        "slope": exact_slope,
        "slope_stderr": exact_stderr,
        "n_epochs": 18,
        "per_order": [{"order": 2, "slope": 0.9}, {"order": 3, "slope": 1.1}],
    }

    class Completed:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Completed()

    monkeypatch.setattr(m36.subprocess, "run", fake_run)
    slope, stderr, parsed = m36.score("M36PA_audit01_c00", "reference.rvo.dat")

    assert slope == exact_slope
    assert stderr == exact_stderr
    assert {key: parsed[key] for key in payload} == payload
    assert json.loads(parsed["invocation"]["stdout"]) == payload
    assert parsed["invocation"]["stderr"] == ""
    assert "--plan" in parsed["invocation"]["argv"]
    assert "--working-dir" in parsed["invocation"]["argv"]
    assert calls[0][0][-1] == "--json"
    assert m36.per_order_spread(parsed) == pytest.approx(2**0.5 / 10)


def test_m36_keeps_the_registered_slope_only_gate(m36):
    assert m36.passes_registered_slope_gate(0.80)
    assert m36.passes_registered_slope_gate(1.20)
    assert not m36.passes_registered_slope_gate(0.7999)
    assert not m36.passes_registered_slope_gate(1.2001)
    assert not m36.passes_registered_slope_gate(None)
    first = m36.replay_output_path("audit01")
    second = m36.replay_output_path("audit02")
    assert first != second
    assert first != m36.HISTORICAL_OUTPUT
    assert second != m36.HISTORICAL_OUTPUT


def test_bare_or_mismatched_rvo_is_never_a_cache_hit(tmp_path, m36, monkeypatch):
    monkeypatch.setattr(m36, "VIPER", str(tmp_path))
    m36._sha256_for_stat.cache_clear()
    tag = "M36PA_audit01_c00_ref"
    output = tmp_path / f"{tag}.rvo.dat"
    log = tmp_path / f"{tag}.log"
    write_rvo(output, [(1.0, 1.0, 2.0, 1.0, "epoch.fits")])
    log.write_text("synthetic log\n", encoding="utf-8")
    expected = {
        "schema_version": m36.CACHE_SCHEMA,
        "runtime_identity_sha256": "runtime-a",
        "argv": ["viper.py", "-deg_norm", "3"],
    }

    assert not m36.cache_matches(tag, expected)
    m36._write_cache_manifest(tag, expected, str(log))
    assert m36.cache_matches(tag, expected)

    changed_config = {**expected, "runtime_identity_sha256": "runtime-b"}
    assert not m36.cache_matches(tag, changed_config)

    with output.open("a", encoding="utf-8") as fh:
        fh.write("3 1 4 1 another.fits\n")
    assert not m36.cache_matches(tag, expected)


def test_tag_target_coordinates_are_content_matched_before_a_run(tmp_path, m36, monkeypatch):
    monkeypatch.setattr(m36, "VIPER", str(tmp_path))
    m36._sha256_for_stat.cache_clear()
    source = tmp_path / "full1.targ.csv"
    tag = "M36PA_audit01_c00_ref"
    target = tmp_path / f"{tag}.targ.csv"
    source.write_text("name,ra,dec\nCD-35 2722,1,2\n", encoding="utf-8")
    target.write_text("name,ra,dec\nwrong,3,4\n", encoding="utf-8")

    assert Path(m36._ensure_target_csv(tag)) == target
    assert target.read_bytes() == source.read_bytes()


def configure_template_workspace(tmp_path, m36, monkeypatch):
    viper_dir = tmp_path / "viper"
    injection_root = tmp_path / "injections"
    script_dir = tmp_path / "scripts"
    viper_dir.mkdir()
    injection_root.mkdir()
    script_dir.mkdir()
    plan_path = script_dir / "plan.json"
    plan_path.write_text(
        '[{"file": "a.fits", "v": 0}, {"file": "b.fits", "v": 1}]', encoding="utf-8"
    )
    (script_dir / "mktpl.py").write_text("# synthetic generator\n", encoding="utf-8")
    (viper_dir / m36.TPL).write_bytes(b"source template")

    monkeypatch.setattr(m36, "VIPER", str(viper_dir))
    monkeypatch.setattr(m36, "INJECTION_ROOT", str(injection_root))
    monkeypatch.setattr(m36, "SC", str(script_dir))
    monkeypatch.setattr(m36, "PLAN", str(plan_path))
    m36._sha256_for_stat.cache_clear()
    plan = [{"file": "a.fits", "v": 0}, {"file": "b.fits", "v": 1}]
    return plan, injection_root


def test_mismatched_template_namespace_is_never_blessed_in_place(tmp_path, m36, monkeypatch):
    plan, _ = configure_template_workspace(tmp_path, m36, monkeypatch)
    run_id = "audit01"
    final_dir = Path(m36.replay_template_dir(run_id))
    final_dir.mkdir(parents=True)
    for index in range(len(plan)):
        (final_dir / f"inj{index:02d}_tpl.fits").write_bytes(b"stale template")

    def must_not_run(*args, **kwargs):
        raise AssertionError("a stale namespace must abort before template generation")

    monkeypatch.setattr(m36.subprocess, "check_call", must_not_run)
    with pytest.raises(RuntimeError, match="choose a new run ID"):
        m36.ensure_injected_templates(plan, run_id, "runtime-a")

    assert not Path(m36.template_manifest_path(str(final_dir))).exists()


def test_templates_are_generated_in_an_empty_fresh_namespace(tmp_path, m36, monkeypatch):
    plan, _ = configure_template_workspace(tmp_path, m36, monkeypatch)
    run_id = "audit02"
    staging_paths = []

    def fake_generator(argv, cwd):
        staging = Path(argv[-1])
        staging_paths.append(staging)
        assert cwd == m36.VIPER
        assert list(staging.iterdir()) == []
        for index in range(len(plan)):
            (staging / f"inj{index:02d}_tpl.fits").write_bytes(f"template {index}".encode())
        return 0

    monkeypatch.setattr(m36.subprocess, "check_call", fake_generator)
    final_dir = m36.ensure_injected_templates(plan, run_id, "runtime-a")
    expected_spec = m36.template_bundle_spec(plan, run_id, "runtime-a")

    assert Path(final_dir) == Path(m36.replay_template_dir(run_id))
    assert staging_paths and not staging_paths[0].exists()
    assert m36.template_bundle_matches(plan, final_dir, expected_spec)
    audit = m36.template_audit_record(final_dir)
    assert audit["valid"] is True
    assert audit["manifest_payload_sha256"]


def test_template_staging_rejects_extra_outputs(tmp_path, m36, monkeypatch):
    plan, _ = configure_template_workspace(tmp_path, m36, monkeypatch)
    run_id = "audit03"

    def fake_generator(argv, cwd):
        del cwd
        staging = Path(argv[-1])
        for index in range(len(plan)):
            (staging / f"inj{index:02d}_tpl.fits").write_bytes(b"template")
        (staging / "stale_tpl.fits").write_bytes(b"stale")
        return 0

    monkeypatch.setattr(m36.subprocess, "check_call", fake_generator)
    with pytest.raises(RuntimeError, match="invalid staging directory"):
        m36.ensure_injected_templates(plan, run_id, "runtime-a")

    assert not Path(m36.replay_template_dir(run_id)).exists()


def test_runtime_identity_preserves_git_diff_sources_and_worker_dependencies(
    tmp_path, m36, monkeypatch
):
    viper_dir = tmp_path / "viper"
    viper_dir.mkdir()
    (viper_dir / "viper.py").write_text("import numpy\n", encoding="utf-8")
    (viper_dir / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (viper_dir / "config_viper.ini").write_text("[config]\n", encoding="utf-8")
    (viper_dir / "instrument.dat").write_bytes(b"instrument")
    worker = tmp_path / "worker-python"
    worker.write_bytes(b"synthetic interpreter")
    tracked_diff = {"bytes": b"binary patch\x00\xff"}

    def fake_capture(argv, cwd):
        assert cwd == str(viper_dir)
        if argv == ["git", "rev-parse", "HEAD"]:
            return b"abc123\n"
        if argv == ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--"]:
            return tracked_diff["bytes"]
        if argv == ["git", "status", "--short", "--untracked-files=no"]:
            return b" M helper.py\n"
        if argv[0] == str(worker):
            return json.dumps(
                {
                    "executable": str(worker),
                    "version": "3.test",
                    "platform": "test-platform",
                    "packages": [["numpy", "9.9"]],
                },
                sort_keys=True,
            ).encode()
        raise AssertionError(argv)

    monkeypatch.setattr(m36, "VIPER", str(viper_dir))
    monkeypatch.setattr(m36, "PY", str(worker))
    monkeypatch.setattr(m36, "FTS", "instrument.dat")
    monkeypatch.setattr(m36, "_capture_bytes", fake_capture)
    m36._sha256_for_stat.cache_clear()

    first = m36.runtime_identity()
    assert first["viper_git"]["head"] == "abc123"
    assert base64.b64decode(first["viper_git"]["tracked_diff_base64"]) == tracked_diff["bytes"]
    assert {item["path"] for item in first["viper_python_sources"]} == {
        "helper.py",
        "viper.py",
    }
    assert first["instrument_fts"]["sha256"]
    assert first["python"]["packages"] == [["numpy", "9.9"]]
    assert first["python"]["executable_fingerprint"]["sha256"]

    tracked_diff["bytes"] = b"different patch"
    second = m36.runtime_identity()
    assert m36.canonical_sha256(first) != m36.canonical_sha256(second)


def test_run_spec_binds_runtime_identity_and_rejects_historical_tag(tmp_path, m36, monkeypatch):
    monkeypatch.setattr(m36, "VIPER", str(tmp_path))
    config = dict(m36.grid("audit01")[0], _tpl="template.fits")
    with pytest.raises(ValueError, match="outside replay namespace"):
        m36.run_spec("*.fits", "M36_c00ref", config, "audit01", "runtime-a")

    tag = config["arm"] + "_ref"
    spec = m36.run_spec("*.fits", tag, config, "audit01", "runtime-a")
    assert spec["runtime_identity_sha256"] == "runtime-a"
    assert spec["run_id"] == "audit01"
    assert option_value(spec["argv"], "-tag") == tag


def test_existing_unmanifested_rvo_aborts_without_viper(tmp_path, m36, monkeypatch):
    monkeypatch.setattr(m36, "VIPER", str(tmp_path))
    m36._sha256_for_stat.cache_clear()
    (tmp_path / "full1.targ.csv").write_text("name,ra,dec\ntest,1,2\n", encoding="utf-8")
    config = dict(m36.grid("audit01")[0], _tpl="template.fits")
    tag = config["arm"] + "_ref"
    write_rvo(
        tmp_path / f"{tag}.rvo.dat",
        [(1.0, 1.0, 2.0, 1.0, "epoch.fits")],
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("stale output must never invoke or be reused by VIPER")

    monkeypatch.setattr(m36, "viper", must_not_run)
    with pytest.raises(RuntimeError, match="namespace collision"):
        m36.ensure_run(
            "*.fits",
            tag,
            config,
            str(tmp_path / "run.log"),
            "audit01",
            "runtime-a",
        )


def test_json_artifacts_are_digest_bound_and_never_overwritten(tmp_path, m36):
    artifact = tmp_path / "replays" / "result.json"
    m36.write_json_exclusive(str(artifact), {"status": "complete", "value": 1})
    original = artifact.read_bytes()
    stored = json.loads(original)

    assert m36._valid_hashed_payload(stored)
    with pytest.raises(FileExistsError):
        m36.write_json_exclusive(str(artifact), {"status": "complete", "value": 2})
    assert artifact.read_bytes() == original


def test_json_serialization_failure_never_publishes_final_artifact(tmp_path, m36):
    artifact = tmp_path / "result.json"
    with pytest.raises(TypeError):
        m36.write_json_exclusive(str(artifact), {"not_json": object()})

    assert not artifact.exists()
    assert list(tmp_path.glob(".exosat-json-*.tmp")) == []


def test_replay_payload_keeps_full_scorer_and_manifest_evidence(m36):
    score = {
        "schema_version": 1,
        "slope": 1.0123456789,
        "slope_stderr": 0.0123,
        "n_epochs": 1,
        "epochs": [
            {
                "file": "epoch.fits",
                "matched_orders": [2, 3],
                "injected_velocity": 4.5,
                "per_order": [{"order": 2, "difference": 4.4}],
            }
        ],
        "per_order": [{"order": 2, "slope": 1.01}],
        "invocation": {"stdout": "raw scorer json", "stderr": "", "returncode": 0},
    }
    cache_record = {
        "tag": "M36PA_audit01_c00_ref",
        "manifest": {"sha256": "manifest-hash"},
        "manifest_payload_sha256": "payload-hash",
        "run_spec_sha256": "run-hash",
    }
    result = {
        "arm": "M36PA_audit01_c00",
        "eligible": True,
        "slope": score["slope"],
        "score": score,
        "cache_manifests": {"reference": cache_record, "injections": []},
    }
    runtime = {
        "viper_git": {"tracked_diff_base64": "cGF0Y2g=", "head": "abc"},
        "python": {"packages": [["numpy", "9.9"]]},
    }
    template_record = {
        "manifest": {"sha256": "template-manifest-hash"},
        "manifest_payload_sha256": "template-payload-hash",
        "run_spec_sha256": "template-run-hash",
    }

    payload = m36.build_replay_payload(
        "audit01",
        [result],
        result,
        12.3,
        runtime,
        template_record,
        [cache_record],
    )

    assert payload["grid"][0]["score"] == score
    assert payload["grid"][0]["score"]["epochs"][0]["matched_orders"] == [2, 3]
    assert payload["grid"][0]["score"]["per_order"] == score["per_order"]
    assert payload["cache_manifests"][0]["run_spec_sha256"] == "run-hash"
    assert payload["template_manifest"]["manifest_payload_sha256"] == ("template-payload-hash")
    assert payload["runtime_identity"] == runtime
    assert payload["runtime_identity_sha256"] == m36.canonical_sha256(runtime)


def test_non_dry_m36_replay_is_disabled_before_external_work(tmp_path, m36, monkeypatch):
    viper_dir = tmp_path / "viper"
    viper_dir.mkdir()
    historical = {
        viper_dir / "M36_c00ref.rvo.dat": b"historical rvo",
        viper_dir / "M36_c00ref.targ.csv": b"historical target",
        viper_dir / "M36_c00ref.exosat-cache.json": b"historical cache",
    }
    for path, value in historical.items():
        path.write_bytes(value)

    monkeypatch.setattr(m36, "VIPER", str(viper_dir))
    monkeypatch.setattr(m36, "INJECTION_ROOT", str(tmp_path / "injections"))
    monkeypatch.setattr(m36, "REPLAY_OUTPUT_DIR", str(tmp_path / "replays"))

    def must_not_run(*args, **kwargs):
        raise AssertionError("disabled replay reached external work")

    monkeypatch.setattr(m36, "runtime_identity", must_not_run)
    monkeypatch.setattr(m36, "ensure_injected_templates", must_not_run)
    monkeypatch.setattr(m36.subprocess, "run", must_not_run)
    monkeypatch.setattr(m36.subprocess, "call", must_not_run)
    monkeypatch.setattr(m36.subprocess, "check_call", must_not_run)

    with pytest.raises(RuntimeError, match="non-dry M36 replay is disabled"):
        m36.main(["--run-id", "audit01"])

    assert all(path.read_bytes() == value for path, value in historical.items())
    assert not (tmp_path / "injections").exists()
    assert not (tmp_path / "replays").exists()


def test_m36_cli_fails_closed_on_missing_or_unknown_options(m36):
    with pytest.raises(SystemExit):
        m36.parse_args([])
    with pytest.raises(SystemExit):
        m36.parse_args(["--dry-rnu"])
