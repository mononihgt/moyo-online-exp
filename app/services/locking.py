import asyncio
from collections import defaultdict

_room_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def room_lock(room_id: str) -> asyncio.Lock:
    return _room_locks[room_id]
