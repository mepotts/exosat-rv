# M38 target-free runtime probe — engineering evidence only

> **NOT A PREREGISTRATION / NOT A SCIENTIFIC RUNTIME / NO TARGET AUTHORITY**
>
> This record covers a minimal identity probe built from a dedicated five-file context on
> 2026-09-01. The repository root was not used as the Docker build context, no host path was
> mounted, and no target spectrum, target-derived product, or target diagnostic was opened.

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

The static audit also observes a mutable directory; it is not a cryptographic transaction with
the later Docker build. Although this build followed the audit and its resulting image digest
was recorded, the current machinery cannot prove that no bytes changed between those events or
that another builder used the audited directory. A production route must build from a sealed,
content-addressed read-only snapshot and issue an externally verified attestation binding the
context hash, platform, build invocation, and resulting image digest.

Any future image that adds code, dependencies, controls, mounts, or output handling is a new
artifact. It must receive a new allowlist/content audit, independent review, and runtime
observation before it can be named in a replacement preregistration. Target mounting remains
forbidden until every M38 blocking decision is independently closed and frozen.
