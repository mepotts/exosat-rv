# M38 target-free runtime prototype

The `m38/` directory contains a minimal Docker bootstrap, entrypoint, and runtime contract for
testing restricted execution and content identity. It is **not** a production CR2RES/VIPER
image and does not authorize mounting target data.

Read [runtime evidence](../docs/milestones/M38-CONTROL-RUNTIME-EVIDENCE.md) and the
[control-development checkpoint](../docs/milestones/M38-CONTROL-DEVELOPMENT.md) before use.
The M38 sealed-context builder selects and hash-binds an explicit file allowlist; this guide
is kept in the parent directory, outside that exact five-file context. Do not add a README
or any other file inside `m38/`, and do not replace that build context with
the full repository, which contains target-aware historical material.

Scientific software/dependency identity, suitable controls, calibrated decision rules, and
independent review remain separate requirements in the
[draft protocol](../docs/milestones/M38-PROTOCOL-DRAFT.md).
