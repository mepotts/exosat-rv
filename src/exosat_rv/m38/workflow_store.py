"""Local durable compare-and-append mechanics for an M38 workflow ledger.

The SQLite store in this module gives cooperative local processes atomic expected-head
comparison, immutable record rows, durable commits, restart recovery, and structural
envelope/link revalidation across each requested chain.  Authoritative signatures and the
workflow state machine remain the responsibility of :class:`WorkflowLedger`.  This store is
intentionally *not* described as an independent or hostile-writer-proof store.  A process with
permission to replace the database can roll it back, alter its schema, or bypass these checks,
and the store has no trusted clock, external monotonic anchor, or key authority.  Those
properties remain external governance and deployment requirements.

The subprocess adapter is useful for exercising the callback boundary in a separate process.
It does not turn a helper running as the same OS principal into an independent trust domain.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from .provenance import ProvenanceError, canonical_json_bytes
from .workflow import WorkflowError, validate_workflow_record_envelope

WORKFLOW_STORE_SCHEMA_VERSION = 1
LOCAL_DURABILITY_SCOPE = (
    "atomic local SQLite mechanics only; no external trust, hostile-writer resistance, "
    "trusted timestamp, or rollback anchor"
)
_APPLICATION_ID = 0x4D333853  # ASCII-ish "M38S".
_MAX_SQLITE_INTEGER = (1 << 63) - 1
_MAX_CLI_REQUEST_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CREATE_RECORDS_SQL = """CREATE TABLE workflow_records (
    workflow_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (
        typeof(sequence) = 'integer' AND sequence >= 0
    ),
    record_sha256 TEXT NOT NULL,
    prior_record_sha256 TEXT,
    record_json BLOB NOT NULL CHECK (typeof(record_json) = 'blob'),
    PRIMARY KEY (workflow_id, sequence),
    UNIQUE (workflow_id, sequence, record_sha256)
) WITHOUT ROWID"""
_CREATE_HEADS_SQL = """CREATE TABLE workflow_heads (
    workflow_id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL CHECK (
        typeof(sequence) = 'integer' AND sequence >= 0
    ),
    record_sha256 TEXT NOT NULL,
    FOREIGN KEY (workflow_id, sequence, record_sha256)
        REFERENCES workflow_records (
            workflow_id, sequence, record_sha256
        )
) WITHOUT ROWID"""
_CREATE_NO_UPDATE_SQL = """CREATE TRIGGER workflow_records_no_update
BEFORE UPDATE ON workflow_records
BEGIN
    SELECT RAISE(ABORT, 'workflow records are immutable');
END"""
_CREATE_NO_DELETE_SQL = """CREATE TRIGGER workflow_records_no_delete
BEFORE DELETE ON workflow_records
BEGIN
    SELECT RAISE(ABORT, 'workflow records are immutable');
END"""
_SCHEMA_SQL = {
    ("table", "workflow_heads"): _CREATE_HEADS_SQL,
    ("table", "workflow_records"): _CREATE_RECORDS_SQL,
    ("trigger", "workflow_records_no_delete"): _CREATE_NO_DELETE_SQL,
    ("trigger", "workflow_records_no_update"): _CREATE_NO_UPDATE_SQL,
}
_SCHEMA_OBJECTS = frozenset(_SCHEMA_SQL)


class WorkflowStoreError(RuntimeError):
    """Base error for invalid requests, persistence failures, or corrupt store state."""


class WorkflowStoreCorruptionError(WorkflowStoreError):
    """Raised when persisted rows, links, heads, or the database schema fail closed."""


def _require_sha256(value: Any, *, field: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise WorkflowStoreError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _require_sequence(value: Any, *, field: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_SQLITE_INTEGER:
        raise WorkflowStoreError(
            f"{field} must be a non-negative native integer representable by SQLite"
        )
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _decode_strict_json(content: bytes, *, label: str) -> Any:
    try:
        decoded = content.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
        # This also rejects non-native values and excessive/cyclic nesting in callers that do
        # not originate from JSON, and gives every stored value one byte representation.
        canonical_json_bytes(value)
    except (UnicodeError, ValueError, ProvenanceError, RecursionError) as exc:
        raise WorkflowStoreError(f"{label} is not strict canonical-compatible JSON") from exc
    return value


def _validate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    try:
        detached = validate_workflow_record_envelope(record)
    except (ProvenanceError, WorkflowError, TypeError, ValueError) as exc:
        raise WorkflowStoreError("workflow record envelope is invalid") from exc
    _require_sha256(detached["workflow_id"], field="record.workflow_id")
    _require_sha256(detached["record_sha256"], field="record.record_sha256")
    _require_sequence(detached["sequence"], field="record.sequence")
    return detached


def _validate_chain_records(
    workflow_id: str,
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    workflow = _require_sha256(workflow_id, field="workflow_id")
    if type(records) not in {list, tuple}:
        raise WorkflowStoreCorruptionError("workflow records must be a native list or tuple")
    verified: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        try:
            detached = _validate_record(record)
        except WorkflowStoreError as exc:
            raise WorkflowStoreCorruptionError("persisted workflow record is invalid") from exc
        if detached["workflow_id"] != workflow:
            raise WorkflowStoreCorruptionError("persisted record changed workflow identity")
        if detached["sequence"] != index:
            raise WorkflowStoreCorruptionError("persisted workflow sequence has a gap")
        expected_prior = None if index == 0 else verified[-1]["record_sha256"]
        if detached["prior_record_sha256"] != expected_prior:
            raise WorkflowStoreCorruptionError("persisted workflow prior-record link is invalid")
        verified.append(detached)
    return tuple(verified)


class SQLiteWorkflowStore:
    """SQLite-backed atomic compare-and-append storage under one local trust domain."""

    trust_scope = LOCAL_DURABILITY_SCOPE

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        timeout_seconds: int = 30,
    ) -> None:
        if type(timeout_seconds) is not int or timeout_seconds <= 0:
            raise WorkflowStoreError("timeout_seconds must be a positive native integer")
        if timeout_seconds > 3600:
            raise WorkflowStoreError("timeout_seconds exceeds the bounded local maximum")
        try:
            supplied = Path(database_path)
        except TypeError as exc:
            raise WorkflowStoreError("a persistent SQLite database pathname is required") from exc
        if not supplied.name or os.fspath(supplied) == ":memory:":
            raise WorkflowStoreError("a persistent SQLite database pathname is required")
        absolute = Path(os.path.abspath(os.fspath(supplied)))
        try:
            absolute.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkflowStoreError("cannot create the workflow-store directory") from exc
        if absolute.is_symlink() or (absolute.exists() and not absolute.is_file()):
            raise WorkflowStoreError("database path must be a regular nonsymlink file")
        self._path = absolute
        self._timeout_seconds = timeout_seconds
        with closing(self._connect()) as connection:
            self._ensure_schema(connection)
            self._require_database_integrity(connection)
        if os.name != "nt":
            try:
                self._path.chmod(0o600)
            except OSError as exc:
                raise WorkflowStoreError(
                    "cannot restrict local workflow-store permissions"
                ) from exc

    @property
    def database_path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        if self._path.is_symlink() or (self._path.exists() and not self._path.is_file()):
            raise WorkflowStoreError("database path was replaced by a non-regular entry")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self._path,
                timeout=self._timeout_seconds,
                isolation_level=None,
            )
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute(f"PRAGMA busy_timeout = {self._timeout_seconds * 1000}")
            journal_mode = connection.execute("PRAGMA journal_mode = DELETE").fetchone()
            connection.execute("PRAGMA synchronous = FULL")
            synchronous = connection.execute("PRAGMA synchronous").fetchone()
            if journal_mode != ("delete",) or synchronous != (2,):
                connection.close()
                raise WorkflowStoreError("SQLite durability pragmas were not enforced")
            return connection
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise WorkflowStoreError("cannot open the local workflow store") from exc

    @staticmethod
    def _rollback(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        try:
            # Serialising the inspection as well as creation avoids a stale empty-schema view
            # when two fresh helper processes race to initialise the same database.
            connection.execute("BEGIN IMMEDIATE")
            schema_sql = {
                (kind, name): sql
                for kind, name, sql in connection.execute(
                    "SELECT type, name, sql FROM sqlite_master "
                    "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                )
            }
            objects = set(schema_sql)
            version = connection.execute("PRAGMA user_version").fetchone()
            application_id = connection.execute("PRAGMA application_id").fetchone()
            if not objects and version == (0,) and application_id == (0,):
                connection.execute(_CREATE_RECORDS_SQL)
                connection.execute(_CREATE_HEADS_SQL)
                connection.execute(_CREATE_NO_UPDATE_SQL)
                connection.execute(_CREATE_NO_DELETE_SQL)
                connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {WORKFLOW_STORE_SCHEMA_VERSION}")
                schema_sql = {
                    (kind, name): sql
                    for kind, name, sql in connection.execute(
                        "SELECT type, name, sql FROM sqlite_master "
                        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
                    )
                }
                objects = set(schema_sql)
                version = (WORKFLOW_STORE_SCHEMA_VERSION,)
                application_id = (_APPLICATION_ID,)
            if objects != _SCHEMA_OBJECTS:
                raise WorkflowStoreCorruptionError("workflow-store schema objects differ")
            if schema_sql != _SCHEMA_SQL:
                raise WorkflowStoreCorruptionError("workflow-store schema definitions differ")
            if version != (WORKFLOW_STORE_SCHEMA_VERSION,):
                raise WorkflowStoreCorruptionError("workflow-store schema version differs")
            if application_id != (_APPLICATION_ID,):
                raise WorkflowStoreCorruptionError("workflow-store application identity differs")
            connection.execute("COMMIT")
        except WorkflowStoreError:
            self._rollback(connection)
            raise
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise WorkflowStoreCorruptionError("workflow-store schema cannot be verified") from exc

    @staticmethod
    def _require_database_integrity(connection: sqlite3.Connection) -> None:
        try:
            quick_check = connection.execute("PRAGMA quick_check(1)").fetchall()
            foreign_key_check = connection.execute("PRAGMA foreign_key_check").fetchall()
            missing_or_stale_head = connection.execute(
                """
                SELECT records.workflow_id
                FROM (
                    SELECT workflow_id, MAX(sequence) AS tip_sequence
                    FROM workflow_records
                    GROUP BY workflow_id
                ) AS records
                LEFT JOIN workflow_heads AS heads
                    ON heads.workflow_id = records.workflow_id
                WHERE heads.workflow_id IS NULL OR heads.sequence != records.tip_sequence
                LIMIT 1
                """
            ).fetchone()
        except sqlite3.Error as exc:
            raise WorkflowStoreCorruptionError("SQLite integrity checks could not run") from exc
        if quick_check != [("ok",)] or foreign_key_check or missing_or_stale_head is not None:
            raise WorkflowStoreCorruptionError("SQLite integrity checks failed")

    def _read_chain(
        self,
        connection: sqlite3.Connection,
        workflow_id: str,
    ) -> tuple[dict[str, Any], ...]:
        try:
            rows = connection.execute(
                """
                SELECT sequence, record_sha256, prior_record_sha256, record_json
                FROM workflow_records
                WHERE workflow_id = ?
                ORDER BY sequence
                """,
                (workflow_id,),
            ).fetchall()
            self._after_record_rows_read(workflow_id)
            head = connection.execute(
                """
                SELECT sequence, record_sha256
                FROM workflow_heads
                WHERE workflow_id = ?
                """,
                (workflow_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise WorkflowStoreCorruptionError("persisted workflow cannot be read") from exc
        if not rows:
            if head is not None:
                raise WorkflowStoreCorruptionError("workflow head exists without records")
            return ()

        decoded_records: list[dict[str, Any]] = []
        for row_sequence, row_hash, row_prior, raw_record in rows:
            if type(raw_record) is not bytes:
                raise WorkflowStoreCorruptionError("persisted record is not canonical byte data")
            try:
                decoded = _decode_strict_json(raw_record, label="persisted workflow record")
            except WorkflowStoreError as exc:
                raise WorkflowStoreCorruptionError("persisted workflow JSON is invalid") from exc
            if type(decoded) is not dict:
                raise WorkflowStoreCorruptionError("persisted workflow record is not an object")
            decoded_records.append(decoded)
            if (
                type(row_sequence) is not int
                or type(row_hash) is not str
                or (row_prior is not None and type(row_prior) is not str)
                or decoded.get("sequence") != row_sequence
                or decoded.get("record_sha256") != row_hash
                or decoded.get("prior_record_sha256") != row_prior
                or canonical_json_bytes(decoded) != raw_record
            ):
                raise WorkflowStoreCorruptionError("persisted row columns do not bind its record")

        verified = _validate_chain_records(workflow_id, decoded_records)
        last = verified[-1]
        if head != (last["sequence"], last["record_sha256"]):
            raise WorkflowStoreCorruptionError("persisted head does not match the chain tip")
        return verified

    def _after_record_rows_read(self, _workflow_id: str) -> None:
        """No-op interleaving seam used to prove the two reads share one snapshot."""

    def _read_validated_chain(
        self,
        connection: sqlite3.Connection,
        workflow_id: str,
    ) -> tuple[dict[str, Any], ...]:
        """Read integrity state, records, and head from one SQLite snapshot."""

        try:
            connection.execute("BEGIN")
            self._require_database_integrity(connection)
            records = self._read_chain(connection, workflow_id)
            connection.execute("COMMIT")
            return records
        except WorkflowStoreError:
            self._rollback(connection)
            raise
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise WorkflowStoreError("SQLite snapshot read failed") from exc

    def append_exclusive(
        self,
        workflow_id: str,
        expected_sequence: int | None,
        expected_sha256: str | None,
        record: Mapping[str, Any],
    ) -> bool:
        """Atomically create or append when the durable head exactly matches expectations."""

        workflow = _require_sha256(workflow_id, field="workflow_id")
        if (expected_sequence is None) != (expected_sha256 is None):
            raise WorkflowStoreError("expected sequence and hash must both be null or both be set")
        if expected_sequence is not None:
            expected_sequence = _require_sequence(
                expected_sequence,
                field="expected_sequence",
            )
            expected_sha256 = _require_sha256(expected_sha256, field="expected_sha256")
            if expected_sequence == _MAX_SQLITE_INTEGER:
                raise WorkflowStoreError("expected sequence cannot be advanced in SQLite")
        detached = _validate_record(record)
        if detached["workflow_id"] != workflow:
            raise WorkflowStoreError("record does not bind the requested workflow")
        if expected_sequence is None:
            if detached["sequence"] != 0 or detached["prior_record_sha256"] is not None:
                raise WorkflowStoreError("genesis record must be sequence zero with no prior hash")
        elif (
            detached["sequence"] != expected_sequence + 1
            or detached["prior_record_sha256"] != expected_sha256
        ):
            raise WorkflowStoreError("append record does not bind the expected head")
        record_bytes = canonical_json_bytes(detached)

        with closing(self._connect()) as connection:
            self._ensure_schema(connection)
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._require_database_integrity(connection)
                existing = self._read_chain(connection, workflow)
                if expected_sequence is None:
                    matches = not existing
                else:
                    matches = bool(
                        existing
                        and existing[-1]["sequence"] == expected_sequence
                        and existing[-1]["record_sha256"] == expected_sha256
                    )
                if not matches:
                    connection.execute("ROLLBACK")
                    return False
                connection.execute(
                    """
                    INSERT INTO workflow_records (
                        workflow_id,
                        sequence,
                        record_sha256,
                        prior_record_sha256,
                        record_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        workflow,
                        detached["sequence"],
                        detached["record_sha256"],
                        detached["prior_record_sha256"],
                        record_bytes,
                    ),
                )
                if expected_sequence is None:
                    connection.execute(
                        """
                        INSERT INTO workflow_heads (workflow_id, sequence, record_sha256)
                        VALUES (?, ?, ?)
                        """,
                        (workflow, detached["sequence"], detached["record_sha256"]),
                    )
                else:
                    cursor = connection.execute(
                        """
                        UPDATE workflow_heads
                        SET sequence = ?, record_sha256 = ?
                        WHERE workflow_id = ? AND sequence = ? AND record_sha256 = ?
                        """,
                        (
                            detached["sequence"],
                            detached["record_sha256"],
                            workflow,
                            expected_sequence,
                            expected_sha256,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise WorkflowStoreCorruptionError(
                            "head changed inside the exclusive SQLite transaction"
                        )
                committed_chain = self._read_chain(connection, workflow)
                if committed_chain[-1]["record_sha256"] != detached["record_sha256"]:
                    raise WorkflowStoreCorruptionError("new record did not become the chain tip")
                connection.execute("COMMIT")
            except WorkflowStoreError:
                self._rollback(connection)
                raise
            except sqlite3.IntegrityError as exc:
                self._rollback(connection)
                raise WorkflowStoreCorruptionError(
                    "SQLite rejected a record after expected-head validation"
                ) from exc
            except sqlite3.Error as exc:
                self._rollback(connection)
                raise WorkflowStoreError("SQLite compare-and-append failed") from exc

        if not self.verify_record_included(
            workflow,
            detached["sequence"],
            detached["record_sha256"],
        ):
            raise WorkflowStoreCorruptionError(
                "committed record failed durable inclusion read-back"
            )
        return True

    def load_chain(self, workflow_id: str) -> tuple[dict[str, Any], ...]:
        """Load and revalidate the complete canonical record chain after a restart."""

        workflow = _require_sha256(workflow_id, field="workflow_id")
        with closing(self._connect()) as connection:
            self._ensure_schema(connection)
            records = self._read_validated_chain(connection, workflow)
        if not records:
            raise WorkflowStoreError("workflow does not exist")
        return tuple(_validate_record(record) for record in records)

    def verify_head(self, workflow_id: str, sequence: int, record_sha256: str) -> bool:
        """Revalidate the full stored chain and compare its current tip exactly."""

        workflow = _require_sha256(workflow_id, field="workflow_id")
        expected_sequence = _require_sequence(sequence, field="sequence")
        expected_hash = _require_sha256(record_sha256, field="record_sha256")
        with closing(self._connect()) as connection:
            self._ensure_schema(connection)
            records = self._read_validated_chain(connection, workflow)
        return bool(
            records
            and records[-1]["sequence"] == expected_sequence
            and records[-1]["record_sha256"] == expected_hash
        )

    def verify_record_included(
        self,
        workflow_id: str,
        sequence: int,
        record_sha256: str,
    ) -> bool:
        """Revalidate the chain and confirm a record remains included below any later tip."""

        workflow = _require_sha256(workflow_id, field="workflow_id")
        expected_sequence = _require_sequence(sequence, field="sequence")
        expected_hash = _require_sha256(record_sha256, field="record_sha256")
        with closing(self._connect()) as connection:
            self._ensure_schema(connection)
            records = self._read_validated_chain(connection, workflow)
        return bool(
            expected_sequence < len(records)
            and records[expected_sequence]["sequence"] == expected_sequence
            and records[expected_sequence]["record_sha256"] == expected_hash
        )


class SubprocessWorkflowStore:
    """Invoke the SQLite adapter through a strict JSON subprocess protocol."""

    trust_scope = LOCAL_DURABILITY_SCOPE

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        command: Sequence[str] | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        if type(timeout_seconds) is not int or timeout_seconds <= 0:
            raise WorkflowStoreError("timeout_seconds must be a positive native integer")
        if timeout_seconds > 3600:
            raise WorkflowStoreError("timeout_seconds exceeds the bounded local maximum")
        selected = (
            (sys.executable, "-m", "exosat_rv.m38.workflow_store") if command is None else command
        )
        if type(selected) not in {list, tuple} or not selected:
            raise WorkflowStoreError("subprocess command must be a non-empty native sequence")
        if any(type(part) is not str or not part for part in selected):
            raise WorkflowStoreError("subprocess command entries must be native strings")
        self._command = tuple(selected)
        try:
            supplied_path = Path(database_path)
            if not supplied_path.name or os.fspath(supplied_path) == ":memory:":
                raise WorkflowStoreError("a persistent SQLite database pathname is required")
            self._database_path = Path(os.path.abspath(os.fspath(supplied_path)))
        except TypeError as exc:
            raise WorkflowStoreError("a persistent SQLite database pathname is required") from exc
        self._timeout_seconds = timeout_seconds

    def _invoke(self, operation: str, request: Mapping[str, Any]) -> dict[str, Any]:
        try:
            payload = canonical_json_bytes(request) + b"\n"
        except ProvenanceError as exc:
            raise WorkflowStoreError("workflow-store request is not strict native JSON") from exc
        argv = [
            *self._command,
            "--database",
            os.fspath(self._database_path),
            operation,
        ]
        try:
            result = subprocess.run(
                argv,
                input=payload,
                capture_output=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise WorkflowStoreError("workflow-store subprocess did not complete") from exc
        try:
            response = _decode_strict_json(result.stdout, label="workflow-store response")
        except WorkflowStoreError as exc:
            raise WorkflowStoreError(
                "workflow-store subprocess returned an invalid response"
            ) from exc
        if type(response) is not dict or type(response.get("ok")) is not bool:
            raise WorkflowStoreError("workflow-store subprocess response schema is invalid")
        if result.returncode != 0 or response["ok"] is not True:
            if set(response) != {"error_code", "ok"} or type(response.get("error_code")) is not str:
                raise WorkflowStoreError("workflow-store subprocess failure schema is invalid")
            if response["error_code"] == "store_corruption":
                raise WorkflowStoreCorruptionError(
                    "workflow-store subprocess detected durable-store corruption"
                )
            raise WorkflowStoreError(
                f"workflow-store subprocess rejected the request: {response['error_code']}"
            )
        return response

    def append_exclusive(
        self,
        workflow_id: str,
        expected_sequence: int | None,
        expected_sha256: str | None,
        record: Mapping[str, Any],
    ) -> bool:
        response = self._invoke(
            "append",
            {
                "expected_sequence": expected_sequence,
                "expected_sha256": expected_sha256,
                "record": record,
                "workflow_id": workflow_id,
            },
        )
        if set(response) != {"accepted", "ok"} or type(response["accepted"]) is not bool:
            raise WorkflowStoreError("append subprocess response schema is invalid")
        return response["accepted"]

    def verify_head(self, workflow_id: str, sequence: int, record_sha256: str) -> bool:
        response = self._invoke(
            "verify-head",
            {
                "record_sha256": record_sha256,
                "sequence": sequence,
                "workflow_id": workflow_id,
            },
        )
        if set(response) != {"ok", "verified"} or type(response["verified"]) is not bool:
            raise WorkflowStoreError("head-verification subprocess response schema is invalid")
        return response["verified"]

    def verify_record_included(
        self,
        workflow_id: str,
        sequence: int,
        record_sha256: str,
    ) -> bool:
        response = self._invoke(
            "verify-record",
            {
                "record_sha256": record_sha256,
                "sequence": sequence,
                "workflow_id": workflow_id,
            },
        )
        if set(response) != {"included", "ok"} or type(response["included"]) is not bool:
            raise WorkflowStoreError("record-verification subprocess response schema is invalid")
        return response["included"]

    def load_chain(self, workflow_id: str) -> tuple[dict[str, Any], ...]:
        response = self._invoke("load-chain", {"workflow_id": workflow_id})
        if set(response) != {"ok", "records"} or type(response["records"]) is not list:
            raise WorkflowStoreError("load-chain subprocess response schema is invalid")
        return _validate_chain_records(workflow_id, response["records"])


def _read_cli_request() -> dict[str, Any]:
    content = sys.stdin.buffer.read(_MAX_CLI_REQUEST_BYTES + 1)
    if len(content) > _MAX_CLI_REQUEST_BYTES:
        raise WorkflowStoreError("CLI request exceeds the fixed size limit")
    request = _decode_strict_json(content, label="workflow-store request")
    if type(request) is not dict:
        raise WorkflowStoreError("workflow-store request must be an object")
    return request


def _write_cli_response(response: Mapping[str, Any]) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(response) + b"\n")
    sys.stdout.buffer.flush()


def _run_cli(database: str, operation: str) -> int:
    try:
        request = _read_cli_request()
        store = SQLiteWorkflowStore(database)
        if operation == "append":
            if set(request) != {
                "expected_sequence",
                "expected_sha256",
                "record",
                "workflow_id",
            }:
                raise WorkflowStoreError("append request schema differs")
            response = {
                "accepted": store.append_exclusive(
                    request["workflow_id"],
                    request["expected_sequence"],
                    request["expected_sha256"],
                    request["record"],
                ),
                "ok": True,
            }
        elif operation == "verify-head":
            if set(request) != {"record_sha256", "sequence", "workflow_id"}:
                raise WorkflowStoreError("verify-head request schema differs")
            response = {
                "ok": True,
                "verified": store.verify_head(
                    request["workflow_id"],
                    request["sequence"],
                    request["record_sha256"],
                ),
            }
        elif operation == "verify-record":
            if set(request) != {"record_sha256", "sequence", "workflow_id"}:
                raise WorkflowStoreError("verify-record request schema differs")
            response = {
                "included": store.verify_record_included(
                    request["workflow_id"],
                    request["sequence"],
                    request["record_sha256"],
                ),
                "ok": True,
            }
        elif operation == "load-chain":
            if set(request) != {"workflow_id"}:
                raise WorkflowStoreError("load-chain request schema differs")
            response = {"ok": True, "records": list(store.load_chain(request["workflow_id"]))}
        else:  # pragma: no cover - argparse constrains this before dispatch.
            raise WorkflowStoreError("unknown workflow-store operation")
    except WorkflowStoreCorruptionError:
        _write_cli_response({"error_code": "store_corruption", "ok": False})
        return 3
    except (ProvenanceError, WorkflowError, WorkflowStoreError, TypeError, ValueError):
        _write_cli_response({"error_code": "invalid_or_failed_request", "ok": False})
        return 2
    _write_cli_response(response)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M38 local SQLite compare-and-append helper")
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "operation",
        choices=("append", "verify-head", "verify-record", "load-chain"),
    )
    arguments = parser.parse_args(argv)
    return _run_cli(arguments.database, arguments.operation)


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests.
    raise SystemExit(main())


__all__ = [
    "LOCAL_DURABILITY_SCOPE",
    "WORKFLOW_STORE_SCHEMA_VERSION",
    "SQLiteWorkflowStore",
    "SubprocessWorkflowStore",
    "WorkflowStoreCorruptionError",
    "WorkflowStoreError",
]
