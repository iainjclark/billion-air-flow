# utils/filesystem.py
"""
Filesystem utilities for billion-air-flow.

Provides OS-aware base paths for hot (fast NVMe), cold (HDD),
and optionally warm (external SSD) storage.
Works on Windows and Linux (Ubuntu).
"""

import platform
import os


def filesystem_data_paths(dataset: str = "") -> dict:
    """
    Return OS-specific base paths for hotdata and colddata.

    Args:
        dataset (str): Optional subfolder name (e.g., "nyc_tlc").
                       If empty, returns just the root tier paths.

    On Windows (change drive letters if needed):
        HOTDATA → D:/nyc_tlc
        COLDDATA → E:/nyc_tlc
    On Linux:
        HOTDATA → /hotdata/nyc_tlc
        COLDDATA → /colddata/nyc_tlc
    """
    tiers = ["hot", "cold"]  # future: add "warm"

    if platform.system() == "Windows":
        roots = {"hot": "D:/", "cold": "E:/"}  # e.g. add "warm": "F:/"
    else:
        roots = {x: f"/{x}data" for x in tiers}  # /hotdata, /colddata

    paths = {}
    for tier in tiers:
        base = roots[tier]
        path = os.path.join(base, dataset) if dataset else base

        try:
            os.makedirs(path, exist_ok=True)
        except PermissionError:
            print(f"⚠️ Warning: Could not create/access {path} (check permissions or mount).")

        if not os.path.exists(path):
            print(f"⚠️ Warning: {tier.upper()} storage path not available: {path}")

        paths[tier] = path

    return paths
