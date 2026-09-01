"""M37: freeze the load-bearing VIPER products used by the downstream analyses.

The project's raw CRIRES products, reduced spectra, and fitted templates are too large (and,
for ESO products, not ours to redistribute here).  The small VIPER result tables were also
kept outside the repository, however, which meant that even the downstream period, BERV,
jackknife, and limit calculations could not be rerun from a clone.

This script copies the four adopted result series, their per-order fit tables, target
sidecars, and the VIPER configuration observed in the audited checkout into ``data/repro``.
It fails closed unless every source has the hash recorded during the 2026-08-31 audit and the
VIPER checkout is at the audited commit with the audited tracked patch.  The observed
configuration records checkout state; it does not prove which configuration governed the
historical extraction runs.  Templates and the 74 MB FTS atlas remain external; their hashes
are recorded in the generated manifest.

Package from the audited WSL checkout::

    ~/viperenv/bin/python scripts/m37_package_evidence.py --viper-root ~/viper-src

Verify a repository clone without VIPER or the external products::

    python scripts/m37_package_evidence.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "repro"

VIPER_REPOSITORY = "https://github.com/mzechmeister/viper"
VIPER_COMMIT = "e8b22fa7489a9357e3b1936c54d54f86313dc129"
VIPER_PATCH_SHA256 = "7e6253f0d712cd48cf345ce941800d78610491b81f43461c3d52184e6b1642ba"
VIPER_PATCH_SIZE = 2681
VIPER_PATCH_FILES = ("utils/gplot.py", "viper.py")
EXPECTED_TRACKED_STATUS = {" M utils/gplot.py", " M viper.py"}


@dataclass(frozen=True)
class EvidenceFile:
    source: str
    destination: str | None
    size: int
    sha256: str
    role: str


INCLUDED_FILES = (
    EvidenceFile(
        "M14_NODT2.rvo.dat",
        "viper/results/M14_NODT2.rvo.dat",
        18_383,
        "b46585784888d8883bcfaa2020178695a6fff0b05e8f2408af698075efc87939",
        "CD-35 2722 B adopted per-nodding RV series",
    ),
    EvidenceFile(
        "M14_NODT2.par.dat",
        "viper/results/M14_NODT2.par.dat",
        201_308,
        "88fbeb9230fbd1b53ee9025f0009caed92cd7a69917bd5a97aad30b445e0fa4e",
        "CD-35 2722 B adopted per-nodding per-order fit parameters",
    ),
    EvidenceFile(
        "M14_NODT2.targ.csv",
        "viper/results/M14_NODT2.targ.csv",
        197,
        "b633fee597810a78ec482b439f84bd5f2531d59f5b308e18cc95c481e86bc465",
        "CD-35 2722 B target metadata used by VIPER",
    ),
    EvidenceFile(
        "M14_T2.rvo.dat",
        "viper/results/M14_T2.rvo.dat",
        9_564,
        "e450f10717f0fcadc88487100bd3e8c78f4127c57733783a777fca312e3501c7",
        "CD-35 2722 B adopted per-epoch RV series",
    ),
    EvidenceFile(
        "M14_T2.par.dat",
        "viper/results/M14_T2.par.dat",
        100_810,
        "4ce45c14159e079086828e8ffb0eab122b8c12e72681c3cf6e4446fd672a1a52",
        "CD-35 2722 B adopted per-epoch per-order fit parameters",
    ),
    EvidenceFile(
        "M14_T2.targ.csv",
        "viper/results/M14_T2.targ.csv",
        197,
        "b633fee597810a78ec482b439f84bd5f2531d59f5b308e18cc95c481e86bc465",
        "CD-35 2722 B target metadata used by VIPER",
    ),
    EvidenceFile(
        "E15_NOD.rvo.dat",
        "viper/results/E15_NOD.rvo.dat",
        19_818,
        "5c1b4935e418991436f967b76ba01c5562e3b46d100b286843dda6cff1b6b53c",
        "eta Tel B adopted per-nodding RV series",
    ),
    EvidenceFile(
        "E15_NOD.par.dat",
        "viper/results/E15_NOD.par.dat",
        222_328,
        "8b9a9f31534e71cf7c49daf94a470f4626998a17897b7133ed9a9f1c194b4bd5",
        "eta Tel B adopted per-nodding per-order fit parameters",
    ),
    EvidenceFile(
        "E15_NOD.targ.csv",
        "viper/results/E15_NOD.targ.csv",
        165,
        "27d0d18e9ea2670cdc8a9971cd81506ec0028bfd2c45eb4036252e21cbb8bcbc",
        "eta Tel B target metadata used by VIPER",
    ),
    EvidenceFile(
        "E15_R2.rvo.dat",
        "viper/results/E15_R2.rvo.dat",
        10_360,
        "536101a949a8f2608c9671a654e19c0a74028f4ae157591a1a604710d57b6c52",
        "eta Tel B adopted per-epoch RV series",
    ),
    EvidenceFile(
        "E15_R2.par.dat",
        "viper/results/E15_R2.par.dat",
        110_632,
        "20041b14b63a68d67595b433d131e83d5f7b2518e56382ed41366560d18f3cce",
        "eta Tel B adopted per-epoch per-order fit parameters",
    ),
    EvidenceFile(
        "E15_R2.targ.csv",
        "viper/results/E15_R2.targ.csv",
        165,
        "27d0d18e9ea2670cdc8a9971cd81506ec0028bfd2c45eb4036252e21cbb8bcbc",
        "eta Tel B target metadata used by VIPER",
    ),
    EvidenceFile(
        "config_viper.ini",
        "viper/config_viper.ini",
        3_135,
        "24c1a73fbfe07dc26cdaa35387fb03eb7c0a455e0b1c871f57d30c2a834bd2c6",
        "VIPER configuration present in the audited checkout",
    ),
)

HASH_ONLY_FILES = (
    EvidenceFile(
        "M13tpl_tpl.fits",
        None,
        1_074_240,
        "50baff2f024fbc358c4e92b423078ebb42a860547a4081314f28838dbd3707aa",
        "CD-35 2722 B iteration-1 fitted template",
    ),
    EvidenceFile(
        "M14tpl2_tpl.fits",
        None,
        1_074_240,
        "7a1a638cee0b86bb7285672c89b638d170455ef802a92a456aabf320fbc8ec4d",
        "CD-35 2722 B iteration-2 fitted template",
    ),
    EvidenceFile(
        "E15tpl2_tpl.fits",
        None,
        1_074_240,
        "1ba34749c7fbffd1d7f2a343f08e909dbb624d16bc98c40859852288ee821620",
        "eta Tel B iteration-2 fitted template",
    ),
    EvidenceFile(
        "lib/CRIRES/FTS/CRp_SGC2_FTStmpl-HR0p007-WN5000-10000_Hband.dat",
        None,
        74_354_167,
        "ed7a7431d95cb63946af6ba7593ee1bd7373d34f96e6362750e26a74c555ed83",
        "H-band FTS atlas passed explicitly to VIPER",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path: Path, *, size: int, sha256: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_size = path.stat().st_size
    if actual_size != size:
        raise RuntimeError(f"size drift for {path}: expected {size}, got {actual_size}")
    actual_hash = sha256_file(path)
    if actual_hash != sha256:
        raise RuntimeError(f"hash drift for {path}: expected {sha256}, got {actual_hash}")


def _git(viper_root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(viper_root), *arguments], stderr=subprocess.STDOUT
    )


def _record(spec: EvidenceFile, *, included: bool) -> dict[str, object]:
    record: dict[str, object] = {
        "logical_source": f"~/viper-src/{spec.source}",
        "role": spec.role,
        "sha256": spec.sha256,
        "size_bytes": spec.size,
    }
    if included:
        record["path"] = spec.destination
    return record


def _bundle_digest(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: str(item["path"])):
        digest.update(str(record["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _expected_included_records() -> list[dict[str, object]]:
    records = [_record(spec, included=True) for spec in INCLUDED_FILES]
    records.append(
        {
            "logical_source": "git diff of audited VIPER tracked worktree",
            "path": "viper/viper-tracked.patch",
            "role": (
                "tracked modifications present in the audited checkout; "
                "application date unknown"
            ),
            "sha256": VIPER_PATCH_SHA256,
            "size_bytes": VIPER_PATCH_SIZE,
        }
    )
    return records


def _expected_manifest() -> dict[str, object]:
    included_records = _expected_included_records()
    manifest: dict[str, object] = {
        "schema_version": 1,
        "scope": {
            "supports": [
                "offline downstream reanalysis of the adopted CD-35 2722 B RV tables",
                "offline downstream reanalysis of the adopted eta Tel B RV tables",
                "verification of VIPER source/configuration/template/FTS identities observed during the audit",
            ],
            "does_not_support": [
                "raw ESO exposure to reduced-spectrum replay",
                "rebuilding the fitted templates, which are hash-only here",
                "claiming that the packaging environment was the historical run environment",
                "proving when the audited VIPER patch/configuration was applied relative to the historical runs",
            ],
        },
        "viper": {
            "repository": VIPER_REPOSITORY,
            "commit": VIPER_COMMIT,
            "tracked_status": sorted(EXPECTED_TRACKED_STATUS),
            "untracked_files_enumerated": False,
        },
        "included_files": included_records,
        "external_hash_only_files": [
            _record(spec, included=False) for spec in HASH_ONLY_FILES
        ],
        "bundle_sha256": _bundle_digest(included_records),
    }
    return manifest


def validate_manifest_contract(manifest: dict[str, object]) -> None:
    """Reject a self-consistent manifest that no longer matches the audited contract."""
    expected = _expected_manifest()
    if manifest != expected:
        raise RuntimeError(
            "manifest contract drift: records or audit metadata differ from the "
            "packager's pinned evidence specification"
        )


def package(viper_root: Path, output: Path) -> Path:
    viper_root = viper_root.expanduser().resolve()
    output = output.resolve()

    head = _git(viper_root, "rev-parse", "HEAD").decode().strip()
    if head != VIPER_COMMIT:
        raise RuntimeError(f"VIPER commit drift: expected {VIPER_COMMIT}, got {head}")

    status = {
        line
        for line in _git(viper_root, "status", "--porcelain=v1", "--untracked-files=no")
        .decode()
        .splitlines()
        if line
    }
    if status != EXPECTED_TRACKED_STATUS:
        raise RuntimeError(
            "VIPER tracked worktree drift: expected "
            f"{sorted(EXPECTED_TRACKED_STATUS)}, got {sorted(status)}"
        )

    for spec in (*INCLUDED_FILES, *HASH_ONLY_FILES):
        verify_file(viper_root / spec.source, size=spec.size, sha256=spec.sha256)

    patch = _git(
        viper_root,
        "diff",
        "--binary",
        "--no-ext-diff",
        "--",
        *VIPER_PATCH_FILES,
    )
    patch_hash = hashlib.sha256(patch).hexdigest()
    if len(patch) != VIPER_PATCH_SIZE or patch_hash != VIPER_PATCH_SHA256:
        raise RuntimeError(
            "VIPER patch drift: expected "
            f"{VIPER_PATCH_SIZE} bytes/{VIPER_PATCH_SHA256}, got {len(patch)} bytes/{patch_hash}"
        )

    included_records: list[dict[str, object]] = []
    for spec in INCLUDED_FILES:
        assert spec.destination is not None
        destination = output / spec.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(viper_root / spec.source, destination)
        verify_file(destination, size=spec.size, sha256=spec.sha256)
        included_records.append(_record(spec, included=True))

    patch_destination = output / "viper" / "viper-tracked.patch"
    patch_destination.parent.mkdir(parents=True, exist_ok=True)
    patch_destination.write_bytes(patch)
    verify_file(
        patch_destination,
        size=VIPER_PATCH_SIZE,
        sha256=VIPER_PATCH_SHA256,
    )
    included_records.append(
        {
            "logical_source": "git diff of audited VIPER tracked worktree",
            "path": "viper/viper-tracked.patch",
            "role": "tracked modifications present in the audited checkout; application date unknown",
            "sha256": VIPER_PATCH_SHA256,
            "size_bytes": VIPER_PATCH_SIZE,
        }
    )

    expected_records = _expected_included_records()
    if included_records != expected_records:
        raise RuntimeError("internal evidence-record construction drift")
    manifest = _expected_manifest()

    manifest_path = output / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    verify_bundle(output)
    return manifest_path


def verify_bundle(output: Path, *, enforce_contract: bool = True) -> dict[str, object]:
    output = output.resolve()
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if enforce_contract:
        validate_manifest_contract(manifest)
    records = manifest["included_files"]
    for record in records:
        verify_file(
            output / record["path"],
            size=record["size_bytes"],
            sha256=record["sha256"],
        )
    actual_digest = _bundle_digest(records)
    if actual_digest != manifest["bundle_sha256"]:
        raise RuntimeError(
            "bundle digest drift: expected "
            f"{manifest['bundle_sha256']}, got {actual_digest}"
        )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--viper-root",
        type=Path,
        default=Path("~/viper-src").expanduser(),
        help="audited VIPER checkout (default: ~/viper-src)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="bundle directory (default: data/repro)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify the existing bundle without reading the VIPER checkout",
    )
    args = parser.parse_args()

    if args.verify:
        manifest = verify_bundle(args.output)
        print(
            f"verified {len(manifest['included_files'])} files; "
            f"bundle sha256 {manifest['bundle_sha256']}"
        )
    else:
        manifest_path = package(args.viper_root, args.output)
        print(f"wrote and verified {manifest_path}")


if __name__ == "__main__":
    main()
