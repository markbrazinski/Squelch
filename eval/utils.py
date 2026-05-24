"""Shared CSV / IO helpers.

Promoted from eval/cluster.py in Bundle 3 Sessions 21-22 because three
modules need it (cluster, eval_lib, future github_integration) and the
deferred-import workaround in eval_lib.py was getting bent out of shape
to dodge the cycle.

Vendored to /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/.
"""

from __future__ import annotations

import csv
from pathlib import Path


def load_lookup(csv_path: Path | None) -> dict[str, str]:
    """Two-column CSV → {value: context}. Returns {} if path missing.

    Column 0 is the key; column 1 is the human-readable context. Header
    row is skipped (read positionally — DictReader-style names ignored).
    """
    if csv_path is None or not Path(csv_path).exists():
        return {}
    out: dict[str, str] = {}
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 2 and row[0]:
                out[row[0]] = row[1]
    return out
