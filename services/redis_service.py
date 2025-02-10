import redis
from flask import current_app
import json

class RedisService:
    @staticmethod
    def save_pending_booking(slot_id, user_id, game_id):
        redis_conn = redis.StrictRedis.from_url(current_app.config['REDIS_URL'])
        # Convert dict to JSON string before saving
        pending_data = json.dumps({"user_id": user_id, "game_id": game_id})
        redis_conn.set(f"pending_booking:{slot_id}", pending_data, ex=120)  # TTL 2 mins

    @staticmethod
    def get_pending_booking(slot_id):
        redis_conn = redis.StrictRedis.from_url(current_app.config['REDIS_URL'])
        pending_data = redis_conn.get(f"pending_booking:{slot_id}")
        if pending_data:
            return json.loads(pending_data)  # Convert JSON string back to dict
        return None
