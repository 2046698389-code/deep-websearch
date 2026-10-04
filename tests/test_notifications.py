import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

from deep_websearch import notifications


def test_windows_reminder_uses_hidden_child_and_never_waits(monkeypatch):
    popen = Mock()
    process = popen.return_value
    monkeypatch.setattr(notifications, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        GetProcessWindowStation=lambda: 1)), raising=False)
    monkeypatch.setattr(notifications, "subprocess", SimpleNamespace(
        Popen=popen, DEVNULL=-3, CREATE_NO_WINDOW=0x08000000))
    assert notifications.notify_missing([{"source": "x", "reason": "Missing X_BEARER_TOKEN"}], ["bilibili"])
    popen.assert_called_once()
    assert popen.call_args.kwargs["creationflags"] == 0x08000000
    assert "--show" in popen.call_args.args[0]
    process.wait.assert_not_called()
    process.communicate.assert_not_called()


def test_headless_windows_never_launches_a_popup(monkeypatch):
    monkeypatch.setattr(notifications, "os", SimpleNamespace(name="nt", environ={"DEEP_WEBSEARCH_HEADLESS": "1"}))
    popen = Mock()
    monkeypatch.setattr(notifications, "subprocess", SimpleNamespace(Popen=popen))
    assert not notifications.notify_missing([{"source": "x", "reason": "Missing X_BEARER_TOKEN"}], [], True)
    popen.assert_not_called()
