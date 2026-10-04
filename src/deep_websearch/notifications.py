"""One best-effort, non-blocking Windows reminder per orchestration call."""
import os
import subprocess
import sys
from pathlib import Path


def notify_missing(missing: list[dict], enabled: list[str], mode="auto") -> bool:
    if not missing or mode is False or os.name != "nt":
        return False
    if os.environ.get("DEEP_WEBSEARCH_HEADLESS", "").lower() in ("1", "true", "yes"):
        return False
    if mode == "auto" and os.environ.get("SESSIONNAME", "").lower() == "services":
        return False
    try:
        import ctypes
        if not ctypes.windll.user32.GetProcessWindowStation():
            return False
        message = "部分搜索源未启用\n\n" + "\n".join(
            f"{item['source']}: {item['reason']}" for item in missing)
        message += "\n\n本次搜索继续使用：" + ("、".join(enabled) or "无可用搜索源")
        message += "\n请配置 .env / config.yaml 后重新运行。此提醒不阻塞搜索。"
        # A separate hidden process keeps MCP responsive even while the reminder is open.
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--show", message],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except (OSError, AttributeError):
        return False


if __name__ == "__main__" and os.name == "nt" and len(sys.argv) == 3 and sys.argv[1] == "--show":
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, sys.argv[2], "深度网络搜索：部分来源不可用", 0x40)
