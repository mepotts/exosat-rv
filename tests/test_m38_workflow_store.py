"""Adversarial target-free tests for the local M38 SQLite workflow store."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from threading import Event, Thread

import pytest

from exosat_rv.m38.provenance import canonical_json_bytes, canonical_sha256
from exosat_rv.m38.workflow import WORKFLOW_SCHEMA_VERSION, WorkflowStage
from exosat_rv.m38.workflow_store import (
    LOCAL_DURABILITY_SCOPE,
    SQLiteWorkflowStore,
    SubprocessWorkflowStore,
    WorkflowStoreCorruptionError,
    WorkflowStoreError,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


WORKFLOW_ID = digest("workflow-store-test")
SCIENCE_ID = digest("workflow-store-science")
KEY_ID = digest("workflow-store-key")


def workflow_record(
    sequence: int,
    prior_record_sha256: str | None,
    label: str,
    *,
    workflow_id: str = WORKFLOW_ID,
) -> dict:
    payload = {
        "input_identity_sha256": digest(f"input-{label}"),
        "output": {"artifact_sha256": digest(f"artifact-{label}")},
        "prior_record_sha256": prior_record_sha256,
        "retry_of_record_sha256": None,
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "scientific_identity_sha256": SCIENCE_ID,
        "sequence": sequence,
        "stage": (
            WorkflowStage.FROZEN.value if sequence == 0 else WorkflowStage.TARGET_MOUNTED.value
        ),
        "status": "complete",
        "workflow_id": workflow_id,
    }
    payload_bytes = canonical_json_bytes(payload)
    payload_hash = hashlib.sha256(payload_bytes).hexdigest()
    record = payload | {
        "integrity": {
            "payload_sha256": payload_hash,
            "signature": {
                "details": {
                    "algorithm": "external-detached-sha256-v1",
                    "key_identity_sha256": KEY_ID,
                    "signature_sha256": hashlib.sha256(
                        payload_bytes + b"test-signature"
                    ).hexdigest(),
                },
                "signed_content_sha256": payload_hash,
                "status": "signed",
            },
        }
    }
    record["record_sha256"] = canonical_sha256(record)
    return record


def test_atomic_append_reopen_load_and_prefix_rollback_rejection(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = SQLiteWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is True

    second = workflow_record(1, genesis["record_sha256"], "second")
    assert store.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], second) is True
    assert store.verify_head(WORKFLOW_ID, 1, second["record_sha256"]) is True
    assert store.verify_head(WORKFLOW_ID, 0, genesis["record_sha256"]) is False
    assert store.verify_record_included(WORKFLOW_ID, 0, genesis["record_sha256"]) is True
    assert store.verify_record_included(WORKFLOW_ID, 1, second["record_sha256"]) is True
    assert store.verify_record_included(WORKFLOW_ID, 0, digest("not-genesis")) is False

    reopened = SQLiteWorkflowStore(database)
    assert reopened.load_chain(WORKFLOW_ID) == (genesis, second)
    assert reopened.verify_head(WORKFLOW_ID, 1, second["record_sha256"]) is True


def test_post_commit_readback_accepts_inclusion_after_a_successor_lands(tmp_path):
    class SuccessorInterleavingStore(SQLiteWorkflowStore):
        def __init__(self, database_path):
            self._peer = None
            self._successor = None
            super().__init__(database_path)

        def arm(self, peer, successor):
            self._peer = peer
            self._successor = successor

        def _land_successor(self, workflow_id, sequence, record_sha256):
            if self._successor is None:
                return
            successor = self._successor
            peer = self._peer
            self._successor = None
            assert peer is not None
            assert peer.append_exclusive(
                workflow_id,
                sequence,
                record_sha256,
                successor,
            )

        def verify_head(self, workflow_id, sequence, record_sha256):
            self._land_successor(workflow_id, sequence, record_sha256)
            return super().verify_head(workflow_id, sequence, record_sha256)

        def verify_record_included(self, workflow_id, sequence, record_sha256):
            self._land_successor(workflow_id, sequence, record_sha256)
            return super().verify_record_included(workflow_id, sequence, record_sha256)

    database = tmp_path / "workflow.sqlite3"
    store = SuccessorInterleavingStore(database)
    peer = SQLiteWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is True

    second = workflow_record(1, genesis["record_sha256"], "second")
    successor = workflow_record(2, second["record_sha256"], "successor")
    store.arm(peer, successor)
    assert store.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], second) is True

    assert store.verify_record_included(WORKFLOW_ID, 1, second["record_sha256"]) is True
    assert store.verify_head(WORKFLOW_ID, 1, second["record_sha256"]) is False
    assert store.load_chain(WORKFLOW_ID) == (genesis, second, successor)


@pytest.mark.parametrize("operation", ["load-chain", "verify-head"])
def test_chain_and_head_reads_share_one_snapshot_during_writer_commit(tmp_path, operation):
    rows_read = Event()
    writer_committed = Event()

    class WALInterleavingStore(SQLiteWorkflowStore):
        def __init__(self, database_path):
            self.pause_after_rows = False
            super().__init__(database_path)

        def _connect(self):
            connection = sqlite3.connect(
                self._path,
                timeout=self._timeout_seconds,
                isolation_level=None,
            )
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute(f"PRAGMA busy_timeout = {self._timeout_seconds * 1000}")
            assert connection.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
            connection.execute("PRAGMA synchronous = FULL")
            return connection

        def _after_record_rows_read(self, _workflow_id):
            if self.pause_after_rows:
                rows_read.set()
                assert writer_committed.wait(10), "writer did not commit at the read boundary"

    database = tmp_path / "workflow.sqlite3"
    reader = WALInterleavingStore(database)
    writer = WALInterleavingStore(database)
    genesis = workflow_record(0, None, "genesis")
    second = workflow_record(1, genesis["record_sha256"], "second")
    assert reader.append_exclusive(WORKFLOW_ID, None, None, genesis) is True

    writer_errors = []

    def commit_successor():
        try:
            assert rows_read.wait(10), "reader did not reach the inter-query boundary"
            assert writer.append_exclusive(
                WORKFLOW_ID,
                0,
                genesis["record_sha256"],
                second,
            )
        except BaseException as exc:  # noqa: BLE001 - re-raised in the test thread.
            writer_errors.append(exc)
        finally:
            writer_committed.set()

    reader.pause_after_rows = True
    writer_thread = Thread(target=commit_successor, daemon=True)
    writer_thread.start()
    try:
        if operation == "load-chain":
            assert reader.load_chain(WORKFLOW_ID) == (genesis,)
        else:
            assert reader.verify_head(WORKFLOW_ID, 0, genesis["record_sha256"]) is True
    finally:
        reader.pause_after_rows = False
        writer_thread.join(10)

    assert not writer_thread.is_alive()
    assert writer_errors == []
    assert reader.load_chain(WORKFLOW_ID) == (genesis, second)


def test_duplicate_genesis_stale_writer_and_bad_expected_head_fail_closed(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    genesis = workflow_record(0, None, "genesis")
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is True
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is False

    second = workflow_record(1, genesis["record_sha256"], "second")
    assert store.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], second) is True
    stale = workflow_record(1, genesis["record_sha256"], "stale")
    assert store.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], stale) is False
    assert store.verify_head(WORKFLOW_ID, 1, second["record_sha256"]) is True

    with pytest.raises(WorkflowStoreError, match="both be null or both be set"):
        store.append_exclusive(WORKFLOW_ID, 1, None, workflow_record(2, None, "bad"))


@pytest.mark.parametrize("bad_sequence", [True, -1, 1 << 63])
def test_expected_sequence_requires_exact_sqlite_native_integer(tmp_path, bad_sequence):
    store = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    genesis = workflow_record(0, None, "genesis")
    with pytest.raises(WorkflowStoreError, match="native integer representable by SQLite"):
        store.append_exclusive(WORKFLOW_ID, bad_sequence, digest("expected"), genesis)


def test_record_identity_sequence_link_and_self_hash_are_independently_checked(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    genesis = workflow_record(0, None, "genesis")

    wrong_workflow = workflow_record(
        0,
        None,
        "other-workflow",
        workflow_id=digest("other-workflow"),
    )
    with pytest.raises(WorkflowStoreError, match="record does not bind"):
        store.append_exclusive(WORKFLOW_ID, None, None, wrong_workflow)

    wrong_sequence = workflow_record(1, None, "wrong-sequence")
    with pytest.raises(WorkflowStoreError, match="genesis record"):
        store.append_exclusive(WORKFLOW_ID, None, None, wrong_sequence)

    tampered = deepcopy(genesis)
    tampered["record_sha256"] = digest("forged-self-hash")
    with pytest.raises(WorkflowStoreError, match="envelope is invalid"):
        store.append_exclusive(WORKFLOW_ID, None, None, tampered)


def test_non_native_and_non_finite_record_values_are_rejected(tmp_path):
    class DictSubclass(dict):
        pass

    store = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    genesis = workflow_record(0, None, "genesis")
    with pytest.raises(WorkflowStoreError, match="envelope is invalid"):
        store.append_exclusive(WORKFLOW_ID, None, None, DictSubclass(genesis))

    non_finite = deepcopy(genesis)
    non_finite["output"]["not_a_number"] = float("nan")
    with pytest.raises(WorkflowStoreError, match="envelope is invalid"):
        store.append_exclusive(WORKFLOW_ID, None, None, non_finite)


def test_record_rows_are_sql_immutable_and_head_tampering_is_detected(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = SQLiteWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is True

    with closing(sqlite3.connect(database)) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE workflow_records SET record_json = ? WHERE workflow_id = ?",
                (b"{}", WORKFLOW_ID),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "DELETE FROM workflow_records WHERE workflow_id = ?",
                (WORKFLOW_ID,),
            )

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE workflow_heads SET record_sha256 = ? WHERE workflow_id = ?",
            (digest("tampered-head"), WORKFLOW_ID),
        )
        connection.commit()
    with pytest.raises(WorkflowStoreCorruptionError, match="subprocess detected"):
        SubprocessWorkflowStore(database).load_chain(WORKFLOW_ID)
    with pytest.raises(WorkflowStoreCorruptionError, match="integrity checks failed"):
        SQLiteWorkflowStore(database)


def test_schema_trigger_removal_is_detected_before_use(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    SQLiteWorkflowStore(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DROP TRIGGER workflow_records_no_update")
        connection.commit()
    with pytest.raises(WorkflowStoreCorruptionError, match="schema objects differ"):
        SQLiteWorkflowStore(database)


def test_same_named_but_weakened_schema_trigger_is_detected(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    SQLiteWorkflowStore(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DROP TRIGGER workflow_records_no_update")
        connection.execute(
            """
            CREATE TRIGGER workflow_records_no_update
            BEFORE UPDATE ON workflow_records
            BEGIN
                SELECT 1;
            END
            """
        )
        connection.commit()
    with pytest.raises(WorkflowStoreCorruptionError, match="schema definitions differ"):
        SQLiteWorkflowStore(database)


def test_mutable_head_cannot_be_repointed_to_a_valid_older_record(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = SQLiteWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    second = workflow_record(1, genesis["record_sha256"], "second")
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is True
    assert store.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], second) is True

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            UPDATE workflow_heads
            SET sequence = ?, record_sha256 = ?
            WHERE workflow_id = ?
            """,
            (0, genesis["record_sha256"], WORKFLOW_ID),
        )
        connection.commit()

    with pytest.raises(WorkflowStoreCorruptionError, match="integrity checks failed"):
        SQLiteWorkflowStore(database)


def test_process_crash_rolls_back_uncommitted_head_change(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    store = SQLiteWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is True

    script = (
        "import os, sqlite3, sys; "
        "connection=sqlite3.connect(sys.argv[1]); "
        "connection.execute('PRAGMA foreign_keys=OFF'); "
        "connection.execute('BEGIN IMMEDIATE'); "
        'connection.execute("UPDATE workflow_heads SET sequence=7, '
        "record_sha256='0000000000000000000000000000000000000000000000000000000000000000'\"); "
        "os._exit(91)"
    )
    crashed = subprocess.run(
        [sys.executable, "-c", script, os.fspath(database)],
        check=False,
        capture_output=True,
    )
    assert crashed.returncode == 91
    assert SQLiteWorkflowStore(database).load_chain(WORKFLOW_ID) == (genesis,)


def test_subprocess_adapter_persists_and_recovers_after_caller_restart(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    client = SubprocessWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    assert client.append_exclusive(WORKFLOW_ID, None, None, genesis) is True

    second = workflow_record(1, genesis["record_sha256"], "second")
    assert client.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], second) is True

    restarted_client = SubprocessWorkflowStore(database)
    assert restarted_client.load_chain(WORKFLOW_ID) == (genesis, second)
    assert restarted_client.verify_head(WORKFLOW_ID, 1, second["record_sha256"]) is True
    assert (
        restarted_client.verify_record_included(
            WORKFLOW_ID,
            0,
            genesis["record_sha256"],
        )
        is True
    )


def test_concurrent_subprocess_writers_have_exactly_one_cas_winner(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    direct = SQLiteWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    assert direct.append_exclusive(WORKFLOW_ID, None, None, genesis) is True

    candidates = [
        workflow_record(1, genesis["record_sha256"], "candidate-a"),
        workflow_record(1, genesis["record_sha256"], "candidate-b"),
    ]

    def append(record):
        client = SubprocessWorkflowStore(database)
        return client.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(append, candidates))
    assert sorted(outcomes) == [False, True]
    stored = SQLiteWorkflowStore(database).load_chain(WORKFLOW_ID)
    assert len(stored) == 2
    assert stored[1] in candidates


def test_concurrent_subprocess_genesis_creation_initialises_once(tmp_path):
    database = tmp_path / "fresh-workflow.sqlite3"
    candidates = [
        workflow_record(0, None, "genesis-a"),
        workflow_record(0, None, "genesis-b"),
    ]

    def create(record):
        client = SubprocessWorkflowStore(database)
        return client.append_exclusive(WORKFLOW_ID, None, None, record)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(create, candidates))
    assert sorted(outcomes) == [False, True]
    stored = SQLiteWorkflowStore(database).load_chain(WORKFLOW_ID)
    assert len(stored) == 1
    assert stored[0] in candidates


def test_cli_rejects_duplicate_json_keys_without_creating_a_store(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    request = (
        b'{"workflow_id":"'
        + WORKFLOW_ID.encode("ascii")
        + b'","workflow_id":"'
        + WORKFLOW_ID.encode("ascii")
        + b'"}'
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "exosat_rv.m38.workflow_store",
            "--database",
            os.fspath(database),
            "load-chain",
        ],
        input=request,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "error_code": "invalid_or_failed_request",
        "ok": False,
    }
    assert not database.exists()


def test_unknown_workflow_and_exact_head_argument_types_fail_closed(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    assert store.verify_head(WORKFLOW_ID, 0, digest("missing")) is False
    assert store.verify_record_included(WORKFLOW_ID, 0, digest("missing")) is False
    with pytest.raises(WorkflowStoreError, match="does not exist"):
        store.load_chain(WORKFLOW_ID)
    with pytest.raises(WorkflowStoreError, match="native integer"):
        store.verify_head(WORKFLOW_ID, True, digest("missing"))
    with pytest.raises(WorkflowStoreError, match="native integer"):
        store.verify_record_included(WORKFLOW_ID, True, digest("missing"))


def test_whole_database_snapshot_rollback_is_explicitly_outside_local_claim(tmp_path):
    database = tmp_path / "workflow.sqlite3"
    snapshot = tmp_path / "older.sqlite3"
    store = SQLiteWorkflowStore(database)
    genesis = workflow_record(0, None, "genesis")
    assert store.append_exclusive(WORKFLOW_ID, None, None, genesis) is True
    shutil.copyfile(database, snapshot)

    second = workflow_record(1, genesis["record_sha256"], "second")
    assert store.append_exclusive(WORKFLOW_ID, 0, genesis["record_sha256"], second) is True
    shutil.copyfile(snapshot, database)

    rolled_back = SQLiteWorkflowStore(database)
    assert rolled_back.load_chain(WORKFLOW_ID) == (genesis,)
    assert "no external trust" in LOCAL_DURABILITY_SCOPE
    assert "rollback anchor" in LOCAL_DURABILITY_SCOPE
