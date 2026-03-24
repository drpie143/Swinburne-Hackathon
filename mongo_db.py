# ====================================================================
# MONGO_DB.PY - MongoDB Atlas Integration (Cloud-Hosted, Free Forever)
# ====================================================================
#
# Thay thế Amazon DynamoDB bằng MongoDB Atlas (M0 Free Tier).
#
# MONGODB ATLAS FREE TIER:
#   - Cloud-hosted: KHÔNG cần cài local, chỉ cần connection string
#   - Free forever (M0): 512 MB storage, shared RAM
#   - Document database: JSON-like documents (BSON)
#   - Đăng ký: https://www.mongodb.com/cloud/atlas/register
#
# FALLBACK:
#   Nếu chưa có MongoDB URI → dùng DynamoDBSimulator (in-memory)
#   Khi có URI → tự động dùng MongoDB Atlas thật
#
# COLLECTIONS:
#   customer_profiles: Thông tin KYC, behavioral baseline
#   transaction_history: Lịch sử giao dịch
# ====================================================================

from __future__ import annotations
from typing import Optional
from datetime import datetime, timedelta
import random

from config import settings


class MongoDBClient:
    """
    Client cho MongoDB Atlas (cloud-hosted document database).

    Cloud-hosted → không cần cài database server local.
    Chỉ cần 1 connection string từ Atlas console:
       mongodb+srv://user:password@cluster.xxxxx.mongodb.net/

    Khi không có credentials: fallback sang DynamoDBSimulator.
    """

    def __init__(self):
        """
        Khởi tạo MongoDB client.

        pymongo chỉ là DRIVER (client library),
        KHÔNG phải database server. Database chạy trên cloud Atlas.
        """
        self.client = None
        self.db = None
        self._use_simulator = True

        if settings.mongodb_uri:
            try:
                from pymongo import MongoClient

                self.client = MongoClient(
                    settings.mongodb_uri,
                    serverSelectionTimeoutMS=5000,
                )
                # Test connection
                self.client.admin.command("ping")
                self.db = self.client[settings.mongodb_db_name]
                self._use_simulator = False
                print(f"✅ MongoDB Atlas connected (db: {settings.mongodb_db_name})")
            except Exception as e:
                print(f"⚠️  MongoDB connection failed: {e}")
                print("   → Fallback: dùng DynamoDBSimulator (in-memory)")
                self.client = None
                self.db = None
                self._use_simulator = True
        else:
            print("ℹ️  MongoDB URI chưa cấu hình → dùng DynamoDBSimulator")

    @property
    def is_connected(self) -> bool:
        """Kiểm tra đã kết nối MongoDB Atlas chưa."""
        return self.db is not None and not self._use_simulator

    def close(self):
        """Đóng connection khi shutdown."""
        if self.client:
            self.client.close()

    # =================================================================
    # SEED DATA - Tạo sample data ban đầu cho demo
    # =================================================================

    def seed_demo_data(self):
        """
        Tạo document data mẫu trong MongoDB Atlas.

        Gọi 1 lần khi bắt đầu demo để populate collections.
        Data giống hệt DynamoDBSimulator.
        Idempotent: clear + insert lại.
        """
        if not self.is_connected:
            print("⚠️  Bỏ qua seed_demo_data (không có MongoDB connection)")
            return

        print("🌱 Seeding demo data vào MongoDB Atlas...")

        # ─── Customer profiles ───
        profiles_col = self.db["customer_profiles"]
        profiles_col.delete_many({})

        profiles = [
            {
                "_id": "ACC_001",
                "customer_id": "ACC_001",
                "name": "Nguyễn Văn An",
                "account_type": "savings",
                "kyc_status": "verified",
                "account_age_days": 1825,
                "avg_monthly_transactions": 12,
                "avg_transaction_amount": 500.0,
                "typical_channels": ["mobile", "web"],
                "typical_locations": ["Ho Chi Minh City", "Hanoi"],
                "risk_category": "low",
            },
            {
                "_id": "ACC_007",
                "customer_id": "ACC_007",
                "name": "Trần Thị B",
                "account_type": "checking",
                "kyc_status": "verified",
                "account_age_days": 45,
                "avg_monthly_transactions": 3,
                "avg_transaction_amount": 200.0,
                "typical_channels": ["mobile"],
                "typical_locations": ["Da Nang"],
                "risk_category": "medium",
            },
            {
                "_id": "ACC_050",
                "customer_id": "ACC_050",
                "name": "Unknown Entity",
                "account_type": "business",
                "kyc_status": "pending",
                "account_age_days": 15,
                "avg_monthly_transactions": 0,
                "avg_transaction_amount": 0.0,
                "typical_channels": ["web"],
                "typical_locations": ["Unknown"],
                "risk_category": "high",
            },
            {
                "_id": "MULE_001",
                "customer_id": "MULE_001",
                "name": "Phạm Văn X",
                "account_type": "checking",
                "kyc_status": "verified",
                "account_age_days": 90,
                "avg_monthly_transactions": 50,
                "avg_transaction_amount": 1500.0,
                "typical_channels": ["mobile", "web", "atm"],
                "typical_locations": ["Ho Chi Minh City", "Hanoi", "Singapore"],
                "risk_category": "high",
            },
            {
                "_id": "ACC_002",
                "customer_id": "ACC_002",
                "name": "Trần Minh Tuấn",
                "account_type": "personal",
                "kyc_status": "verified",
                "account_age_days": 1095,
                "avg_monthly_transactions": 8,
                "avg_transaction_amount": 400.0,
                "typical_channels": ["mobile", "web"],
                "typical_locations": ["Ho Chi Minh City"],
                "risk_category": "low",
            },
            {
                "_id": "ACC_666",
                "customer_id": "ACC_666",
                "name": "Blocked Account",
                "account_type": "personal",
                "kyc_status": "verified",
                "account_age_days": 365,
                "avg_monthly_transactions": 0,
                "avg_transaction_amount": 0.0,
                "typical_channels": [],
                "typical_locations": ["Unknown"],
                "risk_category": "critical",
            },
            {
                "_id": "MULE_002",
                "customer_id": "MULE_002",
                "name": "Lê Thị Y",
                "account_type": "checking",
                "kyc_status": "verified",
                "account_age_days": 75,
                "avg_monthly_transactions": 40,
                "avg_transaction_amount": 1200.0,
                "typical_channels": ["mobile", "web"],
                "typical_locations": ["Ho Chi Minh City", "Hanoi"],
                "risk_category": "high",
            },
            {
                "_id": "MULE_003",
                "customer_id": "MULE_003",
                "name": "Ngô Văn Z",
                "account_type": "checking",
                "kyc_status": "verified",
                "account_age_days": 60,
                "avg_monthly_transactions": 35,
                "avg_transaction_amount": 1000.0,
                "typical_channels": ["mobile"],
                "typical_locations": ["Ho Chi Minh City"],
                "risk_category": "high",
            },
        ]
        profiles_col.insert_many(profiles)

        # ─── Transaction history ───
        txn_col = self.db["transaction_history"]
        txn_col.delete_many({})

        now = datetime.now()
        transactions = []

        # ACC_007: 15 GD nhỏ liên tiếp → STRUCTURING
        for i in range(15):
            transactions.append({
                "account_id": "ACC_007",
                "transaction_id": f"TXN_007_{i:03d}",
                "timestamp": (now - timedelta(minutes=i * 8)).isoformat(),
                "amount": round(random.uniform(900, 999), 2),
                "receiver_id": f"MULE_{(i % 3) + 1:03d}",
                "type": "transfer",
                "channel": "mobile",
            })

        # ACC_050: GD lớn đột ngột
        transactions.extend([
            {
                "account_id": "ACC_050",
                "transaction_id": "TXN_050_001",
                "timestamp": (now - timedelta(hours=2)).isoformat(),
                "amount": 25000.00,
                "receiver_id": "ACC_666",
                "type": "transfer",
                "channel": "web",
            },
            {
                "account_id": "ACC_050",
                "transaction_id": "TXN_050_002",
                "timestamp": (now - timedelta(hours=1)).isoformat(),
                "amount": 15000.00,
                "receiver_id": "MULE_002",
                "type": "transfer",
                "channel": "web",
            },
        ])

        # ACC_001: GD bình thường
        for i in range(5):
            transactions.append({
                "account_id": "ACC_001",
                "transaction_id": f"TXN_001_{i:03d}",
                "timestamp": (now - timedelta(days=i * 3)).isoformat(),
                "amount": round(random.uniform(100, 800), 2),
                "receiver_id": "ACC_002",
                "type": "transfer",
                "channel": random.choice(["mobile", "web"]),
            })

        txn_col.insert_many(transactions)
        # Tạo index cho query nhanh
        txn_col.create_index("account_id")

        print(f"✅ Seeded {len(profiles)} profiles + {len(transactions)} transactions vào MongoDB Atlas")

    # =================================================================
    # QUERY METHODS
    # =================================================================

    def get_customer_profile(self, account_id: str) -> dict:
        """
        Lấy customer profile (KYC + behavioral baseline).

        Executor gọi khi làm task BEHAVIORAL_ANALYSIS.
        """
        if self._use_simulator:
            from simulators import dynamodb_sim
            return dynamodb_sim.get_customer_profile(account_id)

        try:
            doc = self.db["customer_profiles"].find_one({"_id": account_id})
            if doc:
                doc.pop("_id", None)
                return doc
            return {
                "customer_id": account_id,
                "name": "Unknown",
                "kyc_status": "not_found",
                "account_age_days": 0,
                "risk_category": "unknown",
            }
        except Exception as e:
            print(f"⚠️  MongoDB query error: {e}")
            from simulators import dynamodb_sim
            return dynamodb_sim.get_customer_profile(account_id)

    def get_transaction_history(self, account_id: str, limit: int = 20) -> list[dict]:
        """
        Lấy lịch sử giao dịch gần đây.

        Executor gọi khi làm task:
        - BEHAVIORAL_ANALYSIS: So sánh hành vi
        - AMOUNT_PATTERN: Phân tích mẫu số tiền
        - VELOCITY_CHECK: Đếm tần suất
        """
        if self._use_simulator:
            from simulators import dynamodb_sim
            return dynamodb_sim.get_transaction_history(account_id, limit)

        try:
            cursor = (
                self.db["transaction_history"]
                .find({"account_id": account_id})
                .sort("timestamp", -1)
                .limit(limit)
            )
            results = []
            for doc in cursor:
                doc.pop("_id", None)
                results.append(doc)
            return results
        except Exception as e:
            print(f"⚠️  MongoDB query error: {e}")
            from simulators import dynamodb_sim
            return dynamodb_sim.get_transaction_history(account_id, limit)

    def get_related_accounts(self, account_id: str) -> list[str]:
        """
        Tìm tài khoản liên quan (dựa trên lịch sử GD).
        """
        if self._use_simulator:
            from simulators import dynamodb_sim
            return dynamodb_sim.get_related_accounts(account_id)

        try:
            cursor = self.db["transaction_history"].find(
                {"account_id": account_id},
                {"receiver_id": 1},
            )
            related = set()
            for doc in cursor:
                if doc.get("receiver_id"):
                    related.add(doc["receiver_id"])
            return list(related)
        except Exception as e:
            print(f"⚠️  MongoDB query error: {e}")
            from simulators import dynamodb_sim
            return dynamodb_sim.get_related_accounts(account_id)

    def run_query(self, collection: str, filter_dict: dict, limit: int = 20) -> list[dict]:
        """
        Chạy read-only query trên MongoDB collection.

        Cho phép Executor Agent (LLM-driven) tạo query linh hoạt.
        Chỉ cho phép đọc từ collections đã định sẵn.

        Args:
            collection: Tên collection (chỉ cho phép customer_profiles, transaction_history)
            filter_dict: MongoDB filter document
            limit: Số kết quả tối đa (max 50)
        """
        allowed = {"customer_profiles", "transaction_history"}
        if collection not in allowed:
            print(f"⚠️  Collection '{collection}' không được phép query")
            return []

        if self._use_simulator:
            from simulators import dynamodb_sim
            if collection == "customer_profiles":
                acc = filter_dict.get("_id", filter_dict.get("customer_id", ""))
                if acc:
                    return [dynamodb_sim.get_customer_profile(acc)]
                return []
            elif collection == "transaction_history":
                acc = filter_dict.get("account_id", "")
                if acc:
                    return dynamodb_sim.get_transaction_history(acc, min(limit, 50))
                return []
            return []

        try:
            cursor = self.db[collection].find(filter_dict).limit(min(limit, 50))
            results = []
            for doc in cursor:
                doc.pop("_id", None)
                results.append(doc)
            return results
        except Exception as e:
            print(f"⚠️  MongoDB query error: {e}")
            return []

    def store_investigation_result(self, result: dict):
        """
        Lưu kết quả điều tra (cho audit trail).
        """
        if not self.is_connected:
            return

        try:
            self.db["investigation_results"].insert_one({
                **result,
                "stored_at": datetime.now().isoformat(),
            })
        except Exception as e:
            print(f"⚠️  MongoDB store error: {e}")


# =====================================================================
# SINGLETON INSTANCE
# =====================================================================

mongodb_client = MongoDBClient()
