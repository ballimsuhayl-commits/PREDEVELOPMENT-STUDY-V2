from __future__ import annotations

from pathlib import Path
from typing import Dict

from .config import settings


def data_paths() -> Dict[str, Path]:
    return {
        "municipalities": Path(settings.municipalities_dir),
        "nsc_regions": Path(settings.nsc_regions_dir),
        "mpr_regions": Path(settings.mpr_regions_dir),
        "custom_regions": Path(settings.custom_regions_dir),
    }
