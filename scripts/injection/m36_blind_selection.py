"""Replay the M36 target-aware configuration selection with implementation fixes.

The protocol is `docs/milestones/M36-PREREGISTRATION.md`, committed before this ran. This
file preserves its registered slope-only selection gate. It does not load the published RV
table: selection is the injection-recovery slope from `inject_score2.py`, which compares a
configuration against its own uninjected run. It is nevertheless not paper-blind. The
registered `inject_plan_big.json` encodes the published 171.454-day orbit, so the injected
phase/time/BERV pattern is paper-derived.

Historical boundary: the committed ``data/m36-selection.json`` was produced before the
omitted fixed arguments and unequal-order scoring bug were found. Correcting this runner
does not retroactively validate that artifact. A future execution would be a post-audit
replay, not the preregistered M36 result, and would require a unique external namespace and
repository artifact.

Non-dry execution is intentionally disabled. The audit found that the legacy runner cannot
capture a complete per-invocation software/import manifest or archive all evidence needed
for a repository-only verification. Use the successor protocol rather than executing M36.
The dry run remains available for inspecting the registered grid and effective argv.

Run from anywhere. Dry-run inspection does not invoke viper in ``~/viper-src``.

Usage: python scripts/injection/m36_blind_selection.py --dry-run [--run-id ID]
"""

import argparse
import base64
import glob
import hashlib
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from functools import cache

_ROOT = os.environ.get("EXOSAT_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
)
SC = os.path.join(_ROOT, "scripts", "injection")
PLAN = os.path.join(SC, "inject_plan_big.json")

VIPER = os.path.expanduser("~/viper-src")
PY = os.path.expanduser("~/viperenv/bin/python")
INJECTION_ROOT = os.path.expanduser("~/inj/M36-post-audit")
FTS = "lib/CRIRES/FTS/CRp_SGC2_FTStmpl-HR0p007-WN5000-10000_Hband.dat"
TPL = "M13tpl_tpl.fits"  # iteration 1: iteration 2 was chosen against the paper
TARG = "CD-35 2722"
HISTORICAL_OUTPUT = os.path.join(_ROOT, "data", "m36-selection.json")
REPLAY_OUTPUT_DIR = os.path.join(_ROOT, "data", "m36-post-audit-replays")
REPLAY_TAG_PREFIX = "M36PA"

# These are protocol settings, not assumptions about whichever viper revision happens to
# be installed. Pass every one explicitly so a changed upstream default cannot change M36.
FIXED_SETTINGS = {
    "chunks": 1,
    "deg_norm": 3,
    "deg_wave": 3,
    "iset": "380:1700",
    "nocell": True,
}
CACHE_SCHEMA = 2

# --- the grid, exactly as pre-registered ------------------------------------------
OSETS = ["2:20", "2:11", "11:20"]
OVERSAMPLING = [1, 2, 4]
KAPSIG = [3.0, 4.5]
TELLURIC = ["sig", "mask"]

GATE_LO, GATE_HI = 0.80, 1.20  # eligibility on recovery slope
TIE = 0.005  # |slope-1| within this counts as a tie


def validate_run_id(run_id):
    """Validate the explicit ID used in every external and repository replay path."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", run_id or ""):
        raise ValueError("run ID must be 1-32 ASCII letters, digits, '_' or '-'")
    return run_id


def replay_namespace(run_id):
    return f"{REPLAY_TAG_PREFIX}_{validate_run_id(run_id)}"


def replay_output_path(run_id):
    return os.path.join(REPLAY_OUTPUT_DIR, f"m36-post-audit-replay-{validate_run_id(run_id)}.json")


def replay_template_dir(run_id):
    return os.path.join(INJECTION_ROOT, replay_namespace(run_id), "templates")


def grid(run_id="DRYRUN"):
    namespace = replay_namespace(run_id)
    out = []
    for i, (oset, osamp, kap, tel) in enumerate(
        itertools.product(OSETS, OVERSAMPLING, KAPSIG, TELLURIC)
    ):
        out.append(
            {
                "n": i,
                "arm": f"{namespace}_c{i:02d}",
                "oset": oset,
                "oversampling": osamp,
                "kapsig": kap,
                "telluric": tel,
            }
        )
    return out


def build_viper_command(files, tag, cfg):
    """Build one complete viper argv, including every held-fixed protocol setting."""
    return [
        PY,
        "viper.py",
        files,
        cfg["_tpl"],
        "-inst",
        "CRIRES",
        "-fts",
        FTS,
        "-targ",
        TARG,
        "-tag",
        tag,
        "-nocell",
        "-chunks",
        str(FIXED_SETTINGS["chunks"]),
        "-deg_norm",
        str(FIXED_SETTINGS["deg_norm"]),
        "-deg_wave",
        str(FIXED_SETTINGS["deg_wave"]),
        "-iset",
        FIXED_SETTINGS["iset"],
        "-oset",
        cfg["oset"],
        "-oversampling",
        str(cfg["oversampling"]),
        "-kapsig",
        str(cfg["kapsig"]),
        "-telluric",
        cfg["telluric"],
    ]


def _viper_path(path):
    return path if os.path.isabs(path) else os.path.join(VIPER, path)


@cache
def _sha256_for_stat(path, size, mtime_ns, ctime_ns):
    """Hash a file once per path/stat tuple during this process."""
    del size, mtime_ns, ctime_ns  # values are cache-key material
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path):
    """Return a content-bound fingerprint, or an explicit missing-file record."""
    resolved = os.path.realpath(_viper_path(path))
    label = os.path.relpath(resolved, VIPER).replace(os.sep, "/")
    try:
        stat = os.stat(resolved)
    except FileNotFoundError:
        return {"path": label, "missing": True}
    return {
        "path": label,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "sha256": _sha256_for_stat(resolved, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns),
    }


def canonical_sha256(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _capture_bytes(argv, cwd):
    process = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        error = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"provenance command failed ({shlex.join(argv)}): {error}")
    return process.stdout


def runtime_identity():
    """Capture the complete tracked VIPER delta and executable dependency identity."""
    head = _capture_bytes(["git", "rev-parse", "HEAD"], VIPER).decode().strip()
    tracked_diff = _capture_bytes(["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--"], VIPER)
    tracked_status = _capture_bytes(
        ["git", "status", "--short", "--untracked-files=no"], VIPER
    ).decode("utf-8", errors="replace")

    source_paths = [
        path
        for path in sorted(glob.glob(os.path.join(VIPER, "**", "*.py"), recursive=True))
        if "__pycache__" not in path.split(os.sep) and ".git" not in path.split(os.sep)
    ]
    if not source_paths:
        raise RuntimeError("VIPER source fingerprint found no Python files")

    probe = (
        "import importlib.metadata as m,json,platform,sys;"
        "d=sorted((x.metadata.get('Name') or '',x.version) for x in m.distributions());"
        "print(json.dumps({'executable':sys.executable,'version':sys.version,"
        "'platform':platform.platform(),'packages':d},sort_keys=True))"
    )
    python = json.loads(_capture_bytes([PY, "-c", probe], VIPER))
    return {
        "schema_version": 1,
        "viper_git": {
            "head": head,
            "tracked_status": tracked_status,
            "tracked_diff_sha256": hashlib.sha256(tracked_diff).hexdigest(),
            "tracked_diff_base64": base64.b64encode(tracked_diff).decode("ascii"),
        },
        "viper_python_sources": [file_fingerprint(path) for path in source_paths],
        "viper_config": file_fingerprint("config_viper.ini"),
        "instrument_fts": file_fingerprint(FTS),
        "python": python | {"executable_fingerprint": file_fingerprint(PY)},
    }


def _ensure_target_csv(tag):
    """Make the tag-specific coordinates an exact copy of the declared source."""
    targ_csv = os.path.join(VIPER, tag + ".targ.csv")
    src_csv = os.path.join(VIPER, "full1.targ.csv")
    if not os.path.exists(src_csv):
        raise FileNotFoundError("required target-coordinate source is missing: " + src_csv)
    if (
        not os.path.exists(targ_csv)
        or file_fingerprint(src_csv)["sha256"] != file_fingerprint(targ_csv)["sha256"]
    ):
        shutil.copyfile(src_csv, targ_csv)
    return targ_csv


def run_spec(files, tag, cfg, run_id, runtime_sha256):
    """Describe everything that must match before an RVO cache may be reused."""
    namespace = replay_namespace(run_id)
    if not tag.startswith(namespace + "_"):
        raise ValueError(f"tag {tag!r} is outside replay namespace {namespace!r}")
    pattern = os.path.join(VIPER, files)
    inputs = [file_fingerprint(path) for path in sorted(glob.glob(pattern))]
    return {
        "schema_version": CACHE_SCHEMA,
        "run_id": run_id,
        "runtime_identity_sha256": runtime_sha256,
        "tag": tag,
        "cwd": os.path.realpath(VIPER),
        "argv": build_viper_command(files, tag, cfg),
        "fixed_settings": FIXED_SETTINGS,
        "input_pattern": files,
        "input_files": inputs,
        "template": file_fingerprint(cfg["_tpl"]),
        "target_csv": file_fingerprint(tag + ".targ.csv"),
        "fts": file_fingerprint(FTS),
        "viper_driver": file_fingerprint("viper.py"),
        "viper_config": file_fingerprint("config_viper.ini"),
        "plan": file_fingerprint(PLAN),
        "driver": file_fingerprint(__file__),
        "scorer": file_fingerprint(os.path.join(SC, "inject_score2.py")),
    }


def cache_manifest_path(tag):
    return os.path.join(VIPER, tag + ".exosat-cache.json")


def par(tag):
    return os.path.join(VIPER, tag + ".par.dat")


def _hashed_payload(payload):
    result = dict(payload)
    result["manifest_payload_sha256"] = canonical_sha256(payload)
    return result


def _valid_hashed_payload(payload):
    expected = payload.get("manifest_payload_sha256")
    body = {key: value for key, value in payload.items() if key != "manifest_payload_sha256"}
    return expected is not None and expected == canonical_sha256(body)


def write_json_exclusive(path, payload):
    """Atomically publish JSON once; never replace an existing artifact."""
    final_path = os.path.abspath(path)
    parent = os.path.dirname(final_path)
    os.makedirs(parent, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".exosat-json-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
            json.dump(_hashed_payload(payload), fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        # A hard-link publication is atomic and fails if ``final_path`` already exists.
        # The temporary file lives in the same directory, so this never crosses devices.
        os.link(temporary, final_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cache_matches(tag, expected_spec, min_rows=2):
    """A bare RVO is never a cache hit; its manifest and content hash must match."""
    output_path = rvo(tag)
    manifest_path = cache_manifest_path(tag)
    if not usable(output_path, min_rows=min_rows) or not os.path.exists(manifest_path):
        return False
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return False
    return (
        _valid_hashed_payload(manifest)
        and manifest.get("run") == expected_spec
        and manifest.get("output") == file_fingerprint(output_path)
    )


def _write_cache_manifest(tag, spec, log):
    path = cache_manifest_path(tag)
    payload = {
        "run": spec,
        "output": file_fingerprint(rvo(tag)),
        "artifacts": {
            "rvo": file_fingerprint(rvo(tag)),
            "par": file_fingerprint(par(tag)),
            "target_csv": file_fingerprint(tag + ".targ.csv"),
            "log": file_fingerprint(log),
        },
    }
    write_json_exclusive(path, payload)


def cache_audit_record(tag):
    """Return repo-safe hashes proving which external cache manifest backed a result."""
    path = cache_manifest_path(tag)
    record = {"tag": tag, "manifest": file_fingerprint(path)}
    if record["manifest"].get("missing"):
        return record
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        return record | {"valid": False, "error": str(exc)}
    return record | {
        "valid": _valid_hashed_payload(manifest),
        "manifest_payload_sha256": manifest.get("manifest_payload_sha256"),
        "run_spec_sha256": canonical_sha256(manifest.get("run")),
        "output": manifest.get("output"),
        "artifacts": manifest.get("artifacts"),
    }


def injected_template_paths(plan, template_dir):
    return [os.path.join(template_dir, f"inj{i:02d}_tpl.fits") for i in range(len(plan))]


def template_bundle_spec(plan, run_id, runtime_sha256):
    """Bind generated injection templates to their plan, source, and generator."""
    return {
        "schema_version": CACHE_SCHEMA,
        "run_id": validate_run_id(run_id),
        "runtime_identity_sha256": runtime_sha256,
        "plan_epochs": len(plan),
        "plan": file_fingerprint(PLAN),
        "source_template": file_fingerprint(os.path.join(VIPER, TPL)),
        "generator": file_fingerprint(os.path.join(SC, "mktpl.py")),
    }


def template_manifest_path(template_dir):
    return os.path.join(template_dir, ".exosat-template-cache.json")


def template_output_records(plan, template_dir):
    records = []
    for path in injected_template_paths(plan, template_dir):
        fingerprint = file_fingerprint(path)
        records.append(
            {
                "name": os.path.basename(path),
                "size": fingerprint.get("size"),
                "sha256": fingerprint.get("sha256"),
                "missing": fingerprint.get("missing", False),
            }
        )
    return records


def exact_template_bundle(plan, template_dir):
    """Require exactly the expected nonempty, regular, nonsymlink template files."""
    expected = {os.path.basename(path) for path in injected_template_paths(plan, template_dir)}
    actual = {
        name
        for name in os.listdir(template_dir)
        if name != os.path.basename(template_manifest_path(template_dir))
    }
    if actual != expected:
        return False
    return all(
        os.path.isfile(path) and not os.path.islink(path) and os.path.getsize(path) > 0
        for path in injected_template_paths(plan, template_dir)
    )


def template_bundle_matches(plan, template_dir, expected_spec):
    path = template_manifest_path(template_dir)
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return False
    outputs = template_output_records(plan, template_dir)
    return (
        exact_template_bundle(plan, template_dir)
        and all(not output.get("missing") for output in outputs)
        and _valid_hashed_payload(manifest)
        and manifest.get("run") == expected_spec
        and manifest.get("outputs") == outputs
    )


def ensure_injected_templates(plan, run_id, runtime_sha256):
    """Create a fresh run-specific bundle; never bless files in a mismatched directory."""
    final_dir = replay_template_dir(run_id)
    spec = template_bundle_spec(plan, run_id, runtime_sha256)
    if os.path.exists(final_dir):
        if template_bundle_matches(plan, final_dir, spec):
            return final_dir
        raise RuntimeError(
            f"template namespace exists without a matching manifest: {final_dir}; "
            "choose a new run ID"
        )

    parent = os.path.dirname(final_dir)
    os.makedirs(parent, exist_ok=True)
    staging_dir = tempfile.mkdtemp(prefix=".template-staging-", dir=parent)
    subprocess.check_call(
        [PY, os.path.join(SC, "mktpl.py"), PLAN, os.path.join(VIPER, TPL), staging_dir],
        cwd=VIPER,
    )
    outputs = template_output_records(plan, staging_dir)
    if not exact_template_bundle(plan, staging_dir):
        raise RuntimeError(f"template generator left an invalid staging directory: {staging_dir}")
    write_json_exclusive(template_manifest_path(staging_dir), {"run": spec, "outputs": outputs})
    os.rename(staging_dir, final_dir)
    if not template_bundle_matches(plan, final_dir, spec):
        raise RuntimeError("fresh template bundle failed its post-rename manifest check")
    return final_dir


def template_audit_record(template_dir):
    path = template_manifest_path(template_dir)
    record = {"manifest": file_fingerprint(path)}
    if record["manifest"].get("missing"):
        return record
    try:
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        return record | {"valid": False, "error": str(exc)}
    return record | {
        "valid": _valid_hashed_payload(manifest),
        "manifest_payload_sha256": manifest.get("manifest_payload_sha256"),
        "run_spec_sha256": canonical_sha256(manifest.get("run")),
        "outputs": manifest.get("outputs"),
    }


def viper(files, tag, cfg, log):
    """One viper invocation. ``files`` may be a glob for the whole series."""
    _ensure_target_csv(tag)
    cmd = build_viper_command(files, tag, cfg)
    with open(log, "w") as fh:
        return subprocess.call(cmd, cwd=VIPER, stdout=fh, stderr=subprocess.STDOUT)


def ensure_run(files, tag, cfg, log, run_id, runtime_sha256, min_rows=2):
    """Reuse only a content- and configuration-matched run; otherwise run fail-closed."""
    existing_products = [rvo(tag), par(tag), cache_manifest_path(tag)]
    if any(os.path.exists(path) for path in existing_products):
        _ensure_target_csv(tag)
        spec = run_spec(files, tag, cfg, run_id, runtime_sha256)
        if cache_matches(tag, spec, min_rows=min_rows):
            return True
        raise RuntimeError(
            f"replay namespace collision for {tag}; existing products do not match "
            "their immutable manifest, so choose a new run ID"
        )

    _ensure_target_csv(tag)
    spec = run_spec(files, tag, cfg, run_id, runtime_sha256)

    previous_output = file_fingerprint(rvo(tag))
    returncode = viper(files, tag, cfg, log)
    current_output = file_fingerprint(rvo(tag))
    if (
        returncode != 0
        or not usable(rvo(tag), min_rows=min_rows)
        or current_output == previous_output
    ):
        return False
    _write_cache_manifest(tag, spec, log)
    return cache_matches(tag, spec, min_rows=min_rows)


def rvo(tag):
    return os.path.join(VIPER, tag + ".rvo.dat")


def usable(path, min_rows=2):
    return (
        os.path.exists(path)
        and len([ln for ln in open(path).read().splitlines() if ln.strip()]) >= min_rows
    )


def score(arm, ref_path):
    """Recovery slope from the scorer's full-precision JSON report."""
    argv = [
        PY,
        os.path.join(SC, "inject_score2.py"),
        arm,
        ref_path,
        "--plan",
        PLAN,
        "--working-dir",
        VIPER,
        "--json",
    ]
    process = subprocess.run(
        argv,
        cwd=VIPER,
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        return (
            None,
            None,
            {
                "error": process.stderr or process.stdout,
                "invocation": {
                    "argv": argv,
                    "cwd": os.path.realpath(VIPER),
                    "returncode": process.returncode,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                },
            },
        )
    try:
        result = json.loads(process.stdout)
    except ValueError:
        return (
            None,
            None,
            {
                "error": "scorer did not return JSON",
                "invocation": {
                    "argv": argv,
                    "cwd": os.path.realpath(VIPER),
                    "returncode": process.returncode,
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                },
            },
        )
    result["invocation"] = {
        "argv": argv,
        "cwd": os.path.realpath(VIPER),
        "returncode": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
    }
    return result.get("slope"), result.get("slope_stderr"), result


def per_order_spread(result):
    vals = [row.get("slope") for row in result.get("per_order", [])]
    vals = [value for value in vals if value is not None]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    return (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5


def passes_registered_slope_gate(slope):
    """The M36 preregistration gates on slope alone; uncertainty is not post-hoc added."""
    return slope is not None and GATE_LO <= slope <= GATE_HI


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--run-id",
        help="required non-dry immutable replay ID (1-32 letters, digits, '_' or '-')",
    )
    args = parser.parse_args(argv)
    if not args.dry_run and not args.run_id:
        parser.error("--run-id is required for a non-dry post-audit replay")
    try:
        args.run_id = validate_run_id(args.run_id or "DRYRUN")
    except ValueError as exc:
        parser.error(str(exc))
    return args


def build_replay_payload(
    run_id,
    results,
    winner,
    elapsed_s,
    runtime,
    template_manifest,
    cache_manifests,
):
    """Assemble the complete repo-resident replay audit artifact."""
    return {
        "schema_version": 2,
        "execution_kind": "post-audit replay; not the preregistered M36 result",
        "run_id": run_id,
        "external_tag_namespace": replay_namespace(run_id),
        "historical_result": os.path.relpath(HISTORICAL_OUTPUT, _ROOT),
        "supersedes_historical_result": False,
        "grid": results,
        "winner": winner,
        "gate": [GATE_LO, GATE_HI],
        "gate_definition": "registered slope-only gate",
        "tie_break_window": TIE,
        "fixed_settings": FIXED_SETTINGS,
        "cache_schema": CACHE_SCHEMA,
        "runtime_identity_sha256": canonical_sha256(runtime),
        "runtime_identity": runtime,
        "template_manifest": template_manifest,
        "cache_manifests": cache_manifests,
        "driver": file_fingerprint(__file__),
        "scorer": file_fingerprint(os.path.join(SC, "inject_score2.py")),
        "plan": file_fingerprint(PLAN),
        "elapsed_s": round(elapsed_s),
    }


def main(argv=None):
    args = parse_args(argv)
    run_id = args.run_id
    with open(PLAN, encoding="utf-8") as fh:
        plan = json.load(fh)
    configs = grid(run_id)
    out = replay_output_path(run_id)
    print(f"M36: {len(configs)} configurations, {len(plan)} injected epochs each")
    print("selection = injection recovery only; no published RV table is loaded")
    print("warning = the registered injection plan is derived from the published orbit\n")
    print("POST-AUDIT REPLAY: this does not rehabilitate data/m36-selection.json")
    print(f"run ID = {run_id}")
    print(f"external namespace = {replay_namespace(run_id)}")
    print(f"new immutable output = {os.path.relpath(out, _ROOT)}\n")
    if args.dry_run:
        print(
            "held fixed: chunks={chunks} deg_norm={deg_norm} deg_wave={deg_wave} "
            "iset={iset} nocell={nocell}".format(**FIXED_SETTINGS)
        )
        for c in configs:
            print(
                f"  {c['arm']}  oset={c['oset']:<6} osamp={c['oversampling']} "
                f"kapsig={c['kapsig']:.1f} telluric={c['telluric']}"
            )
        example = dict(configs[0], _tpl=TPL)
        print("\nexample argv:")
        print(
            "  "
            + shlex.join(
                build_viper_command("cr2res_data/*.fits", f"{configs[0]['arm']}_ref", example)
            )
        )
        return

    raise RuntimeError(
        "non-dry M36 replay is disabled: complete per-invocation runtime provenance "
        "and repository-resident evidence are not implemented; use the successor "
        "protocol instead"
    )

    if os.path.exists(out):
        raise FileExistsError(f"immutable replay artifact already exists: {out}")

    runtime = runtime_identity()
    runtime_sha256 = canonical_sha256(runtime)

    # Injected templates are built once in a fresh run namespace and shared by every arm.
    # A mismatched or partial directory is never regenerated or blessed in place.
    template_dir = ensure_injected_templates(plan, run_id, runtime_sha256)
    template_manifest = template_audit_record(template_dir)

    results = []
    cache_manifests = []
    t0 = time.time()
    for c in configs:
        c["_tpl"] = TPL
        ref_tag = c["arm"] + "_ref"
        ref_path = rvo(ref_tag)
        if not ensure_run(
            "cr2res_data/*.fits",
            ref_tag,
            c,
            f"/tmp/{ref_tag}.log",
            run_id,
            runtime_sha256,
            min_rows=len(plan) + 1,
        ):
            ref_manifest = cache_audit_record(ref_tag)
            cache_manifests.append(ref_manifest)
            print(f"{c['arm']}  REFERENCE RUN FAILED -- ineligible")
            results.append(
                {k: v for k, v in c.items() if not k.startswith("_")}
                | {
                    "slope": None,
                    "eligible": False,
                    "note": "reference run failed",
                    "cache_manifests": {"reference": ref_manifest, "injections": []},
                }
            )
            continue
        ref_manifest = cache_audit_record(ref_tag)
        cache_manifests.append(ref_manifest)

        failed_injections = []
        injection_manifests = []
        for i, p in enumerate(plan):
            tag = f"{c['arm']}_inj{i:02d}"
            c["_tpl"] = os.path.join(template_dir, f"inj{i:02d}_tpl.fits")
            if not ensure_run(
                "cr2res_data/" + p["file"],
                tag,
                c,
                f"/tmp/{tag}.log",
                run_id,
                runtime_sha256,
            ):
                failed_injections.append(tag)
            manifest = cache_audit_record(tag)
            injection_manifests.append(manifest)
            cache_manifests.append(manifest)
        c["_tpl"] = TPL
        if failed_injections:
            print(f"{c['arm']}  {len(failed_injections)} INJECTION RUN(S) FAILED -- ineligible")
            results.append(
                {k: v for k, v in c.items() if not k.startswith("_")}
                | {
                    "slope": None,
                    "eligible": False,
                    "note": "injection runs failed",
                    "failed_injections": failed_injections,
                    "cache_manifests": {
                        "reference": ref_manifest,
                        "injections": injection_manifests,
                    },
                }
            )
            continue

        slope, se, score_result = score(c["arm"], ref_path)
        spread = per_order_spread(score_result)
        complete = score_result.get("n_epochs") == len(plan)
        eligible = complete and passes_registered_slope_gate(slope)
        recovery = f"{slope:.3f} +- {se:.3f}" if slope is not None else "  n/a  "
        status = "eligible" if eligible else "INELIGIBLE"
        print(
            f"{c['arm']}  oset={c['oset']:<6} osamp={c['oversampling']} "
            f"kap={c['kapsig']:.1f} tel={c['telluric']:<4}  recovery={recovery}  {status}"
        )
        results.append(
            {k: v for k, v in c.items() if not k.startswith("_")}
            | {
                "slope": slope,
                "slope_err": se,
                "per_order_spread": spread,
                "eligible": bool(eligible),
                "ref_series": ref_tag,
                "scored_epochs": score_result.get("n_epochs"),
                "score": score_result,
                "cache_manifests": {"reference": ref_manifest, "injections": injection_manifests},
            }
        )

    ok = [r for r in results if r["eligible"]]
    print(
        f"\n{len(ok)} of {len(results)} configurations eligible "
        f"(gate: slope in [{GATE_LO:.2f}, {GATE_HI:.2f}])"
    )
    winner = None
    if ok:
        best = min(abs(r["slope"] - 1.0) for r in ok)
        tied = [r for r in ok if abs(r["slope"] - 1.0) <= best + TIE]
        winner = min(
            tied, key=lambda r: r["per_order_spread"] if r["per_order_spread"] is not None else 9e9
        )
        spread_text = (
            f"{winner['per_order_spread']:.3f}" if winner["per_order_spread"] is not None else "n/a"
        )
        print(
            f"winner: {winner['arm']}  (slope {winner['slope']:.3f}, "
            f"|slope-1| {abs(winner['slope'] - 1.0):.3f}, "
            f"per-order spread {spread_text})"
        )
        if len(tied) > 1:
            print(
                f"  ({len(tied)} configurations tied within {TIE:.3f}; broken on per-order spread)"
            )
    else:
        print("NO configuration passed the gate. Per the protocol the experiment stops here.")

    payload = build_replay_payload(
        run_id,
        results,
        winner,
        time.time() - t0,
        runtime,
        template_manifest,
        cache_manifests,
    )
    write_json_exclusive(out, payload)
    print(f"\nwrote {os.path.relpath(out, _ROOT)} in {int(time.time() - t0)} s")
    if winner:
        print("\nReplay winner recorded. No period search is authorised by this runner.")


if __name__ == "__main__":
    main()
