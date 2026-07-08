import asyncio
import httpx
import json

async def test():
    payload = {
        "event": "message_created",
        "message_type": "outgoing",
        "private": False,
        "content": "hello from agent",
        "conversation": {"id": 1},
        "sender": {"name": "Agent"}
    }
    body = json.dumps(payload).encode()
    print(f"Sending body ({len(body)} bytes): {body}")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://localhost:8000/chatwoot/webhook",
            content=body,
            headers={"content-type": "application/json"}
        )
        print("Status:", r.status_code)
        print("Response:", r.text)

asyncio.run(test())
