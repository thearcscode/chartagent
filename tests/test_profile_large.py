"""10 GB-class source: peak RSS stays under 500 MB (ADR-0011 Decision 7).

Excluded from the default run. Set ``CHARTAGENT_LARGE=1`` to execute.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

_BUDGET_RSS = 500 * 1024 * 1024
_TEN_GB_ROWS = (10 * 1024 * 1024 * 1024) // 8

pytestmark = [
    pytest.mark.large,
    pytest.mark.skipif(
        os.environ.get("CHARTAGENT_LARGE") != "1",
        reason="10 GB-class source; set CHARTAGENT_LARGE=1 to run",
    ),
]


def test_ten_gb_class_parquet_peaks_under_500mb(tmp_path: Path) -> None:
    path = tmp_path / "tall.parquet"
    quoted = str(path).replace("'", "''")
    connection = duckdb.connect()
    try:
        connection.execute(
            f"COPY (SELECT i::BIGINT AS n FROM range({_TEN_GB_ROWS}) t(i)) "
            f"TO '{quoted}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()

    script = r"""
import resource
import sys
from pathlib import Path

from chartagent.profile import profile_source

profile_source(Path(sys.argv[1]))
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if sys.platform == "darwin":
    print(rss)
else:
    print(rss * 1024)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    peak = int(result.stdout.strip())
    assert peak < _BUDGET_RSS, f"peak RSS {peak} bytes"
