from datetime import date
import pandas as pd

def test_previous_day_plus_one_is_date_safe():
    prev_day = date(2026, 9, 15)
    assert (prev_day + pd.Timedelta(days=1)).isoformat() == "2026-09-16"
