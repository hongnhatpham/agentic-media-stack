import sqlite3

from agentic_media_stack.state import StateStore


def test_state_migrates_and_backups_audit_history(tmp_path):
    source = tmp_path / "state.db"
    backup = tmp_path / "backups" / "state.db"
    state = StateStore(str(source))
    state.record_audit("test", "persistent event", {"safe": True})
    state.backup(str(backup))
    state.close()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT count(*) FROM audit").fetchone()[0] == 1
