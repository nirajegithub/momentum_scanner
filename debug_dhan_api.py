#!/usr/bin/env python3
"""
Diagnostic script to test Dhan API intraday data availability.
"""
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from app.dhan_client import DhanClient

IST = ZoneInfo("Asia/Kolkata")

def test_intraday_api():
    dhan = DhanClient()

    # Test with current date and a few sample securities
    now_ist = datetime.now(IST)
    trading_day = now_ist.date()

    print(f"\n{'='*80}")
    print(f"Dhan Intraday API Diagnostic Test")
    print(f"{'='*80}")
    print(f"Current time (IST): {now_ist.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Trading day: {trading_day}")
    print(f"Testing date range: {trading_day.isoformat()} to {(trading_day + pd.Timedelta(days=1)).isoformat()}")

    # Test securities with different patterns
    test_securities = [
        ("99926000", "NIFTY50"),        # Index
        ("27061", "ACMESOLAR"),          # Regular stock
        ("1363", "HINDALCO"),            # Regular stock
    ]

    for security_id, name in test_securities:
        print(f"\n{'-'*80}")
        print(f"Testing {name} (security_id={security_id})")
        print(f"{'-'*80}")

        try:
            # Make raw API call to understand response
            import requests
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "access-token": os.environ.get("DHAN_ACCESS_TOKEN"),
            }
            payload = {
                "securityId": str(security_id),
                "exchangeSegment": "NSE_EQ",
                "instrument": "EQUITY",
                "interval": "15",
                "oi": False,
                "fromDate": trading_day.isoformat(),
                "toDate": (trading_day + pd.Timedelta(days=1)).isoformat(),
            }

            print(f"Request payload: {json.dumps(payload, indent=2)}")

            response = requests.post(
                "https://api.dhan.co/v2/charts/intraday",
                headers=headers,
                json=payload,
                timeout=30
            )

            print(f"HTTP Status: {response.status_code}")
            print(f"Response size: {len(response.text)} bytes")

            resp_json = response.json()
            print(f"Response top-level keys: {list(resp_json.keys())}")

            # Check if nested or flat
            if "data" in resp_json and isinstance(resp_json["data"], dict):
                print(f"Response format: NESTED (has 'data' key)")
                data = resp_json["data"]
                if "status" in resp_json:
                    print(f"Status: {resp_json['status']}")
            else:
                print(f"Response format: FLAT (direct OHLCV arrays)")
                data = resp_json

            # Check candle counts
            required = ["timestamp", "open", "high", "low", "close", "volume"]
            print(f"\nCandle array lengths:")
            for key in required:
                arr = data.get(key, [])
                if isinstance(arr, list):
                    print(f"  {key}: {len(arr)} elements")
                else:
                    print(f"  {key}: NOT A LIST (type={type(arr).__name__})")

            # If data available, show first/last timestamps
            if data.get("timestamp") and len(data["timestamp"]) > 0:
                timestamps = data["timestamp"]
                print(f"\nFirst timestamp: {timestamps[0]} (epoch seconds)")
                print(f"Last timestamp: {timestamps[-1]} (epoch seconds)")

                # Convert to IST for readability
                first_ist = pd.Timestamp(timestamps[0], unit='s', tz='UTC').tz_convert(IST)
                last_ist = pd.Timestamp(timestamps[-1], unit='s', tz='UTC').tz_convert(IST)
                print(f"First candle (IST): {first_ist.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                print(f"Last candle (IST): {last_ist.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            else:
                print(f"\n⚠️  NO CANDLE DATA RETURNED (empty arrays)")

        except Exception as exc:
            print(f"❌ Error: {exc}")

    print(f"\n{'='*80}\n")

if __name__ == "__main__":
    test_intraday_api()
