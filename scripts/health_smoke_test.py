"""Quick health endpoint test — starts server, curls it, stops."""
import asyncio
import sys
sys.path.insert(0, "src")

from krankenfahrt.health import HealthServer

async def test():
    server = HealthServer(host="127.0.0.1", port=9876, db_check=None)
    async with server:
        # Use raw socket to hit the health endpoint
        reader, writer = await asyncio.open_connection("127.0.0.1", 9876)
        writer.write(b"GET /health HTTP/1.0\r\n\r\n")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(4096), timeout=5.0)
        writer.close()
        await writer.wait_closed()
        
        text = response.decode()
        print(f"RESPONSE: {text}")
        
        if "200 OK" in text and '"status": "ok"' in text:
            print("✅ Health check PASSED")
            return 0
        else:
            print("❌ Health check FAILED")
            return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test()))
