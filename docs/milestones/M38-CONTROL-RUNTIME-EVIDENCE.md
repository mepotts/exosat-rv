# M38 target-free runtime probe — engineering evidence only

> **NOT A PREREGISTRATION / NOT A SCIENTIFIC RUNTIME / NO TARGET AUTHORITY**
>
> This record covers the initial 2026-09-01 identity probe and the 2026-09-02 sealed-context
> follow-up, both built from the dedicated five-file context. The repository root was not used
> as the Docker build context, no host path was mounted, and no target spectrum, target-derived
> product, or target diagnostic was opened.

## Bound build inputs

The static allowlist audit of `containers/m38/` produced:

- context SHA-256:
  `6003dca1276828526f8b57affd1ecc4b11fdb23978bb6925aa0d02f748a7beda`;
- audit SHA-256:
  `712fa445db8e2a956599ff3beed43729f6b755bb936b2c0d73ee5ec2900bded7`;
- pinned base image:
  `python:3.11-slim@sha256:233de06753d30d120b1a3ce359d8d3be8bda78524cd8f520c99883bfe33964cf`;
  and
- runtime-contract SHA-256:
  `3f53f6eafff880b8bd90d39619c470426f5a6068995e7404b605f4d2327175e9`.

The five accepted context files were independently content-pinned by the runtime policy:

| path | bytes | SHA-256 |
|---|---:|---|
| `.dockerignore` | 93 | `b7675ed240df7cc5362d2c17167ba6fbb15e5699f17929a0eada047692e12f39` |
| `.m38-target-free-context` | 43 | `1c6ececdbc94142063514808185676e29c99e299ae489126b236d39c9c568ee2` |
| `Dockerfile` | 389 | `486a855b13d5a8e1646cbea480df76ef59f8714e2e4c1cade485bbfbb7ddee51` |
| `entrypoint.py` | 1264 | `bc74902b627b3aabaa352e77d803be46ce493126d711260559537700944fb633` |
| `runtime-contract.json` | 664 | `3f53f6eafff880b8bd90d39619c470426f5a6068995e7404b605f4d2327175e9` |

The build requested network mode `none` for Dockerfile `RUN` instructions and set
`--pull=false`, meaning “do not always pull.” This Dockerfile has no `RUN` instruction, but
those flags did not independently disable or measure builder registry egress. The recorded
local Docker image identity is
`sha256:e1f066f38b8e4785bfca460a5498535b0dac327add4e46fdca57c5f38fe4b384`.
The exact build invocation, image/platform inspection, container settings, probe output, and
exit state are also retained as a strict JSON
[engineering observation](../evidence/m38-runtime-observation-2026-09-01.json), whose file
SHA-256 is `06667e5b33ec281c1b99ad8c50c04d1c5149006660ab5b6ce66c136297cdc65d`.
That record is deliberately marked unauthenticated; committing it makes the local observation
auditable but does not turn it into an external signature or a cryptographic build attestation.

## Inspected launch contract and observation

Before execution, Docker reported the following exact configuration for a disposable
container:

- network mode `none`;
- read-only root filesystem `true`;
- user and group `65532:65532`;
- capability drop `ALL`;
- security option `no-new-privileges:true`;
- sole temporary filesystem `/tmp:rw,noexec,nosuid,nodev,size=64m`; and
- entrypoint `python -I /opt/m38/entrypoint.py`.

The one-shot probe exited zero, was not OOM-killed, and emitted a strict JSON observation with
effective UID/GID `65532:65532`, the expected contract digest, and status `ready`. The
disposable stopped container was then removed; the tagged local image remains available as
build evidence.

## Sealed-context follow-up (2026-09-02)

Commit `63d1deecc2794b4fd400688bd5b4b00dd14a97df` adds a caller-side canonical build
transaction. It re-audits the same five files, encodes them as deterministic USTAR bytes, and
passes those exact immutable bytes to `docker buildx build` on standard input. The observed
context tar was 10,240 bytes with SHA-256
`f95612d175d1953d6d255d2c72d5c6bd5cc84e5446b42998727f8bb5b54de656`; its complete
seal identity was `546258906a488b387bec8159c26c1b88c1611533150bebc36e283585a6e14757`.

The fresh BuildKit metadata reported that same context digest, the pinned base-material digest,
`linux/amd64`, `Dockerfile`, and `force-network-mode=none`. The IID file and metadata both
bound local image ID
`sha256:b3c4ae1c307d43d47367089870fd1b12f101473c179ff68265a6d03ba52cdd0e`.
The IID and metadata outputs used the neutral temporary path
`C:\Users\Public\m38-sealed-build-evidence-20260902`; that directory was removed after its
contents were captured.
An inspected disposable container again had no host mounts, network mode `none`, a read-only
root, user `65532:65532`, all capabilities dropped, no-new-privileges, and only the contracted
`/tmp` tmpfs. The identity probe exited zero and the container was removed.

The strict [sealed observation](../evidence/m38-sealed-runtime-observation-2026-09-02.json)
has file SHA-256 `dcabf042342d629d8d5370b35d07b9d1850005075f4ea4741b03d0173602b9d5`.
The semantically identical, normalized copy of the
[raw BuildKit metadata](../evidence/m38-sealed-buildkit-metadata-2026-09-02.json) has file
SHA-256 `2184526bb8123efbdc430753d22293815397f512ed4397c158e914e3c81ef1ef`;
the exact builder-emitted bytes are separately bound in the observation by SHA-256
`5f1c7c8424e996e4d611b88fee803b857f55616a204537bda0a749582ae0e970`.

This also exposed a reproducibility limit: two earlier builds of the identical sealed tar had
local OCI image IDs `sha256:93d2db084d1634e61e2161c3426ba96118678cb223431c84256d4c1dc8c98401`
and `sha256:9d1216f597da329605d7bcfed7f0a849a13abe4e0735b7ae2100623b2ae2a54e`.
The six rootfs layer identities were identical across all three observations, and every
observed layer list is retained in the strict JSON record, but the reported OCI image IDs
differed. Therefore neither bit-reproducible image identity nor an exact frozen scientific
image is claimed.

## What this does not prove

This probe demonstrates that the dedicated context is small, content-bound, that the observed
build completed without any Dockerfile `RUN` instruction, and that the resulting image can be
launched with the declared Docker restrictions. It does **not** prove that the builder made no
registry connection. Nor does it prove observer
blindness, immutable external storage, a cold full-pipeline rebuild, a production signing or
timestamp scheme, scientific dependency completeness, or resistance to a hostile Docker
administrator or host kernel. The root `uv.lock` is a reproducibility input for later
control-only development, but the probe image intentionally does not install the project or
claim to be the frozen M38 scientific runtime.

The original 2026-09-01 static audit observed a mutable directory and was not a cryptographic
transaction with its later Docker build. The 2026-09-02 follow-up closes that local caller-side
handoff by hashing and streaming one canonical tar, and it validates the bindings reported by
BuildKit. It still cannot make the same-host Docker daemon truthful, disable or measure registry
egress, authenticate the metadata, or produce an external timestamp/signature. A production
route must issue an independently verified attestation binding the context hash, platform,
build invocation, dependency set, and resulting image identity, and must resolve the observed
whole-image reproducibility gap.

Any future image that adds code, dependencies, controls, mounts, or output handling is a new
artifact. It must receive a new allowlist/content audit, independent review, and runtime
observation before it can be named in a replacement preregistration. Target mounting remains
forbidden until every M38 blocking decision is independently closed and frozen.
