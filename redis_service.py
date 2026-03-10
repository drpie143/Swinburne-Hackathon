# ====================================================================
# REDIS_SERVICE.PY - Unified Redis Interface (Real ↔ Simulator)
# ====================================================================
#
# Abstraction layer cho Phase 1 screening:
#   - Khi có Redis Cloud credentials → dùng real Redis
#   - Khi không có (DEMO_MODE=true) → fallback về RedisSimulator
#
# Cung cấp CÙNG API mà orchestrator.py, executor_agent.py,
# detective_agent.py đang gọi → không cần sửa logic gọi.
#
# REAL REDIS DATA STRUCTURE (from fraud-detection):
#   - blacklist          → SET of account IDs
#   - whitelist:{id}     → HASH {target_account: trust_score}
#   - account:{id}       → HASH {name, type, created_at, ...}
#   - rules:velocity     → HASH {max_transactions_per_hour, ...}
#   - rules:amount_threshold → HASH {instant_allow_max, ...}
#   - velocity:{id}:hourly  → STRING counter (INCR) with TTL
#   - velocity:{id}:daily   → STRING counter (INCR) with TTL
#   - txn:result:{txn_id}   → HASH (audit trail)
# ====================================================================

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from config import settings


class RedisService:
    """
    Unified Redis interface cho fraud detection system.
    
    Tự động chọn backend:
    - Real Redis Cloud (khi có credentials)
    - RedisSimulator in-memory (fallback)
    
    API giữ nguyên tương thích với RedisSimulator cũ.
    """
    
    def __init__(self):
        self._real_redis = None
        self._simulator = None
        self.is_connected = False
        self._mode = "simulator"  # "real" or "simulator"
        
        # Thử kết nối Real Redis nếu có credentials
        if (settings.redis_host 
            and settings.redis_host != "localhost"
            and settings.redis_password):
            try:
                from redis_client import get_redis_client
                client = get_redis_client()
                client.ping()
                self._real_redis = client
                self.is_connected = True
                self._mode = "real"
                print(f"   ✅ Redis: Cloud ({settings.redis_host})")
            except Exception as e:
                print(f"   ⚠️  Redis Cloud connection failed: {e}")
                print(f"   → Fallback to RedisSimulator (in-memory)")
                self._init_simulator()
        else:
            print(f"   ℹ️  Redis: Simulator (in-memory, DEMO_MODE)")
            self._init_simulator()
    
    def _init_simulator(self):
        """Initialize RedisSimulator as fallback."""
        from simulators import RedisSimulator
        self._simulator = RedisSimulator()
        self._mode = "simulator"
        self.is_connected = False
    
    # =================================================================
    # WHITELIST
    # =================================================================
    
    def is_whitelisted(self, account_id: str) -> bool:
        """Kiểm tra tài khoản có trong whitelist không."""
        if self._mode == "real":
            # Real Redis: whitelist là SET hoặc kiểm tra existence của hash key
            # Trong fraud-detection, whitelist:{sender} là HASH chứa trust scores
            # Account nằm trong whitelist nếu có key whitelist:{account_id} với entries
            wl_data = self._real_redis.hgetall(f"whitelist:{account_id}")
            return len(wl_data) > 0
        else:
            return self._simulator.is_whitelisted(account_id)
    
    # =================================================================
    # BLACKLIST
    # =================================================================
    
    def is_blacklisted(self, account_id: str) -> bool:
        """Kiểm tra tài khoản có trong blacklist không."""
        if self._mode == "real":
            return self._real_redis.sismember("blacklist", account_id)
        else:
            return self._simulator.is_blacklisted(account_id)
    
    # =================================================================
    # RISK SCORE
    # =================================================================
    
    def get_risk_score(self, account_id: str) -> float:
        """Lấy risk score hiện tại (default 0.3 nếu chưa có)."""
        if self._mode == "real":
            score = self._real_redis.hget(f"risk_score:{account_id}", "score")
            if score is not None:
                return float(score)
            # Fallback: tính dựa trên blacklist/whitelist status
            if self._real_redis.sismember("blacklist", account_id):
                return 0.95
            wl = self._real_redis.hgetall(f"whitelist:{account_id}")
            if wl:
                return 0.1
            return 0.3
        else:
            return self._simulator.get_risk_score(account_id)
    
    # =================================================================
    # VELOCITY
    # =================================================================
    
    def get_velocity(self, account_id: str, hours: int = 1) -> int:
        """Đếm số giao dịch trong N giờ qua."""
        if self._mode == "real":
            if hours <= 1:
                key = f"velocity:{account_id}:hourly"
            else:
                key = f"velocity:{account_id}:daily"
            count = self._real_redis.get(key)
            return int(count) if count else 0
        else:
            return self._simulator.get_velocity(account_id, hours)
    
    # =================================================================
    # WHITELIST UPDATE (Phase 3)
    # =================================================================
    
    def update_whitelist(self, account_id: str, add: bool = True):
        """Cập nhật whitelist (Phase 3: ALLOW → thêm vào whitelist)."""
        if self._mode == "real":
            if add:
                # Thêm vào whitelist: tạo hash key cho account
                self._real_redis.hset(f"whitelist:{account_id}", 
                                       mapping={"_status": "whitelisted"})
                # Xóa khỏi blacklist nếu có
                self._real_redis.srem("blacklist", account_id)
            else:
                self._real_redis.delete(f"whitelist:{account_id}")
        else:
            self._simulator.update_whitelist(account_id, add)
    
    # =================================================================
    # BLACKLIST UPDATE (Phase 3)
    # =================================================================
    
    def update_blacklist(self, account_id: str, add: bool = True):
        """Cập nhật blacklist (Phase 3: BLOCK → thêm vào blacklist)."""
        if self._mode == "real":
            if add:
                self._real_redis.sadd("blacklist", account_id)
                # Xóa khỏi whitelist nếu có
                self._real_redis.delete(f"whitelist:{account_id}")
            else:
                self._real_redis.srem("blacklist", account_id)
        else:
            self._simulator.update_blacklist(account_id, add)
    
    # =================================================================
    # RISK SCORE UPDATE (Phase 3)
    # =================================================================
    
    def update_risk_score(self, account_id: str, score: float):
        """Cập nhật risk score (Phase 3)."""
        score = max(0.0, min(1.0, score))
        if self._mode == "real":
            self._real_redis.hset(f"risk_score:{account_id}", 
                                   mapping={"score": str(score),
                                            "updated_at": datetime.now().isoformat()})
        else:
            self._simulator.update_risk_score(account_id, score)
    
    # =================================================================
    # TRUST SCORE (Real Redis only - từ Phase 1 fraud-detection)
    # =================================================================
    
    def get_trust_score(self, sender_id: str, receiver_id: str) -> Optional[int]:
        """
        Lấy trust score giữa sender và receiver.
        
        Trong real Redis: whitelist:{sender_id} → HASH {receiver_id: score}
        Trong simulator: không có concept này → return None
        """
        if self._mode == "real":
            score = self._real_redis.hget(f"whitelist:{sender_id}", receiver_id)
            return int(score) if score is not None else None
        else:
            return None
    
    # =================================================================
    # AMOUNT THRESHOLDS (Real Redis only - từ Phase 1 fraud-detection)
    # =================================================================
    
    def get_amount_thresholds(self) -> dict:
        """
        Lấy amount threshold rules từ Redis.
        
        Returns:
            dict với keys: instant_allow_max, escalate_threshold, 
            instant_block_threshold
        """
        if self._mode == "real":
            data = self._real_redis.hgetall("rules:amount_threshold")
            return {
                "instant_allow_max": float(data.get("instant_allow_max", 1000000)),
                "escalate_threshold": float(data.get("escalate_threshold", 20000000)),
                "instant_block_threshold": float(data.get("instant_block_threshold", 2000000000)),
                "currency": data.get("currency", "VND"),
            }
        else:
            # Simulator defaults (USD-based, matching existing orchestrator logic)
            return {
                "instant_allow_max": 1000,
                "escalate_threshold": 5000,
                "instant_block_threshold": 50000,
                "currency": "USD",
            }
    
    # =================================================================
    # VELOCITY RULES (Real Redis only)
    # =================================================================
    
    def get_velocity_rules(self) -> dict:
        """Lấy velocity rules từ Redis."""
        if self._mode == "real":
            data = self._real_redis.hgetall("rules:velocity")
            return {
                "max_transactions_per_hour": int(data.get("max_transactions_per_hour", 5)),
                "max_transactions_per_day": int(data.get("max_transactions_per_day", 20)),
                "max_amount_per_day": float(data.get("max_amount_per_day", 250000000)),
            }
        else:
            return {
                "max_transactions_per_hour": 5,
                "max_transactions_per_day": 20,
                "max_amount_per_day": 250000000,
            }
    
    # =================================================================
    # VELOCITY INCREMENT (tracking new transactions)
    # =================================================================
    
    def increment_velocity(self, account_id: str):
        """Tăng velocity counter khi có giao dịch mới."""
        if self._mode == "real":
            # Hourly counter
            hourly_key = f"velocity:{account_id}:hourly"
            hourly_count = self._real_redis.incr(hourly_key)
            if hourly_count == 1:
                self._real_redis.expire(hourly_key, 3600)
            
            # Daily counter
            daily_key = f"velocity:{account_id}:daily"
            daily_count = self._real_redis.incr(daily_key)
            if daily_count == 1:
                self._real_redis.expire(daily_key, 86400)
        else:
            self._simulator.increment_velocity(account_id)
    
    # =================================================================
    # AUDIT TRAIL (store transaction results)
    # =================================================================
    
    def store_transaction_result(self, txn_id: str, result: dict):
        """Lưu kết quả xử lý giao dịch vào Redis (audit trail)."""
        if self._mode == "real":
            self._real_redis.hset(f"txn:result:{txn_id}", mapping={
                k: str(v) for k, v in result.items()
            })
    
    # =================================================================
    # SEED DATA
    # =================================================================
    
    def seed_data(self):
        """
        Seed dữ liệu demo vào Redis Cloud.
        Port từ fraud-detection/src/data/seed.py.
        
        CHỈ gọi khi đang dùng real Redis.
        """
        if self._mode != "real":
            print("   ℹ️  Redis seed skipped (simulator mode)")
            return
        
        r = self._real_redis
        print("   📊 Seeding Redis Cloud data...")
        
        # ─── 1. Account Profiles ───
        accounts = {
            "ACC_001": {"name": "Nguyễn Văn An",   "type": "savings",  "created_at": "2023-01-15", "country": "VN", "status": "active"},
            "ACC_002": {"name": "Trần Minh Tuấn",   "type": "personal", "created_at": "2023-03-22", "country": "VN", "status": "active"},
            "ACC_003": {"name": "Charlie Le",       "type": "business", "created_at": "2022-11-10", "country": "VN", "status": "active"},
            "ACC_004": {"name": "Diana Pham",       "type": "personal", "created_at": "2023-06-05", "country": "AU", "status": "active"},
            "ACC_005": {"name": "Ethan Vo",         "type": "business", "created_at": "2022-08-20", "country": "AU", "status": "active"},
            "ACC_007": {"name": "Trần Thị B",       "type": "checking", "created_at": "2025-11-01", "country": "VN", "status": "active"},
            "ACC_010": {"name": "Julia Mai",        "type": "personal", "created_at": "2023-07-14", "country": "AU", "status": "active"},
            "ACC_050": {"name": "Unknown Entity",   "type": "business", "created_at": "2025-12-15", "country": "XX", "status": "active"},
        }
        for acc_id, profile in accounts.items():
            r.hset(f"account:{acc_id}", mapping=profile)
        print(f"      👤 Seeded {len(accounts)} account profiles")
        
        # ─── 2. Per-Account Whitelists with Trust Scores ───
        whitelists = {
            "ACC_001": {"ACC_002": "90", "ACC_003": "85", "ACC_005": "70", "ACC_010": "75"},
            "ACC_002": {"ACC_001": "95", "ACC_004": "80"},
            "ACC_003": {"ACC_001": "85", "ACC_005": "90"},
            "ACC_004": {"ACC_002": "75", "ACC_007": "85", "ACC_010": "90"},
            "ACC_005": {"ACC_003": "90", "ACC_001": "70"},
            "ACC_010": {"ACC_001": "85", "ACC_004": "90"},
        }
        for acc_id, trusted in whitelists.items():
            r.hset(f"whitelist:{acc_id}", mapping=trusted)
        print(f"      ✅ Seeded whitelists for {len(whitelists)} accounts")
        
        # ─── 3. System-wide Blacklist ───
        blacklisted = ["ACC_666", "ACC_999", "MULE_001", "MULE_002", "MULE_003"]
        for acc in blacklisted:
            r.sadd("blacklist", acc)
        # Profiles for blacklisted accounts
        fraud_accounts = {
            "ACC_666": {"name": "Blocked Account",   "type": "personal", "created_at": "2024-06-01", "country": "XX", "status": "blocked"},
            "ACC_999": {"name": "Scam Operator",     "type": "personal", "created_at": "2024-08-20", "country": "XX", "status": "blocked"},
            "MULE_001": {"name": "Phạm Văn X (Mule)", "type": "checking", "created_at": "2025-09-01", "country": "VN", "status": "blocked"},
            "MULE_002": {"name": "Lê Thị Y (Mule)",   "type": "checking", "created_at": "2025-09-15", "country": "VN", "status": "blocked"},
            "MULE_003": {"name": "Ngô Văn Z (Mule)",  "type": "checking", "created_at": "2025-10-01", "country": "VN", "status": "blocked"},
        }
        for acc_id, profile in fraud_accounts.items():
            r.hset(f"account:{acc_id}", mapping=profile)
        print(f"      🚫 Seeded {len(blacklisted)} blacklisted accounts")
        
        # ─── 4. Risk Scores ───
        risk_scores = {
            "ACC_001": 0.05, "ACC_002": 0.10, "ACC_003": 0.15,
            "ACC_004": 0.08, "ACC_005": 0.12, "ACC_007": 0.65,
            "ACC_010": 0.02, "ACC_050": 0.78,
            "ACC_666": 0.95, "ACC_999": 0.99,
            "MULE_001": 0.92, "MULE_002": 0.88, "MULE_003": 0.85,
        }
        for acc_id, score in risk_scores.items():
            r.hset(f"risk_score:{acc_id}", mapping={
                "score": str(score),
                "updated_at": datetime.now().isoformat(),
            })
        print(f"      📊 Seeded risk scores for {len(risk_scores)} accounts")
        
        # ─── 5. Velocity Counters (cho demo scenarios) ───
        # ACC_007: 15 GD/h (structuring pattern)
        hourly_key_007 = "velocity:ACC_007:hourly"
        for _ in range(15):
            r.incr(hourly_key_007)
        r.expire(hourly_key_007, 3600)
        daily_key_007 = "velocity:ACC_007:daily"
        for _ in range(15):
            r.incr(daily_key_007)
        r.expire(daily_key_007, 86400)
        
        # ACC_050: 8 GD/h (suspicious frequency)
        hourly_key_050 = "velocity:ACC_050:hourly"
        for _ in range(8):
            r.incr(hourly_key_050)
        r.expire(hourly_key_050, 3600)
        daily_key_050 = "velocity:ACC_050:daily"
        for _ in range(8):
            r.incr(daily_key_050)
        r.expire(daily_key_050, 86400)
        print(f"      ⏱️  Seeded velocity counters (ACC_007: 15/h, ACC_050: 8/h)")
        
        # ─── 6. Screening Rules ───
        r.hset("rules:velocity", mapping={
            "max_transactions_per_hour": "5",
            "max_transactions_per_day": "20",
            "max_amount_per_day": "250000000",
            "description": "Maximum allowed transaction frequency",
        })
        r.hset("rules:amount_threshold", mapping={
            "instant_allow_max": "1000000",
            "escalate_threshold": "20000000",
            "instant_block_threshold": "2000000000",
            "currency": "VND",
            "description": "Amount-based risk thresholds in VND",
        })
        print(f"      📋 Seeded screening rules (velocity + amount thresholds)")
        
        total_keys = r.dbsize()
        print(f"      🎉 Redis seeding complete! Total keys: {total_keys}")


# =====================================================================
# SINGLETON INSTANCE - Import từ các module khác
# =====================================================================

redis_service = RedisService()
