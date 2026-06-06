"""Quick smoke test for OSRM container — requires OSRM running on localhost:5000.

Usage:
    # Start OSRM first:
    docker run --rm -p 5000:5000 -v osrm-data:/data krankenfahrt/osrm:latest

    # Then test:
    python3 scripts/test_osrm.py
"""

import sys
import typing
import urllib.request
import json


def test_health():
    """Test OSRM is reachable."""
    url = "http://localhost:5000/route/v1/driving/9.18,48.78;9.18,48.77?overview=false"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        return data.get("code") == "Ok", data
    except Exception as e:
        return False, str(e)


def main():
    ok, data = test_health()
    if ok:
        data = typing.cast(dict, data)
        route = data["routes"][0]
        dist_km = float(route["distance"]) / 1000
        dur_min = float(route["duration"]) / 60
        print(f"OSRM OK — distance: {dist_km:.2f} km, duration: {dur_min:.1f} min")
        return 0
    else:
        print(f"OSRM FAILED: {data}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
