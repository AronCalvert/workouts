from __future__ import annotations

import json
import os
from pathlib import Path


class Preferences:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except Exception:
                pass

    @property
    def weight_unit(self) -> str:
        return self._data.get("weight_unit", "kg")

    @weight_unit.setter
    def weight_unit(self, value: str) -> None:
        if value not in ("kg", "lbs"):
            raise ValueError("weight_unit must be 'kg' or 'lbs'")
        self._data["weight_unit"] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def kg_to_display(self, kg: float) -> float:
        if self.weight_unit == "lbs":
            return round(kg * 2.20462, 1)
        return kg

    def display_to_kg(self, value: float) -> float:
        if self.weight_unit == "lbs":
            return round(value / 2.20462, 3)
        return value

    @property
    def weight_label(self) -> str:
        return self.weight_unit

    @property
    def weight_step(self) -> float:
        return 1.0 if self.weight_unit == "lbs" else 0.5

    @property
    def weight_max(self) -> float:
        return 999.0


def default_prefs_path(app_id: str) -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        base = Path(xdg_data_home)
    else:
        base = Path.home() / ".local" / "share"
    safe_dir = app_id.replace("/", "_")
    return base / safe_dir / "preferences.json"
