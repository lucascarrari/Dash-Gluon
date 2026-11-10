import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from soilframe_dashboard.data_access import load_source
from soilframe_dashboard.ui import _gold_sources


class DashboardSmokeTests(unittest.TestCase):
    def test_configured_test_gold_is_discovered_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "gold_test.csv"
            expected = pd.DataFrame(
                {
                    "cell_id": [1, 2],
                    "data": ["2024-01-01", "2024-01-02"],
                    "uf": ["MT", "GO"],
                    "tmax_c": [32.0, 30.0],
                    "tmin_c": [21.0, 20.0],
                    "precipitacao_mm": [4.0, 2.0],
                    "et0_mm": [3.0, 2.5],
                }
            )
            expected.to_csv(source, index=False)
            previous = os.environ.get("SOILFRAME_GOLD_PATH")
            os.environ["SOILFRAME_GOLD_PATH"] = str(source)
            try:
                discovered = _gold_sources()
                self.assertIn(str(source), discovered.values())
                loaded = load_source(str(source))
                pd.testing.assert_frame_equal(loaded, expected)
            finally:
                if previous is None:
                    os.environ.pop("SOILFRAME_GOLD_PATH", None)
                else:
                    os.environ["SOILFRAME_GOLD_PATH"] = previous


if __name__ == "__main__":
    unittest.main()
