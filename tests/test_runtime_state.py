from __future__ import annotations

from types import SimpleNamespace

from stormhelm.core import runtime_state


class _StubPath:
    def __init__(self, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.unlink_calls = 0

    def unlink(self, *, missing_ok: bool = False) -> None:
        assert missing_ok is True
        self.unlink_calls += 1
        if self.unlink_calls <= self.failures_before_success:
            raise PermissionError("runtime state file is temporarily locked")


def _config_for(path: _StubPath) -> SimpleNamespace:
    return SimpleNamespace(runtime=SimpleNamespace(core_state_path=path))


def test_clear_runtime_state_retries_transient_permission_errors(monkeypatch) -> None:
    monkeypatch.setattr(runtime_state, "sleep", lambda _: None)
    path = _StubPath(failures_before_success=2)

    runtime_state.clear_runtime_state(_config_for(path))

    assert path.unlink_calls == 3


def test_clear_runtime_state_tolerates_persistent_permission_errors(monkeypatch) -> None:
    monkeypatch.setattr(runtime_state, "sleep", lambda _: None)
    path = _StubPath(failures_before_success=999)

    runtime_state.clear_runtime_state(_config_for(path))

    assert path.unlink_calls == runtime_state._RUNTIME_STATE_UNLINK_RETRIES + 1
