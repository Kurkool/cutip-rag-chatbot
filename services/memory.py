import time
from collections import defaultdict

from config import settings


class ConversationMemory:
    """
    เก็บประวัติสนทนาแบบ In-Memory ต่อ user_id (LINE userId)
    มี TTL เพื่อลบประวัติอัตโนมัติเมื่อไม่มีข้อความมาสักพัก
    """

    def __init__(self):
        self._store: dict[str, list[dict]] = defaultdict(list)
        self._timestamps: dict[str, float] = {}

    def get_history(self, user_id: str) -> list[dict]:
        if user_id not in self._store:
            return []

        # ตรวจสอบว่าหมดอายุหรือยัง
        if time.time() - self._timestamps.get(user_id, 0) > settings.MEMORY_TTL:
            self.clear(user_id)
            return []

        return self._store[user_id][-settings.MAX_HISTORY_TURNS :]

    def add_turn(self, user_id: str, query: str, answer: str):
        self._store[user_id].append({"query": query, "answer": answer})
        self._timestamps[user_id] = time.time()

        # เก็บแค่ N รอบล่าสุด
        if len(self._store[user_id]) > settings.MAX_HISTORY_TURNS:
            self._store[user_id] = self._store[user_id][
                -settings.MAX_HISTORY_TURNS :
            ]

    def clear(self, user_id: str):
        self._store.pop(user_id, None)
        self._timestamps.pop(user_id, None)


# Singleton instance ใช้ร่วมกันทั้ง application
conversation_memory = ConversationMemory()
