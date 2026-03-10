# ====================================================================
# SETUP_DEMO.PY - Tạo Synthetic Data + Push lên DB
# ====================================================================
#
# Script này tạo DỮ LIỆU GIẢ LẬP và đẩy lên:
#   0. Redis Cloud   → Phase 1 data (whitelist, blacklist, risk scores, rules)
#   1. Neo4j AuraDB  → Graph data (accounts, devices, IPs, relationships)
#   2. MongoDB Atlas  → Customer profiles + Transaction history
#   3. ChromaDB Cloud → Fraud patterns knowledge base (trychroma.com)
#
# CÁCH DÙNG:
#   1. Cập nhật API keys trong file .env
#   2. Chạy: python setup_demo.py
#   3. Xong → chạy demo: python main.py
#
# ====================================================================

import sys
import os
import time
import random
from datetime import datetime, timedelta


# ─────────────────────────────────────────────────────────────
# SYNTHETIC DATA DEFINITIONS
# ─────────────────────────────────────────────────────────────

# ═══ NEO4J: Graph Data ═══
# 10 accounts, 3 devices, 4 IPs, 2 merchants, ~20 relationships

NEO4J_ACCOUNTS = [
    {"id": "ACC_001", "name": "Nguyễn Văn An",        "risk": "low",      "type": "savings",  "kyc_status": "verified", "account_age_days": 1825},
    {"id": "ACC_002", "name": "Trần Minh Tuấn",       "risk": "low",      "type": "checking"},
    {"id": "ACC_007", "name": "Trần Thị B",           "risk": "medium",   "type": "checking", "kyc_status": "verified", "account_age_days": 45},
    {"id": "ACC_008", "name": "Nguyễn Thị D",         "risk": "low",      "type": "savings"},
    {"id": "ACC_009", "name": "Lê Văn C",             "risk": "medium",   "type": "checking"},
    {"id": "ACC_050", "name": "Unknown Entity",        "risk": "high",     "type": "business", "kyc_status": "pending",  "account_age_days": 15},
    {"id": "ACC_666", "name": "Blocked Account",       "risk": "critical"},
    {"id": "MULE_001", "name": "Phạm Văn X (Mule)",   "risk": "high"},
    {"id": "MULE_002", "name": "Lê Thị Y (Mule)",     "risk": "high"},
    {"id": "MULE_003", "name": "Ngô Văn Z (Mule)",    "risk": "high"},
]

NEO4J_DEVICES = [
    {"id": "DEV_001",    "label": "iPhone 15 Pro"},
    {"id": "DEV_002",    "label": "Samsung Galaxy S24"},
    {"id": "DEV_SHARED", "label": "Shared Android Device"},
]

NEO4J_IPS = [
    {"id": "IP_NORMAL_1", "label": "14.161.x.x (HCMC)",   "is_vpn": False},
    {"id": "IP_NORMAL_2", "label": "113.190.x.x (Hanoi)",  "is_vpn": False},
    {"id": "IP_VPN",      "label": "185.220.x.x (Tor Exit)", "is_vpn": True},
    {"id": "IP_SHARED",   "label": "103.45.x.x (Shared)",  "is_vpn": False},
]

NEO4J_MERCHANTS = [
    {"id": "MERCH_001",   "label": "VinMart",           "is_shell": False},
    {"id": "MERCH_SHELL", "label": "Shell Company Ltd",  "is_shell": True},
]

# Relationships: (source, target, type, properties)
NEO4J_RELATIONSHIPS = [
    # ACC_001 - Normal user
    ("ACC_001", "DEV_001",    "USES_DEVICE",   {"since": "2022-01"}),
    ("ACC_001", "IP_NORMAL_1", "CONNECTS_FROM", {"frequency": "daily"}),
    ("ACC_001", "ACC_002",    "TRANSFERS_TO",  {"total_amount": 5000, "count": 10}),
    ("ACC_001", "MERCH_001",  "PAYS_TO",       {"total_amount": 2000, "count": 20}),

    # ACC_007 - Structuring suspect → STAR TOPOLOGY gửi đến 3 mule
    ("ACC_007", "DEV_002",    "USES_DEVICE",   {"since": "2025-11"}),
    ("ACC_007", "IP_NORMAL_2", "CONNECTS_FROM", {"frequency": "daily"}),
    ("ACC_007", "MULE_001",   "TRANSFERS_TO",  {"total_amount": 9500, "count": 5}),
    ("ACC_007", "MULE_002",   "TRANSFERS_TO",  {"total_amount": 8700, "count": 5}),
    ("ACC_007", "MULE_003",   "TRANSFERS_TO",  {"total_amount": 9200, "count": 5}),

    # MULE network → Shared device + IP (DENSE SUBGRAPH)
    ("MULE_001", "DEV_SHARED", "USES_DEVICE",   {"since": "2025-12"}),
    ("MULE_002", "DEV_SHARED", "USES_DEVICE",   {"since": "2025-12"}),
    ("MULE_003", "DEV_SHARED", "USES_DEVICE",   {"since": "2025-12"}),
    ("MULE_001", "IP_SHARED",  "CONNECTS_FROM", {"frequency": "daily"}),
    ("MULE_002", "IP_SHARED",  "CONNECTS_FROM", {"frequency": "daily"}),
    ("MULE_003", "IP_SHARED",  "CONNECTS_FROM", {"frequency": "daily"}),

    # MULES → ACC_666 (tiền đổ về 1 tài khoản blocked)
    ("MULE_001", "ACC_666", "TRANSFERS_TO", {"total_amount": 9000, "count": 3}),
    ("MULE_002", "ACC_666", "TRANSFERS_TO", {"total_amount": 8500, "count": 3}),
    ("MULE_003", "ACC_666", "TRANSFERS_TO", {"total_amount": 9000, "count": 3}),

    # ACC_050 - VPN user → gửi tiền lớn đến blacklisted
    ("ACC_050", "IP_VPN",      "CONNECTS_FROM", {"frequency": "always"}),
    ("ACC_050", "ACC_666",     "TRANSFERS_TO",  {"total_amount": 25000, "count": 1}),
    ("ACC_050", "MULE_002",    "TRANSFERS_TO",  {"total_amount": 15000, "count": 1}),
    ("ACC_050", "MERCH_SHELL", "PAYS_TO",       {"total_amount": 10000, "count": 2}),
]


# ═══ MONGODB: Customer Profiles ═══

MONGO_PROFILES = [
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


def generate_transactions():
    """Tạo synthetic transaction history."""
    now = datetime.now()
    transactions = []

    # ACC_007: 15 GD nhỏ liên tiếp → pattern STRUCTURING
    #   Mỗi GD $900-$999 (ngay dưới $1000 threshold)
    #   Gửi luân phiên đến 3 mule accounts
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

    # ACC_050: 2 GD lớn đột ngột → suspicious large transfers
    #   Account mới 15 ngày, chưa verify KYC, dùng VPN
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

    # ACC_001: 5 GD bình thường → baseline normal behavior
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

    return transactions


# ═══ CHROMADB: Fraud Knowledge Base ═══

CHROMA_DOCUMENTS = [
    {
        "id": "pattern_structuring",
        "text": (
            "Structuring / Smurfing Pattern: Nhiều giao dịch nhỏ ngay dưới "
            "reporting threshold ($10,000 hoặc $1,000) được thực hiện trong "
            "thời gian ngắn để tránh trigger cảnh báo tự động. Thường gửi "
            "đến nhiều tài khoản khác nhau (money mules). Indicators: "
            "Số tiền ngay dưới threshold ($999, $9,999), nhiều GD trong thời "
            "gian ngắn (>10 GD/giờ), gửi đến nhiều tài khoản khác nhau, "
            "tổng số tiền lớn nhưng mỗi GD nhỏ."
        ),
        "metadata": {"type": "fraud_pattern", "risk_level": "high",
                     "confidence_boost": 0.3, "title": "Structuring / Smurfing Pattern"},
    },
    {
        "id": "pattern_money_mule",
        "text": (
            "Money Mule Network: Mạng lưới tài khoản trung gian (money mules) "
            "được sử dụng để chuyển tiền phi pháp qua nhiều lớp. Các mule "
            "accounts thường dùng chung thiết bị hoặc IP, được tạo gần đây, "
            "và nhận tiền từ nhiều nguồn rồi chuyển đến một tài khoản tập trung. "
            "Indicators: Nhiều accounts dùng chung device/IP, tài khoản mới "
            "(<90 ngày), star topology trong graph."
        ),
        "metadata": {"type": "fraud_pattern", "risk_level": "critical",
                     "confidence_boost": 0.35, "title": "Money Mule Network"},
    },
    {
        "id": "pattern_ato",
        "text": (
            "Account Takeover (ATO): Tài khoản bị chiếm đoạt - thay đổi "
            "đột ngột về device, IP, location, hoặc pattern giao dịch. "
            "Kẻ gian thường thực hiện GD lớn ngay sau khi take over. "
            "Indicators: Device mới chưa từng thấy, IP/Location khác biệt "
            "hoàn toàn, GD lớn đột ngột (>5x average)."
        ),
        "metadata": {"type": "fraud_pattern", "risk_level": "high",
                     "confidence_boost": 0.25, "title": "Account Takeover (ATO)"},
    },
    {
        "id": "pattern_app_fraud",
        "text": (
            "Authorized Push Payment (APP) Fraud: Nạn nhân bị social engineering "
            "lừa tự nguyện chuyển tiền. GD lớn bất thường, chuyển đến tài khoản lạ. "
            "Indicators: GD lớn đến tài khoản mới (first-time recipient), "
            "nạn nhân thay đổi hành vi đột ngột, urgency signals."
        ),
        "metadata": {"type": "fraud_pattern", "risk_level": "high",
                     "confidence_boost": 0.2, "title": "APP Fraud"},
    },
    {
        "id": "case_acc666",
        "text": (
            "Past Case: ACC_666 Money Laundering Ring - ACC_666 được xác nhận "
            "là trung tâm của mạng lưới rửa tiền. Nhận tiền từ 15+ mule accounts, "
            "tổng $500K+ trong 3 tháng. Liên quan: MULE_001, MULE_002, MULE_003, "
            "ACC_050. Đã bị BLOCK. Date: 2025-09-15."
        ),
        "metadata": {"type": "past_investigation", "decision": "BLOCK",
                     "title": "Case: ACC_666 Money Laundering Ring",
                     "related_accounts": "MULE_001,MULE_002,MULE_003,ACC_050"},
    },
    {
        "id": "rule_bsa_aml",
        "text": (
            "BSA/AML Reporting Threshold: Bank Secrecy Act yêu cầu báo cáo "
            "CTR cho mọi giao dịch > $10,000. Structuring để tránh threshold "
            "này là vi phạm pháp luật liên bang. Threshold: $10,000 cho CTR, "
            "$5,000 cho SAR review."
        ),
        "metadata": {"type": "regulatory_rule", "title": "BSA/AML Reporting Threshold",
                     "threshold": "10000"},
    },
]


# ─────────────────────────────────────────────────────────────
# PUSH FUNCTIONS
# ─────────────────────────────────────────────────────────────

def push_redis():
    """Đẩy Phase 1 data lên Redis Cloud."""
    print("\n" + "─" * 55)
    print("🔑 [0/4] REDIS CLOUD - Phase 1 Screening Data")
    print("─" * 55)

    from config import settings
    if not settings.redis_password or settings.redis_host == "localhost":
        print("  ⏭️  SKIP: Chưa cấu hình REDIS_HOST/REDIS_PASSWORD trong .env")
        print("  → Hệ thống sẽ dùng RedisSimulator (in-memory)")
        return False

    try:
        import redis
        r = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
            username=settings.redis_username,
            password=settings.redis_password,
        )
        r.ping()
        print(f"  ✅ Connected: {settings.redis_host}:{settings.redis_port}")
    except Exception as e:
        print(f"  ❌ Không kết nối được Redis: {e}")
        return False

    # Clear old Phase 1 data (selective — chỉ xóa keys Phase 1)
    for pattern in ["account:*", "whitelist:*", "risk_score:*",
                    "velocity:*", "rules:*", "txn:result:*"]:
        for key in r.scan_iter(match=pattern):
            r.delete(key)
    r.delete("blacklist")
    print("  🗑️  Cleared old Phase 1 data")

    # ─── Account Profiles ───
    accounts = {
        "ACC_001": {"name": "Nguyễn Văn An",      "type": "savings",  "created_at": "2023-01-15", "country": "VN", "status": "active"},
        "ACC_002": {"name": "Trần Minh Tuấn",     "type": "personal", "created_at": "2023-03-22", "country": "VN", "status": "active"},
        "ACC_003": {"name": "Charlie Le",          "type": "business", "created_at": "2022-11-10", "country": "VN", "status": "active"},
        "ACC_004": {"name": "Diana Pham",          "type": "personal", "created_at": "2023-06-05", "country": "AU", "status": "active"},
        "ACC_005": {"name": "Ethan Vo",            "type": "business", "created_at": "2022-08-20", "country": "AU", "status": "active"},
        "ACC_007": {"name": "Trần Thị B",          "type": "checking", "created_at": "2025-11-01", "country": "VN", "status": "active"},
        "ACC_008": {"name": "Nguyễn Thị D",        "type": "savings",  "created_at": "2023-08-12", "country": "VN", "status": "active"},
        "ACC_009": {"name": "Lê Văn C",            "type": "checking", "created_at": "2024-01-20", "country": "VN", "status": "active"},
        "ACC_010": {"name": "Julia Mai",            "type": "personal", "created_at": "2023-07-14", "country": "AU", "status": "active"},
        "ACC_050": {"name": "Unknown Entity",       "type": "business", "created_at": "2025-12-15", "country": "XX", "status": "active"},
    }
    for acc_id, profile in accounts.items():
        r.hset(f"account:{acc_id}", mapping=profile)
    print(f"  ✅ {len(accounts)} account profiles")

    # ─── Per-Account Whitelists with Trust Scores ───
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
    print(f"  ✅ Whitelists for {len(whitelists)} accounts")

    # ─── System-wide Blacklist ───
    blacklisted = ["ACC_666", "ACC_999", "MULE_001", "MULE_002", "MULE_003"]
    for acc in blacklisted:
        r.sadd("blacklist", acc)
    fraud_accounts = {
        "ACC_666": {"name": "Blocked Account",      "type": "personal", "status": "blocked"},
        "ACC_999": {"name": "Scam Operator",         "type": "personal", "status": "blocked"},
        "MULE_001": {"name": "Phạm Văn X (Mule)",   "type": "checking", "status": "blocked"},
        "MULE_002": {"name": "Lê Thị Y (Mule)",     "type": "checking", "status": "blocked"},
        "MULE_003": {"name": "Ngô Văn Z (Mule)",    "type": "checking", "status": "blocked"},
    }
    for acc_id, profile in fraud_accounts.items():
        r.hset(f"account:{acc_id}", mapping=profile)
    print(f"  ✅ {len(blacklisted)} blacklisted accounts")

    # ─── Risk Scores ───
    risk_scores = {
        "ACC_001": 0.05, "ACC_002": 0.10, "ACC_003": 0.15,
        "ACC_004": 0.08, "ACC_005": 0.12, "ACC_007": 0.65,
        "ACC_010": 0.02, "ACC_050": 0.78,
        "ACC_666": 0.95, "ACC_999": 0.99,
        "MULE_001": 0.92, "MULE_002": 0.88, "MULE_003": 0.85,
    }
    now_iso = datetime.now().isoformat()
    for acc_id, score in risk_scores.items():
        r.hset(f"risk_score:{acc_id}", mapping={"score": str(score), "updated_at": now_iso})
    print(f"  ✅ Risk scores for {len(risk_scores)} accounts")

    # ─── Screening Rules ───
    r.hset("rules:velocity", mapping={
        "max_transactions_per_hour": "5",
        "max_transactions_per_day": "20",
        "max_amount_per_day": "250000000",
    })
    r.hset("rules:amount_threshold", mapping={
        "instant_allow_max": "1000000",
        "escalate_threshold": "20000000",
        "instant_block_threshold": "2000000000",
        "currency": "VND",
    })
    print(f"  ✅ Screening rules (velocity + amount thresholds)")

    # Simulate velocity for suspicious accounts
    for _ in range(15):
        r.incr("velocity:ACC_007:hourly")
    r.expire("velocity:ACC_007:hourly", 3600)
    for _ in range(8):
        r.incr("velocity:ACC_050:hourly")
    r.expire("velocity:ACC_050:hourly", 3600)
    print(f"  ✅ Velocity counters (ACC_007: 15/h, ACC_050: 8/h)")

    total_keys = r.dbsize()
    print(f"\n  📊 TỔNG: {total_keys} keys in Redis")
    return True


def push_neo4j():
    """Đẩy graph data lên Neo4j AuraDB."""
    print("\n" + "─" * 55)
    print("📊 [1/4] NEO4J AURADB - Graph Data")
    print("─" * 55)

    from config import settings
    if not settings.neo4j_password or settings.neo4j_password == "your-neo4j-password-here":
        print("  ⏭️  SKIP: Chưa cấu hình NEO4J_PASSWORD trong .env")
        return False

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        driver.verify_connectivity()
        print(f"  ✅ Connected: {settings.neo4j_uri}")
    except Exception as e:
        print(f"  ❌ Không kết nối được Neo4j: {e}")
        return False

    with driver.session() as session:
        # Clear
        session.run("MATCH (n) DETACH DELETE n")
        print("  🗑️  Cleared old data")

        # Accounts
        for acc in NEO4J_ACCOUNTS:
            props = ", ".join(f"{k}: ${k}" for k in acc)
            session.run(f"CREATE (:Account {{{props}}})", **acc)
        print(f"  ✅ {len(NEO4J_ACCOUNTS)} Account nodes")

        # Devices
        for dev in NEO4J_DEVICES:
            session.run("CREATE (:Device {id: $id, label: $label})", **dev)
        print(f"  ✅ {len(NEO4J_DEVICES)} Device nodes")

        # IPs
        for ip in NEO4J_IPS:
            session.run("CREATE (:IP {id: $id, label: $label, is_vpn: $is_vpn})", **ip)
        print(f"  ✅ {len(NEO4J_IPS)} IP nodes")

        # Merchants
        for m in NEO4J_MERCHANTS:
            session.run("CREATE (:Merchant {id: $id, label: $label, is_shell: $is_shell})", **m)
        print(f"  ✅ {len(NEO4J_MERCHANTS)} Merchant nodes")

        # Relationships
        for src, tgt, rel_type, props in NEO4J_RELATIONSHIPS:
            prop_str = ", ".join(f"{k}: ${k}" for k in props)
            session.run(
                f"MATCH (a {{id: $src}}), (b {{id: $tgt}}) "
                f"CREATE (a)-[:{rel_type} {{{prop_str}}}]->(b)",
                src=src, tgt=tgt, **props,
            )
        print(f"  ✅ {len(NEO4J_RELATIONSHIPS)} relationships")

    # Verify
    with driver.session() as session:
        count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        edges = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        print(f"\n  📊 TỔNG: {count} nodes, {edges} relationships")

    driver.close()
    return True


def push_mongodb():
    """Đẩy profiles + transactions lên MongoDB Atlas."""
    print("\n" + "─" * 55)
    print("📦 [2/4] MONGODB ATLAS - Document Data")
    print("─" * 55)

    from config import settings
    if not settings.mongodb_uri or "xxxxx" in settings.mongodb_uri:
        print("  ⏭️  SKIP: Chưa cấu hình MONGODB_URI trong .env")
        return False

    try:
        from pymongo import MongoClient
        client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        db = client[settings.mongodb_db_name]
        print(f"  ✅ Connected: {settings.mongodb_db_name}")
    except Exception as e:
        print(f"  ❌ Không kết nối được MongoDB: {e}")
        return False

    # Profiles
    profiles_col = db["customer_profiles"]
    profiles_col.delete_many({})
    profiles_col.insert_many(MONGO_PROFILES)
    print(f"  ✅ {len(MONGO_PROFILES)} customer profiles")

    # Print sample
    for p in MONGO_PROFILES:
        print(f"     • {p['_id']}: {p['name']} (KYC={p['kyc_status']}, risk={p['risk_category']})")

    # Transactions
    transactions = generate_transactions()
    txn_col = db["transaction_history"]
    txn_col.delete_many({})
    txn_col.insert_many(transactions)
    txn_col.create_index("account_id")
    print(f"  ✅ {len(transactions)} transaction records")

    # Summary per account
    for acc_id in ["ACC_001", "ACC_007", "ACC_050"]:
        count = txn_col.count_documents({"account_id": acc_id})
        sample = txn_col.find_one({"account_id": acc_id})
        amt = sample["amount"] if sample else 0
        print(f"     • {acc_id}: {count} GD (sample: ${amt:,.2f})")

    # Verify
    total_profiles = profiles_col.count_documents({})
    total_txns = txn_col.count_documents({})
    print(f"\n  📊 TỔNG: {total_profiles} profiles, {total_txns} transactions")

    client.close()
    return True


def push_chromadb():
    """Đẩy fraud knowledge vào ChromaDB Cloud (trychroma.com)."""
    print("\n" + "─" * 55)
    print("🔍 [3/4] CHROMADB - Fraud Knowledge Base (cloud)")
    print("─" * 55)

    try:
        import chromadb
    except Exception:
        print("  ⏭️  SKIP: ChromaDB không tương thích Python hiện tại")
        print("  → Hệ thống tự dùng OpenSearchSimulator làm fallback")
        return False

    from config import settings
    if not settings.chroma_api_key:
        print("  ⏭️  SKIP: CHROMA_API_KEY chưa cấu hình")
        return False

    try:
        client = chromadb.HttpClient(
            host=settings.chroma_host,
            ssl=True,
            headers={"x-chroma-token": settings.chroma_api_key},
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
        )
        # Delete + recreate
        try:
            client.delete_collection(settings.chroma_collection_name)
        except Exception:
            pass
        collection = client.create_collection(
            name=settings.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"  ✅ Collection: {settings.chroma_collection_name}")
    except Exception as e:
        print(f"  ❌ ChromaDB Cloud error: {e}")
        print("  → Hệ thống tự dùng OpenSearchSimulator làm fallback")
        return False

    # Add documents
    collection.add(
        ids=[d["id"] for d in CHROMA_DOCUMENTS],
        documents=[d["text"] for d in CHROMA_DOCUMENTS],
        metadatas=[d["metadata"] for d in CHROMA_DOCUMENTS],
    )

    for d in CHROMA_DOCUMENTS:
        dtype = d["metadata"]["type"]
        title = d["metadata"]["title"]
        print(f"  ✅ [{dtype}] {title}")

    # Verify search
    results = collection.query(query_texts=["structuring money laundering"], n_results=1)
    if results["ids"] and results["ids"][0]:
        top = results["metadatas"][0][0]["title"]
        print(f"\n  🔎 Test search 'structuring money laundering' → {top}")

    print(f"\n  📊 TỔNG: {collection.count()} documents")
    return True


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("\n" + "🔥" * 28)
    print("  FRAUD DETECTION - DATA SETUP")
    print("🔥" * 28)

    # Check .env exists
    from dotenv import load_dotenv
    load_dotenv()

    results = {}

    # Push data
    results["Redis"] = push_redis()
    results["Neo4j"] = push_neo4j()
    results["MongoDB"] = push_mongodb()
    results["ChromaDB"] = push_chromadb()

    # Summary
    print("\n" + "=" * 55)
    print("  📋 KẾT QUẢ SETUP")
    print("=" * 55)
    for name, ok in results.items():
        icon = "✅" if ok else "⏭️ "
        status = "Data đã push!" if ok else "Skipped (dùng simulator fallback)"
        print(f"  {icon} {name}: {status}")

    ok_count = sum(1 for v in results.values() if v)
    print(f"\n  → {ok_count}/4 databases đã có data thật")

    if ok_count < 4:
        print("\n  ⚠️  Các DB chưa push sẽ dùng SIMULATOR (data giả lập in-memory)")
        print("  → Demo vẫn chạy OK, chỉ không query DB thật")

    print(f"\n  ▶️  Tiếp theo: python main.py")
    print()


if __name__ == "__main__":
    main()
