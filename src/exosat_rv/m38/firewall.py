"""Application-level information-firewall primitives for control-only M38 work.

This is a guardrail, not a security boundary.  It does not disable networking, sandbox a
process, intercept ordinary ``open`` calls, or stop code from using another I/O API.  The
runnable image/container must provide OS-level confinement, and application code must route
every permitted file read and every emitted payload through this module.

Path resolution, reopen, and hash comparison reduce accidental TOCTOU exposure but cannot
defeat a hostile or privileged filesystem namespace.  Trusted directories and OS/container
controls remain mandatory.

All rules are caller supplied.  This module intentionally contains no target names, paper
values, scientific thresholds, or repository-specific deny strings.
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import math
import os
import threading
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, NoReturn, TextIO

Clock = Callable[[], str]
_MAX_JSON_NESTING = 256


class FirewallViolation(PermissionError):
    """Raised before access or emission when an information-firewall rule fails."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalise_reason_rules(
    rules: Mapping[Any, str] | Iterable[Any] | None,
    *,
    default_reason: str,
) -> list[tuple[Any, str]]:
    if rules is None:
        return []
    if isinstance(rules, Mapping):
        return [(value, str(reason)) for value, reason in rules.items()]
    return [(value, default_reason) for value in rules]


def _normalised_sha256(value: Any) -> str:
    result = str(value).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise ValueError(f"invalid SHA-256 deny rule: {value!r}")
    return result


@dataclass(frozen=True)
class FileAccess:
    """The exact file identity approved by a preflight."""

    resolved_path: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def _normalise_output_json(
    value: Any,
    *,
    location: str = "$",
    active_containers: set[int] | None = None,
    depth: int = 0,
) -> Any:
    """Return detached JSON data, normalising tuples and rejecting ambiguous objects."""

    if depth > _MAX_JSON_NESTING:
        raise FirewallViolation(
            f"output exceeds maximum nesting depth {_MAX_JSON_NESTING} at {location}"
        )
    value_type = type(value)
    if value is None or value_type in {bool, int, str}:
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise FirewallViolation(f"output contains a non-finite number at {location}")
        return value
    if value_type in {list, tuple, dict}:
        active = set() if active_containers is None else active_containers
        identity = id(value)
        if identity in active:
            raise FirewallViolation(f"output contains a reference cycle at {location}")
        active.add(identity)
        try:
            if value_type in {list, tuple}:
                return [
                    _normalise_output_json(
                        child,
                        location=f"{location}[{index}]",
                        active_containers=active,
                        depth=depth + 1,
                    )
                    for index, child in enumerate(value)
                ]
            detached: dict[str, Any] = {}
            folded_keys: dict[str, str] = {}
            for key, child in value.items():
                if type(key) is not str:
                    raise FirewallViolation(
                        f"output mapping keys must be native strings at {location}"
                    )
                folded = key.casefold()
                if folded in folded_keys:
                    raise FirewallViolation(
                        "output mapping has case-insensitive duplicate fields at "
                        f"{location}: {folded_keys[folded]!r} and {key!r}"
                    )
                folded_keys[folded] = key
                detached[key] = _normalise_output_json(
                    child,
                    location=f"{location}.{key}",
                    active_containers=active,
                    depth=depth + 1,
                )
            return detached
        finally:
            active.remove(identity)
    raise FirewallViolation(
        f"output contains non-native JSON type {value_type.__name__} at {location}"
    )


def _walk_output_fields(value: Any, prefix: str = "") -> Iterable[tuple[str, str]]:
    if type(value) is dict:
        for key, child in value.items():
            dotted = f"{prefix}.{key}" if prefix else key
            yield dotted, key
            yield from _walk_output_fields(child, dotted)
    elif type(value) is list:
        for index, child in enumerate(value):
            indexed = f"{prefix}[{index}]"
            yield from _walk_output_fields(child, indexed)


def enforce_output_fields(
    payload: Mapping[str, Any],
    *,
    allowed_top_level_fields: Iterable[str] | None = None,
    denied_fields: Mapping[str, str] | Iterable[str] = (),
) -> dict[str, Any]:
    """Validate, detach, and enforce case-insensitive stage-output field rules."""

    if type(payload) is not dict:
        raise FirewallViolation("stage output must be a native JSON object")
    normalised = _normalise_output_json(payload)
    assert type(normalised) is dict

    if allowed_top_level_fields is not None:
        allowed = {field.casefold() for field in allowed_top_level_fields}
        unexpected = sorted(key for key in normalised if key.casefold() not in allowed)
        if unexpected:
            raise FirewallViolation(f"output contains fields outside the allowlist: {unexpected}")

    deny_rules = _normalise_reason_rules(
        denied_fields,
        default_reason="forbidden stage-output field",
    )
    for dotted, leaf in _walk_output_fields(normalised):
        folded_path = dotted.casefold()
        folded_leaf = leaf.casefold()
        for pattern, reason in deny_rules:
            folded_pattern = str(pattern).casefold()
            if fnmatch.fnmatchcase(folded_path, folded_pattern) or fnmatch.fnmatchcase(
                folded_leaf, folded_pattern
            ):
                raise FirewallViolation(f"{reason}: {dotted}")
    return normalised


class InformationFirewall:
    """Fail-closed checked reads, access logging, and stage-output field barriers."""

    def __init__(
        self,
        *,
        allowed_roots: Iterable[str | os.PathLike[str]],
        allowed_files: Iterable[str | os.PathLike[str]] = (),
        denied_paths: Mapping[str | os.PathLike[str], str] | Iterable[str | os.PathLike[str]] = (),
        denied_path_patterns: Mapping[str, str] | Iterable[str] = (),
        denied_content: Mapping[str | bytes, str] | Iterable[str | bytes] = (),
        denied_hashes: Mapping[str, str] | Iterable[str] = (),
        allowed_output_fields: Iterable[str] | None = None,
        denied_output_fields: Mapping[str, str] | Iterable[str] = (),
        access_log_path: str | os.PathLike[str] | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self._allowed_roots_lexical: list[Path] = []
        self._allowed_roots_resolved: list[Path] = []
        for root_value in allowed_roots:
            lexical = _absolute(Path(root_value))
            if lexical.is_symlink() or not lexical.is_dir():
                raise ValueError(
                    f"allowed root must be an existing nonsymlink directory: {root_value}"
                )
            self._allowed_roots_lexical.append(lexical)
            self._allowed_roots_resolved.append(lexical.resolve(strict=True))

        self._allowed_files_lexical: set[Path] = set()
        self._allowed_files_resolved: set[Path] = set()
        for file_value in allowed_files:
            lexical = _absolute(Path(file_value))
            if lexical.is_symlink() or not lexical.is_file():
                raise ValueError(f"allowed file must be an existing nonsymlink file: {file_value}")
            self._allowed_files_lexical.add(lexical)
            self._allowed_files_resolved.add(lexical.resolve(strict=True))
        if not self._allowed_roots_lexical and not self._allowed_files_lexical:
            raise ValueError("at least one allowed root or file is required")

        self._denied_paths: list[tuple[Path, str]] = []
        for path_value, reason in _normalise_reason_rules(
            denied_paths,
            default_reason="explicitly denied path",
        ):
            self._denied_paths.append((_absolute(Path(path_value)).resolve(strict=False), reason))
        self._denied_path_patterns = [
            (str(pattern).replace("\\", "/").casefold(), reason)
            for pattern, reason in _normalise_reason_rules(
                denied_path_patterns,
                default_reason="denied path pattern",
            )
        ]
        self._denied_content: list[tuple[bytes, str]] = []
        for pattern, reason in _normalise_reason_rules(
            denied_content,
            default_reason="denied content pattern",
        ):
            encoded = pattern.encode("utf-8") if isinstance(pattern, str) else bytes(pattern)
            if not encoded:
                raise ValueError("denied content patterns cannot be empty")
            self._denied_content.append((encoded, reason))
        self._denied_hashes = {
            _normalised_sha256(digest): reason
            for digest, reason in _normalise_reason_rules(
                denied_hashes,
                default_reason="denied content hash",
            )
        }
        self._allowed_output_fields = (
            tuple(allowed_output_fields) if allowed_output_fields is not None else None
        )
        self._denied_output_fields = {
            str(pattern): reason
            for pattern, reason in _normalise_reason_rules(
                denied_output_fields,
                default_reason="forbidden stage-output field",
            )
        }
        self._log_path = Path(access_log_path) if access_log_path is not None else None
        self._clock = clock
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def access_log(self) -> tuple[dict[str, Any], ...]:
        """Return a detached snapshot of all allow/deny decisions."""

        with self._lock:
            return tuple(json.loads(json.dumps(event)) for event in self._events)

    def _log(self, *, operation: str, decision: str, **details: Any) -> None:
        with self._lock:
            event = {
                "decision": decision,
                "operation": operation,
                "sequence": len(self._events),
                "timestamp": self._clock(),
                **details,
            }
            self._events.append(event)
            if self._log_path is not None:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                encoded = (
                    json.dumps(
                        event,
                        allow_nan=False,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                    + b"\n"
                )
                descriptor = os.open(
                    self._log_path,
                    os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                    0o600,
                )
                with os.fdopen(descriptor, "ab") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())

    def _deny(self, path: Path, reason: str) -> NoReturn:
        self._log(
            operation="open",
            decision="denied",
            path=str(path),
            reason=reason,
        )
        raise FirewallViolation(reason)

    def _lexical_root_for(self, candidate: Path) -> Path | None:
        for root in self._allowed_roots_lexical:
            if _is_relative_to(candidate, root):
                return root
        return None

    def _reject_symlinks(self, candidate: Path, lexical_root: Path | None) -> None:
        if candidate in self._allowed_files_lexical:
            if candidate.is_symlink():
                self._deny(candidate, "allowed-file path became a symlink")
            return
        if lexical_root is None:
            return
        cursor = lexical_root
        for component in candidate.relative_to(lexical_root).parts:
            cursor /= component
            if cursor.is_symlink():
                self._deny(candidate, f"symlink component is forbidden: {cursor}")

    def _path_rule_reason(self, lexical: Path, resolved: Path) -> str | None:
        for denied, reason in self._denied_paths:
            if resolved == denied or lexical == denied:
                return reason
        candidates = {
            lexical.as_posix().casefold(),
            resolved.as_posix().casefold(),
            lexical.name.casefold(),
            resolved.name.casefold(),
        }
        for root in self._allowed_roots_lexical:
            if _is_relative_to(lexical, root):
                candidates.add(lexical.relative_to(root).as_posix().casefold())
        for pattern, reason in self._denied_path_patterns:
            if any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
                return reason
        return None

    def _hash_and_scan(self, path: Path) -> tuple[str, int, str | None]:
        digest = hashlib.sha256()
        size = 0
        longest = max((len(pattern) for pattern, _ in self._denied_content), default=1)
        tail = b""
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
                window = tail + block
                for pattern, reason in self._denied_content:
                    if pattern in window:
                        return digest.hexdigest(), size, reason
                tail = window[-(longest - 1) :] if longest > 1 else b""
        return digest.hexdigest(), size, None

    def _preflight(self, path: str | os.PathLike[str], *, log_success: bool) -> FileAccess:
        lexical = _absolute(Path(path))
        lexical_root = self._lexical_root_for(lexical)
        lexically_allowed = lexical_root is not None or lexical in self._allowed_files_lexical
        if not lexically_allowed:
            self._deny(lexical, "path is outside the caller-supplied allowlist")
        self._reject_symlinks(lexical, lexical_root)
        try:
            resolved = lexical.resolve(strict=True)
        except FileNotFoundError:
            self._deny(lexical, "path does not exist")
        except (OSError, RuntimeError) as exc:
            self._deny(lexical, f"path resolution failed: {exc}")
        assert resolved is not None
        if not resolved.is_file():
            self._deny(lexical, "path is not a regular file")
        resolved_allowed = resolved in self._allowed_files_resolved or any(
            _is_relative_to(resolved, root) for root in self._allowed_roots_resolved
        )
        if not resolved_allowed:
            self._deny(lexical, "resolved path escapes the caller-supplied allowlist")

        path_reason = self._path_rule_reason(lexical, resolved)
        if path_reason is not None:
            self._deny(lexical, path_reason)
        try:
            digest, size, content_reason = self._hash_and_scan(resolved)
        except OSError as exc:
            self._deny(lexical, f"preflight read failed: {exc}")
        if content_reason is not None:
            self._deny(lexical, content_reason)
        if digest in self._denied_hashes:
            self._deny(lexical, self._denied_hashes[digest])

        access = FileAccess(str(resolved), digest, size)
        if log_success:
            self._log(operation="open", decision="allowed", **access.as_dict())
        return access

    def preflight(self, path: str | os.PathLike[str]) -> FileAccess:
        """Resolve, allowlist, deny-scan, hash, and log an existing regular file."""

        return self._preflight(path, log_success=True)

    def audit_allowed_tree(self) -> tuple[FileAccess, ...]:
        """Preflight every file/symlink beneath the configured roots and exact-file set."""

        candidates = set(self._allowed_files_lexical)
        for root in self._allowed_roots_lexical:
            candidates.update(
                path for path in root.rglob("*") if path.is_file() or path.is_symlink()
            )
        return tuple(self.preflight(path) for path in sorted(candidates, key=os.fspath))

    @contextmanager
    def checked_open(
        self,
        path: str | os.PathLike[str],
        mode: str = "rb",
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
        newline: str | None = None,
    ) -> Iterable[BinaryIO | TextIO]:
        """Open a preflighted read-only file and bind the opened handle to its hash."""

        if mode not in {"r", "rt", "rb"}:
            self._deny(
                _absolute(Path(path)),
                "checked_open supports read-only text or binary modes",
            )
        access = self._preflight(path, log_success=False)
        resolved = Path(access.resolved_path)
        try:
            raw_handle = resolved.open("rb")
        except OSError as exc:
            self._deny(resolved, f"checked open failed: {exc}")
        with raw_handle as raw:
            digest = hashlib.sha256()
            try:
                for block in iter(lambda: raw.read(1024 * 1024), b""):
                    digest.update(block)
                raw.seek(0)
            except OSError as exc:
                self._deny(resolved, f"checked read failed: {exc}")
            if digest.hexdigest() != access.sha256:
                self._deny(resolved, "file changed between preflight and open")
            self._log(operation="open", decision="allowed", **access.as_dict())
            if mode == "rb":
                yield raw
            else:
                try:
                    text = io.TextIOWrapper(
                        raw,
                        encoding=encoding,
                        errors=errors,
                        newline=newline,
                    )
                except (LookupError, OSError, ValueError) as exc:
                    self._deny(resolved, f"checked text open failed: {exc}")
                try:
                    yield text
                finally:
                    # Leave ownership of the binary handle with the outer context.
                    try:
                        text.detach()
                    except ValueError:
                        # A caller may close the wrapper before leaving the context.
                        pass

    def check_output(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a detached, JSON-normalised payload after applying the barrier."""

        try:
            normalised = enforce_output_fields(
                payload,
                allowed_top_level_fields=self._allowed_output_fields,
                denied_fields=self._denied_output_fields,
            )
        except FirewallViolation as exc:
            self._log(
                operation="output",
                decision="denied",
                reason=str(exc),
            )
            raise
        fields = sorted(normalised)
        self._log(operation="output", decision="allowed", top_level_fields=fields)
        return normalised


__all__ = [
    "FileAccess",
    "FirewallViolation",
    "InformationFirewall",
    "enforce_output_fields",
]
