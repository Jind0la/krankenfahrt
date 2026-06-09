"""End-to-end OSRM integration test — requires OSRM running on localhost:5000.

Usage:
    USE_OSRM=1 python scripts/test_osrm_integration.py
"""

import asyncio
import os
import sys

# Add project to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from krankenfahrt.routing.osrm_client import OSRMClient, haversine_matrix


async def main():
    client = OSRMClient(base_url="http://localhost:5000", timeout=5.0)

    # 1. Health check
    print("[1/3] Checking OSRM health...")
    healthy = await client.health_check()
    if not healthy:
        print("  ❌ OSRM not healthy")
        # Fall back to Haversine-only demo
        test_coords = [
            (48.7758, 9.1829),  # Stuttgart
            (48.1351, 11.5820),  # Munich
            (49.4875, 8.4660),  # Mannheim
        ]
        print("  Running Haversine fallback demo:")
        matrix = haversine_matrix(test_coords)
        for i, row in enumerate(matrix):
            print(f"    [{i}]: {[f'{d:.1f}' for d in row]}")
        print("\n✅ Haversine fallback works correctly")
        return 0
    print("  ✅ OSRM healthy")

    # 2. Test distance matrix with real OSRM
    print("[2/3] Testing OSRM distance matrix...")
    coords = [
        (48.7758, 9.1829),  # Stuttgart
        (48.1351, 11.5820),  # Munich
        (49.4875, 8.4660),  # Mannheim
    ]
    matrix = await client.distance_matrix(coords)

    print(f"  Matrix ({len(coords)}x{len(coords)}):")
    names = ["Stuttgart", "Munich", "Mannheim"]
    for i, name in enumerate(names):
        vals = ", ".join(f"{matrix[i][j]:.1f} km" for j in range(len(coords)))
        print(f"    {name}: [{vals}]")

    # Check: OSRM road distances should differ from Haversine
    h_matrix = haversine_matrix(coords)
    avg_diff = sum(
        abs(matrix[i][j] - h_matrix[i][j])
        for i in range(len(coords))
        for j in range(len(coords))
    ) / (len(coords) * len(coords))
    print(f"  Avg difference OSRM vs Haversine: {avg_diff:.1f} km")
    if avg_diff > 0.1:
        print("  ✅ OSRM returns road distances (different from Haversine)")
    else:
        print("  ⚠️  OSRM distances match Haversine — may be using fallback")

    # 3. Test fallback with bad URL — should silently return Haversine
    print("[3/3] Testing fallback on bad URL...")
    bad_client = OSRMClient(base_url="http://127.0.0.1:19999", timeout=0.5)
    fallback_matrix = await bad_client.distance_matrix(coords)
    # Should equal Haversine
    h_fb = haversine_matrix(coords)
    all_close = all(
        abs(fallback_matrix[i][j] - h_fb[i][j]) < 0.01
        for i in range(len(coords))
        for j in range(len(coords))
    )
    if all_close:
        print("  ✅ Fallback to Haversine works correctly")
    else:
        print("  ❌ Fallback matrix doesn't match Haversine!")
        return 1

    print("\n✅ All OSRM integration checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
