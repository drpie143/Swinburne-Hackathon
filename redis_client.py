# ====================================================================
# REDIS_CLIENT.PY - Kết nối Redis Cloud (ElastiCache-compatible)
# ====================================================================
# Port từ fraud-detection/src/config/redis_client.py
# Đọc config từ config.py (Settings) thay vì trực tiếp từ .env
# ====================================================================

from __future__ import annotations

import redis
from config import settings


def get_redis_client() -> redis.Redis:
    """
    Tạo và trả về Redis client kết nối đến Redis Cloud.
    
    Sử dụng credentials từ config.py / .env:
    - REDIS_HOST
    - REDIS_PORT
    - REDIS_USERNAME
    - REDIS_PASSWORD
    """
    r = redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        decode_responses=True,
        username=settings.redis_username,
        password=settings.redis_password,
    )
    return r


def test_redis_connection() -> bool:
    """
    Test kết nối Redis với PING/PONG.
    
    Returns:
        True nếu kết nối thành công, False nếu thất bại.
    """
    try:
        r = get_redis_client()
        response = r.ping()
        if response:
            print("✅ Successfully connected to Redis Cloud!")
            print(f"   Host: {settings.redis_host}")
            print(f"   Port: {settings.redis_port}")
            
            # Get server info
            info = r.info('server')
            print(f"   Redis Version: {info.get('redis_version', 'N/A')}")
            
            # Check DB size
            db_size = r.dbsize()
            print(f"   Current DB Size: {db_size} keys")
            return True
        else:
            print("❌ Redis PING failed!")
            return False
    except redis.ConnectionError as e:
        print(f"❌ Redis connection failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Redis unexpected error: {e}")
        return False


if __name__ == "__main__":
    test_redis_connection()
