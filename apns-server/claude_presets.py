"""Claude Code settings preset manager — list/apply/swap."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path

PRESETS_FILE = Path("/root/.claude/presets/presets.json")
SETTINGS_FILE = Path("/root/.claude/settings.json")


def _load_config() -> dict:
    if not PRESETS_FILE.exists():
        return {"presets": [], "active": ""}
    return json.loads(PRESETS_FILE.read_text())


def _save_config(cfg: dict):
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRESETS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))


def list_presets() -> dict:
    cfg = _load_config()
    return {"ok": True, "presets": cfg.get("presets", []), "active": cfg.get("active", "")}


def apply_preset(preset_id: str) -> dict:
    cfg = _load_config()
    preset = next((p for p in cfg.get("presets", []) if p["id"] == preset_id), None)
    if not preset:
        return {"ok": False, "error": f"preset '{preset_id}' not found"}

    src = Path(preset["file"])
    if not src.exists():
        return {"ok": False, "error": f"file not found: {src}"}

    shutil.copy2(str(src), str(SETTINGS_FILE))
    cfg["active"] = preset_id
    _save_config(cfg)
    return {"ok": True, "applied": preset_id}


def trigger_swap() -> dict:
    """Run swap.py in background to restart the Claude session."""
    try:
        subprocess.Popen(
            ["bash", "-c", "sleep 2 && python3 /root/swap.py"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "action": "swap_triggered"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def apply_and_swap(preset_id: str) -> dict:
    result = apply_preset(preset_id)
    if not result.get("ok"):
        return result
    swap_result = trigger_swap()
    result["swap"] = swap_result.get("ok", False)
    return result
