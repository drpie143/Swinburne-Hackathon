# ====================================================================
# SIMULATORS.PY - Giả lập Database cho Demo
# ====================================================================
# Trong hackathon demo, ta không cần AWS thật.
# File này giả lập TẤT CẢ databases bằng in-memory data:
#
#   1. RedisSimulator     → Thay thế Amazon ElastiCache for Redis
#   2. DynamoDBSimulator  → Thay thế Amazon DynamoDB
#   3. NeptuneSimulator   → Thay thế Amazon Neptune (Graph DB)
#   4. OpenSearchSimulator→ Thay thế Amazon OpenSearch (RAG)
#
# Mỗi simulator chứa sample data phù hợp với fraud detection scenario.
# Khi deploy thật, chỉ cần swap sang real client (boto3, redis-py, etc.)
# ====================================================================

from __future__ import annotations
import json
from datetime import datetime, timedelta
from typing import Optional
import random


class RedisSimulator:
    """
    Giả lập Amazon ElastiCache for Redis.
    
    Redis được dùng trong Phase 1 (Rule Engine) để lưu:
    - Whitelist: Danh sách tài khoản đã xác minh an toàn
    - Blacklist: Danh sách tài khoản bị chặn
    - Risk Scores: Điểm rủi ro real-time của mỗi tài khoản
    - Transaction velocity: Đếm số GD trong time window
    
    Trong Phase 3, Redis được cập nhật dựa trên kết quả điều tra:
    - ALLOW → cập nhật whitelist
    - BLOCK → cập nhật blacklist + risk score
    """
    
    def __init__(self):
        # --- Whitelist: Tài khoản đã verified, giao dịch được allow nhanh ---
        self._whitelist: set[str] = {
            "ACC_001", "ACC_002", "ACC_003", "ACC_004", "ACC_005",
            "ACC_010"
        }
        
        # --- Blacklist: Tài khoản bị chặn, giao dịch bị block ngay ---
        self._blacklist: set[str] = {
            "ACC_666", "ACC_999", "MULE_001", "MULE_002", "MULE_003"
        }
        
        # --- Risk Scores: Điểm rủi ro mỗi tài khoản (0.0 = safe, 1.0 = fraud) ---
        self._risk_scores: dict[str, float] = {
            "ACC_001": 0.05,  # Rất an toàn
            "ACC_002": 0.10,
            "ACC_003": 0.15,
            "ACC_004": 0.08,
            "ACC_005": 0.12,
            "ACC_006": 0.45,  # Hơi nghi ngờ
            "ACC_007": 0.65,  # Nghi ngờ cao
            "ACC_008": 0.30,
            "ACC_009": 0.55,
            "ACC_010": 0.02,
            "ACC_050": 0.78,  # Rủi ro cao
            "ACC_666": 0.95,  # Gần như chắc chắn fraud
            "ACC_999": 0.99,
            "MULE_001": 0.92,
            "MULE_002": 0.88,
            "MULE_003": 0.85,
        }
        
        # --- Velocity tracking: Đếm số GD trong 1h, 24h ---
        # Format: {account_id: [timestamp1, timestamp2, ...]}
        self._velocity: dict[str, list[str]] = {
            "ACC_007": [
                # 15 giao dịch trong 1 giờ qua → BẤT THƯỜNG!
                (datetime.now() - timedelta(minutes=i*4)).isoformat()
                for i in range(15)
            ],
            "ACC_050": [
                # 8 giao dịch nhỏ liên tiếp → có thể structuring
                (datetime.now() - timedelta(minutes=i*10)).isoformat()
                for i in range(8)
            ],
        }
    
    def is_whitelisted(self, account_id: str) -> bool:
        """Kiểm tra tài khoản có trong whitelist không"""
        return account_id in self._whitelist
    
    def is_blacklisted(self, account_id: str) -> bool:
        """Kiểm tra tài khoản có trong blacklist không"""
        return account_id in self._blacklist
    
    def get_risk_score(self, account_id: str) -> float:
        """Lấy risk score hiện tại (default 0.3 nếu chưa có)"""
        return self._risk_scores.get(account_id, 0.3)
    
    def get_velocity(self, account_id: str, hours: int = 1) -> int:
        """Đếm số giao dịch trong N giờ qua"""
        if account_id not in self._velocity:
            return random.randint(0, 3)  # Normal: 0-3 GD/giờ
        
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        return sum(1 for ts in self._velocity[account_id] if ts > cutoff)
    
    def update_whitelist(self, account_id: str, add: bool = True):
        """Cập nhật whitelist (Phase 3: ALLOW → thêm vào whitelist)"""
        if add:
            self._whitelist.add(account_id)
            self._blacklist.discard(account_id)
        else:
            self._whitelist.discard(account_id)
    
    def update_blacklist(self, account_id: str, add: bool = True):
        """Cập nhật blacklist (Phase 3: BLOCK → thêm vào blacklist)"""
        if add:
            self._blacklist.add(account_id)
            self._whitelist.discard(account_id)
        else:
            self._blacklist.discard(account_id)
    
    def increment_velocity(self, account_id: str):
        """Tăng velocity counter khi có giao dịch mới."""
        if account_id not in self._velocity:
            self._velocity[account_id] = []
        self._velocity[account_id].append(datetime.now().isoformat())
    
    def update_risk_score(self, account_id: str, score: float):
        """Cập nhật risk score (Phase 3)"""
        self._risk_scores[account_id] = max(0.0, min(1.0, score))


class DynamoDBSimulator:
    """
    Giả lập Amazon DynamoDB.
    
    DynamoDB lưu 2 loại dữ liệu chính:
    1. Transaction History: Lịch sử giao dịch của mỗi tài khoản
    2. Customer Profiles: Thông tin KYC, behavioral profile
    
    Executor Agent truy vấn DynamoDB để:
    - Lấy lịch sử giao dịch gần đây
    - So sánh hành vi hiện tại vs. baseline
    - Kiểm tra KYC status và account age
    """
    
    def __init__(self):
        # --- Customer Profiles ---
        # Mỗi profile chứa thông tin KYC + behavioral baseline
        self._profiles: dict[str, dict] = {
            "ACC_001": {
                "customer_id": "ACC_001",
                "name": "Nguyễn Văn An",
                "account_type": "savings",
                "kyc_status": "verified",        # KYC đã xác minh
                "account_age_days": 1825,         # 5 năm → tài khoản lâu năm
                "avg_monthly_transactions": 12,   # Trung bình 12 GD/tháng
                "avg_transaction_amount": 500.0,  # Trung bình $500/GD
                "typical_channels": ["mobile", "web"],
                "typical_locations": ["Ho Chi Minh City", "Hanoi"],
                "risk_category": "low",
            },
            "ACC_007": {
                "customer_id": "ACC_007",
                "name": "Trần Thị B",
                "account_type": "checking",
                "kyc_status": "verified",
                "account_age_days": 45,           # Tài khoản MỚI → nghi ngờ
                "avg_monthly_transactions": 3,    # Ít GD bình thường
                "avg_transaction_amount": 200.0,
                "typical_channels": ["mobile"],
                "typical_locations": ["Da Nang"],
                "risk_category": "medium",
            },
            "ACC_050": {
                "customer_id": "ACC_050",
                "name": "Unknown Entity",
                "account_type": "business",
                "kyc_status": "pending",          # KYC chưa xong → RED FLAG
                "account_age_days": 15,           # Rất mới
                "avg_monthly_transactions": 0,    # Chưa có lịch sử
                "avg_transaction_amount": 0.0,
                "typical_channels": ["web"],
                "typical_locations": ["Unknown"],
                "risk_category": "high",
            },
            "MULE_001": {
                "customer_id": "MULE_001",
                "name": "Phạm Văn X",
                "account_type": "checking",
                "kyc_status": "verified",
                "account_age_days": 90,
                "avg_monthly_transactions": 50,   # GD nhiều bất thường
                "avg_transaction_amount": 1500.0,
                "typical_channels": ["mobile", "web", "atm"],
                "typical_locations": ["Ho Chi Minh City", "Hanoi", "Singapore"],
                "risk_category": "high",
            },
            "ACC_002": {
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
            "ACC_666": {
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
            "MULE_002": {
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
            "MULE_003": {
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
        }
        
        # --- Transaction History ---
        # Lịch sử GD gần đây (dùng cho behavioral analysis)
        self._transactions: dict[str, list[dict]] = {
            "ACC_007": [
                # 15 GD nhỏ liên tiếp trong 2 giờ → STRUCTURING pattern!
                {
                    "transaction_id": f"TXN_007_{i:03d}",
                    "timestamp": (datetime.now() - timedelta(minutes=i*8)).isoformat(),
                    "amount": round(random.uniform(900, 999), 2),  # Ngay dưới $1000 threshold
                    "receiver_id": f"MULE_{(i % 3) + 1:03d}",     # Gửi cho 3 money mules
                    "type": "transfer",
                    "channel": "mobile",
                }
                for i in range(15)
            ],
            "ACC_050": [
                # GD lớn đột ngột từ tài khoản mới
                {
                    "transaction_id": "TXN_050_001",
                    "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(),
                    "amount": 25000.00,
                    "receiver_id": "ACC_666",    # Gửi đến tài khoản blacklisted
                    "type": "transfer",
                    "channel": "web",
                },
                {
                    "transaction_id": "TXN_050_002",
                    "timestamp": (datetime.now() - timedelta(hours=1)).isoformat(),
                    "amount": 15000.00,
                    "receiver_id": "MULE_002",
                    "type": "transfer",
                    "channel": "web",
                },
            ],
            "ACC_001": [
                # GD bình thường
                {
                    "transaction_id": f"TXN_001_{i:03d}",
                    "timestamp": (datetime.now() - timedelta(days=i*3)).isoformat(),
                    "amount": round(random.uniform(100, 800), 2),
                    "receiver_id": "ACC_002",
                    "type": "transfer",
                    "channel": random.choice(["mobile", "web"]),
                }
                for i in range(5)
            ],
        }
    
    def get_customer_profile(self, account_id: str) -> dict:
        """
        Lấy customer profile (KYC + behavioral baseline).
        
        Executor Agent gọi hàm này khi làm task BEHAVIORAL_ANALYSIS.
        """
        return self._profiles.get(account_id, {
            "customer_id": account_id,
            "name": "Unknown",
            "kyc_status": "not_found",
            "account_age_days": 0,
            "risk_category": "unknown",
        })
    
    def get_transaction_history(self, account_id: str, limit: int = 20) -> list[dict]:
        """
        Lấy lịch sử giao dịch gần đây.
        
        Executor Agent gọi hàm này khi làm task:
        - VELOCITY_CHECK: Đếm tần suất GD
        - AMOUNT_PATTERN: Phân tích mẫu số tiền
        - BEHAVIORAL_ANALYSIS: So sánh với baseline
        """
        return self._transactions.get(account_id, [])[:limit]
    
    def get_related_accounts(self, account_id: str) -> list[str]:
        """
        Tìm tài khoản liên quan (dựa trên lịch sử GD).
        Dùng cho graph analysis khi Neptune không available.
        """
        txns = self._transactions.get(account_id, [])
        related = set()
        for txn in txns:
            if txn.get("receiver_id"):
                related.add(txn["receiver_id"])
        return list(related)


class NeptuneSimulator:
    """
    Giả lập Amazon Neptune (Graph Database).
    
    Neptune lưu RELATIONSHIP GRAPH giữa các entities:
    - Account ↔ Device (tài khoản dùng thiết bị nào)
    - Account ↔ IP (tài khoản đăng nhập từ IP nào)
    - Account ↔ Merchant (tài khoản giao dịch với merchant nào)
    - Account ↔ Account (chuyển tiền cho ai)
    
    Graph analysis giúp phát hiện:
    - Star topology: 1 account kết nối nhiều mule accounts
    - Dense subgraph: Nhóm accounts chuyển tiền vòng tròn
    - Shared device/IP: Nhiều accounts dùng chung 1 thiết bị
    
    Vision Agent sẽ phân tích cấu trúc graph này.
    """
    
    def __init__(self):
        # --- Nodes: Tất cả entities trong graph ---
        self._nodes: dict[str, dict] = {
            # Accounts
            "ACC_001": {"type": "account", "label": "Nguyễn Văn An", "risk": "low"},
            "ACC_007": {"type": "account", "label": "Trần Thị B", "risk": "medium"},
            "ACC_050": {"type": "account", "label": "Unknown Entity", "risk": "high"},
            "ACC_666": {"type": "account", "label": "Blocked Account", "risk": "critical"},
            "MULE_001": {"type": "account", "label": "Phạm Văn X (Mule)", "risk": "high"},
            "MULE_002": {"type": "account", "label": "Lê Thị Y (Mule)", "risk": "high"},
            "MULE_003": {"type": "account", "label": "Ngô Văn Z (Mule)", "risk": "high"},
            
            # Devices
            "DEV_001": {"type": "device", "label": "iPhone 15 Pro"},
            "DEV_002": {"type": "device", "label": "Samsung Galaxy S24"},
            "DEV_SHARED": {"type": "device", "label": "Shared Android Device"},  # RED FLAG
            
            # IPs
            "IP_NORMAL_1": {"type": "ip", "label": "14.161.x.x (HCMC)"},
            "IP_NORMAL_2": {"type": "ip", "label": "113.190.x.x (Hanoi)"},
            "IP_VPN": {"type": "ip", "label": "185.220.x.x (Tor Exit)"},       # RED FLAG
            "IP_SHARED": {"type": "ip", "label": "103.45.x.x (Shared)"},       # RED FLAG
            
            # Merchants
            "MERCH_001": {"type": "merchant", "label": "VinMart"},
            "MERCH_SHELL": {"type": "merchant", "label": "Shell Company Ltd"},   # RED FLAG
        }
        
        # --- Edges: Mối quan hệ giữa entities ---
        # Format: (source, target, relationship_type, metadata)
        self._edges: list[tuple[str, str, str, dict]] = [
            # ACC_001 - Normal user
            ("ACC_001", "DEV_001", "uses_device", {"since": "2022-01"}),
            ("ACC_001", "IP_NORMAL_1", "connects_from", {"frequency": "daily"}),
            ("ACC_001", "ACC_002", "transfers_to", {"total_amount": 5000, "count": 10}),
            ("ACC_001", "MERCH_001", "pays_to", {"total_amount": 2000, "count": 20}),
            
            # ACC_007 - Suspicious (structuring pattern)
            ("ACC_007", "DEV_002", "uses_device", {"since": "2025-11"}),
            ("ACC_007", "IP_NORMAL_2", "connects_from", {"frequency": "daily"}),
            # Chuyển tiền cho 3 MULE accounts → STAR TOPOLOGY (nghi ngờ!)
            ("ACC_007", "MULE_001", "transfers_to", {"total_amount": 9500, "count": 5}),
            ("ACC_007", "MULE_002", "transfers_to", {"total_amount": 8700, "count": 5}),
            ("ACC_007", "MULE_003", "transfers_to", {"total_amount": 9200, "count": 5}),
            
            # MULE network - Dùng chung device + IP → DENSE SUBGRAPH
            ("MULE_001", "DEV_SHARED", "uses_device", {"since": "2025-12"}),
            ("MULE_002", "DEV_SHARED", "uses_device", {"since": "2025-12"}),
            ("MULE_003", "DEV_SHARED", "uses_device", {"since": "2025-12"}),
            ("MULE_001", "IP_SHARED", "connects_from", {"frequency": "daily"}),
            ("MULE_002", "IP_SHARED", "connects_from", {"frequency": "daily"}),
            ("MULE_003", "IP_SHARED", "connects_from", {"frequency": "daily"}),
            # Mules chuyển tiền về ACC_666 → CIRCULAR FLOW
            ("MULE_001", "ACC_666", "transfers_to", {"total_amount": 9000, "count": 3}),
            ("MULE_002", "ACC_666", "transfers_to", {"total_amount": 8500, "count": 3}),
            ("MULE_003", "ACC_666", "transfers_to", {"total_amount": 9000, "count": 3}),
            
            # ACC_050 - New suspicious account
            ("ACC_050", "IP_VPN", "connects_from", {"frequency": "always"}),  # Luôn dùng VPN
            ("ACC_050", "ACC_666", "transfers_to", {"total_amount": 25000, "count": 1}),
            ("ACC_050", "MULE_002", "transfers_to", {"total_amount": 15000, "count": 1}),
            ("ACC_050", "MERCH_SHELL", "pays_to", {"total_amount": 10000, "count": 2}),
        ]
    
    def get_neighbors(self, node_id: str, depth: int = 1) -> dict:
        """
        Tìm tất cả nodes kết nối với 1 node (BFS theo depth).
        
        Executor Agent gọi hàm này khi làm GRAPH_QUERY.
        Trả về: danh sách neighbors + edges + metadata.
        
        Args:
            node_id: ID của node cần tìm neighbors
            depth: Số tầng BFS (1 = chỉ neighbors trực tiếp)
        """
        visited = set()
        result = {"center": node_id, "nodes": {}, "edges": []}
        queue = [(node_id, 0)]
        
        while queue:
            current, current_depth = queue.pop(0)
            if current in visited or current_depth > depth:
                continue
            visited.add(current)
            
            if current in self._nodes:
                result["nodes"][current] = self._nodes[current]
            
            for src, dst, rel, meta in self._edges:
                if src == current and dst not in visited:
                    result["edges"].append({
                        "source": src, "target": dst,
                        "relationship": rel, **meta
                    })
                    if current_depth < depth:
                        queue.append((dst, current_depth + 1))
                elif dst == current and src not in visited:
                    result["edges"].append({
                        "source": src, "target": dst,
                        "relationship": rel, **meta
                    })
                    if current_depth < depth:
                        queue.append((src, current_depth + 1))
        
        return result
    
    def find_shared_entities(self, node_id: str, entity_type: str = "device") -> list[dict]:
        """
        Tìm entities dùng chung (shared device, shared IP).
        
        Đây là signaling RED FLAG khi nhiều accounts dùng chung
        1 device hoặc 1 IP → có thể là cùng 1 người điều khiển.
        
        Args:
            node_id: Account ID cần kiểm tra
            entity_type: "device" hoặc "ip"
        """
        # Bước 1: Tìm devices/IPs mà node_id sử dụng
        rel_type = "uses_device" if entity_type == "device" else "connects_from"
        entities = []
        for src, dst, rel, meta in self._edges:
            if src == node_id and rel == rel_type:
                entities.append(dst)
        
        # Bước 2: Tìm accounts KHÁC cũng dùng cùng device/IP
        shared = []
        for entity in entities:
            other_accounts = []
            for src, dst, rel, meta in self._edges:
                if dst == entity and rel == rel_type and src != node_id:
                    other_accounts.append(src)
            if other_accounts:
                shared.append({
                    "entity_id": entity,
                    "entity_info": self._nodes.get(entity, {}),
                    "shared_with": other_accounts,
                    "is_suspicious": len(other_accounts) >= 2,  # 3+ accounts cùng device
                })
        
        return shared
    
    def detect_circular_flows(self, node_id: str) -> list[dict]:
        """
        Phát hiện fund flow vòng tròn (circular/layering).
        
        Pattern: A → B → C → A (tiền quay vòng để rửa)
        Vision Agent sẽ phân tích kết quả này.
        """
        # Tìm tất cả paths bắt đầu từ node_id
        transfer_edges = [(s, d, m) for s, d, r, m in self._edges if r == "transfers_to"]
        
        paths = []
        for src, dst, meta in transfer_edges:
            if src == node_id:
                # Kiểm tra dst có chuyển ngược lại cho ai liên quan không
                for src2, dst2, meta2 in transfer_edges:
                    if src2 == dst:
                        paths.append({
                            "path": f"{node_id} → {dst} → {dst2}",
                            "amounts": [meta.get("total_amount", 0), meta2.get("total_amount", 0)],
                            "is_circular": dst2 == node_id,
                        })
        
        return paths


class OpenSearchSimulator:
    """
    Giả lập Amazon OpenSearch (RAG Knowledge Base).
    
    OpenSearch lưu trữ:
    1. Known Fraud Patterns: Các pattern gian lận đã biết
    2. Past Investigation Cases: Kết quả điều tra trước đó
    3. Regulatory Rules: Quy định compliance
    
    Executor Agent gọi khi làm task KNOWLEDGE_RETRIEVAL.
    Dùng semantic search để tìm patterns tương tự.
    
    Đây là phần ADAPTIVE INTELLIGENCE:
    - Khi Detective Agent kết luận BLOCK → pattern mới được index
    - Lần sau gặp pattern tương tự → phát hiện nhanh hơn
    """
    
    def __init__(self):
        self._documents: list[dict] = [
            {
                "id": "pattern_001",
                "type": "fraud_pattern",
                "title": "Structuring / Smurfing Pattern",
                "description": (
                    "Nhiều giao dịch nhỏ ngay dưới reporting threshold ($10,000 hoặc $1,000) "
                    "được thực hiện trong thời gian ngắn để tránh trigger cảnh báo tự động. "
                    "Thường gửi đến nhiều tài khoản khác nhau (money mules)."
                ),
                "indicators": [
                    "Số tiền ngay dưới threshold (ví dụ: $999, $9,999)",
                    "Nhiều GD trong thời gian ngắn (>10 GD/giờ)",
                    "Gửi đến nhiều tài khoản khác nhau",
                    "Tổng số tiền lớn nhưng mỗi GD nhỏ",
                ],
                "risk_level": "high",
                "confidence_boost": 0.3,  # Tăng confidence thêm 30% khi match
            },
            {
                "id": "pattern_002",
                "type": "fraud_pattern",
                "title": "Money Mule Network",
                "description": (
                    "Mạng lưới tài khoản trung gian (money mules) được sử dụng để "
                    "chuyển tiền phi pháp qua nhiều lớp. Các mule accounts thường "
                    "dùng chung thiết bị hoặc IP, được tạo gần đây, và nhận tiền "
                    "từ nhiều nguồn rồi chuyển đến một tài khoản tập trung."
                ),
                "indicators": [
                    "Nhiều accounts dùng chung device/IP",
                    "Tài khoản mới (<90 ngày)",
                    "Nhận tiền từ nhiều nguồn → chuyển đến 1 đích",
                    "Star topology trong graph",
                ],
                "risk_level": "critical",
                "confidence_boost": 0.35,
            },
            {
                "id": "pattern_003",
                "type": "fraud_pattern",
                "title": "Account Takeover (ATO)",
                "description": (
                    "Tài khoản bị chiếm đoạt: thay đổi đột ngột về device, IP, "
                    "location, hoặc pattern giao dịch. Kẻ gian thường thực hiện "
                    "GD lớn ngay sau khi take over."
                ),
                "indicators": [
                    "Device mới chưa từng thấy",
                    "IP/Location khác biệt hoàn toàn",
                    "GD lớn đột ngột (>5x average)",
                    "Thay đổi password gần đây",
                ],
                "risk_level": "high",
                "confidence_boost": 0.25,
            },
            {
                "id": "pattern_004",
                "type": "fraud_pattern",
                "title": "Authorized Push Payment (APP) Fraud",
                "description": (
                    "Nạn nhân bị social engineering lừa tự nguyện chuyển tiền. "
                    "Thường có đặc điểm: GD lớn bất thường, chuyển đến tài khoản "
                    "lạ, nạn nhân gọi ngân hàng xác nhận (vì bị ép)."
                ),
                "indicators": [
                    "GD lớn đến tài khoản mới (first-time recipient)",
                    "Nạn nhân thay đổi hành vi đột ngột",
                    "Urgency signals (nhiều lần thử nếu bị chặn)",
                    "Recipient là tài khoản mới/không rõ",
                ],
                "risk_level": "high",
                "confidence_boost": 0.2,
            },
            {
                "id": "case_001",
                "type": "past_investigation",
                "title": "Case: ACC_666 Money Laundering Ring",
                "description": (
                    "ACC_666 được xác nhận là trung tâm của mạng lưới rửa tiền. "
                    "Nhận tiền từ 15+ mule accounts, tổng $500K+ trong 3 tháng. "
                    "Đã bị BLOCK và chuyển cho cơ quan chức năng."
                ),
                "related_accounts": ["MULE_001", "MULE_002", "MULE_003", "ACC_050"],
                "decision": "BLOCK",
                "date": "2025-09-15",
            },
            {
                "id": "rule_001",
                "type": "regulatory_rule",
                "title": "BSA/AML Reporting Threshold",
                "description": (
                    "Bank Secrecy Act yêu cầu báo cáo CTR (Currency Transaction Report) "
                    "cho mọi giao dịch > $10,000. Structuring để tránh threshold này "
                    "là vi phạm pháp luật liên bang."
                ),
                "threshold": 10000,
            },
        ]
    
    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Semantic search trong knowledge base.
        
        Trong demo, dùng keyword matching đơn giản.
        Production sẽ dùng vector embedding + OpenSearch kNN.
        
        Args:
            query: Câu truy vấn (ví dụ: "structuring multiple small transfers")
            top_k: Số kết quả trả về tối đa
        """
        query_lower = query.lower()
        scored = []
        
        for doc in self._documents:
            # Tính relevance score đơn giản (keyword matching)
            score = 0
            text = f"{doc.get('title', '')} {doc.get('description', '')}".lower()
            
            # Chia query thành từ, đếm match
            for word in query_lower.split():
                if len(word) > 3 and word in text:
                    score += 1
            
            # Bonus cho indicator matches
            for indicator in doc.get("indicators", []):
                for word in query_lower.split():
                    if len(word) > 3 and word in indicator.lower():
                        score += 0.5
            
            if score > 0:
                scored.append((score, doc))
        
        # Sắp xếp theo score giảm dần
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:top_k]]
    
    def index_new_pattern(self, pattern: dict):
        """
        Thêm fraud pattern mới vào knowledge base.
        
        Gọi sau khi Detective Agent kết luận BLOCK:
        Pattern mới được lưu để future investigations
        có thể reference → ADAPTIVE INTELLIGENCE.
        """
        pattern["id"] = f"pattern_{len(self._documents) + 1:03d}"
        self._documents.append(pattern)
        return pattern["id"]


# =====================================================================
# RedisService - Unified Redis Interface (Real ↔ Simulator)
# =====================================================================
# Abstraction layer cho Phase 1 screening:
#   - Khi có Redis Cloud credentials → dùng real Redis
#   - Khi không có (DEMO_MODE=true) → fallback về RedisSimulator
# =====================================================================

class RedisService:
    """
    Unified Redis interface cho fraud detection system.
    
    Tự động chọn backend:
    - Real Redis Cloud (khi có credentials)
    - RedisSimulator in-memory (fallback)
    """
    
    def __init__(self):
        self._real_redis = None
        self._simulator = None
        self.is_connected = False
        self._mode = "simulator"  # "real" or "simulator"
        
        # Thử kết nối Real Redis nếu có credentials
        from config import settings
        if (settings.redis_host 
            and settings.redis_host != "localhost"
            and settings.redis_password):
            try:
                import redis
                client = redis.Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    decode_responses=True,
                    username=settings.redis_username,
                    password=settings.redis_password,
                )
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
        self._simulator = RedisSimulator()
        self._mode = "simulator"
        self.is_connected = False
    
    # =================================================================
    # WHITELIST
    # =================================================================
    
    def is_whitelisted(self, account_id: str) -> bool:
        if self._mode == "real":
            wl_data = self._real_redis.hgetall(f"whitelist:{account_id}")
            return len(wl_data) > 0
        else:
            return self._simulator.is_whitelisted(account_id)
    
    # =================================================================
    # BLACKLIST
    # =================================================================
    
    def is_blacklisted(self, account_id: str) -> bool:
        if self._mode == "real":
            return self._real_redis.sismember("blacklist", account_id)
        else:
            return self._simulator.is_blacklisted(account_id)
    
    # =================================================================
    # RISK SCORE
    # =================================================================
    
    def get_risk_score(self, account_id: str) -> float:
        if self._mode == "real":
            score = self._real_redis.hget(f"risk_score:{account_id}", "score")
            if score is not None:
                return float(score)
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
        if self._mode == "real":
            if add:
                self._real_redis.hset(f"whitelist:{account_id}", 
                                       mapping={"_status": "whitelisted"})
                self._real_redis.srem("blacklist", account_id)
            else:
                self._real_redis.delete(f"whitelist:{account_id}")
        else:
            self._simulator.update_whitelist(account_id, add)
    
    # =================================================================
    # BLACKLIST UPDATE (Phase 3)
    # =================================================================
    
    def update_blacklist(self, account_id: str, add: bool = True):
        if self._mode == "real":
            if add:
                self._real_redis.sadd("blacklist", account_id)
                self._real_redis.delete(f"whitelist:{account_id}")
            else:
                self._real_redis.srem("blacklist", account_id)
        else:
            self._simulator.update_blacklist(account_id, add)
    
    # =================================================================
    # RISK SCORE UPDATE (Phase 3)
    # =================================================================
    
    def update_risk_score(self, account_id: str, score: float):
        score = max(0.0, min(1.0, score))
        if self._mode == "real":
            self._real_redis.hset(f"risk_score:{account_id}", 
                                   mapping={"score": str(score),
                                            "updated_at": datetime.now().isoformat()})
        else:
            self._simulator.update_risk_score(account_id, score)
    
    # =================================================================
    # TRUST SCORE (Real Redis only)
    # =================================================================
    
    def get_trust_score(self, sender_id: str, receiver_id: str) -> Optional[int]:
        if self._mode == "real":
            score = self._real_redis.hget(f"whitelist:{sender_id}", receiver_id)
            return int(score) if score is not None else None
        else:
            return None
    
    # =================================================================
    # AMOUNT THRESHOLDS (Real Redis only)
    # =================================================================
    
    def get_amount_thresholds(self) -> dict:
        if self._mode == "real":
            data = self._real_redis.hgetall("rules:amount_threshold")
            return {
                "instant_allow_max": float(data.get("instant_allow_max", 1000000)),
                "escalate_threshold": float(data.get("escalate_threshold", 20000000)),
                "instant_block_threshold": float(data.get("instant_block_threshold", 2000000000)),
                "currency": data.get("currency", "VND"),
            }
        else:
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
    # VELOCITY INCREMENT
    # =================================================================
    
    def increment_velocity(self, account_id: str):
        if self._mode == "real":
            hourly_key = f"velocity:{account_id}:hourly"
            hourly_count = self._real_redis.incr(hourly_key)
            if hourly_count == 1:
                self._real_redis.expire(hourly_key, 3600)
            daily_key = f"velocity:{account_id}:daily"
            daily_count = self._real_redis.incr(daily_key)
            if daily_count == 1:
                self._real_redis.expire(daily_key, 86400)
        else:
            self._simulator.increment_velocity(account_id)
    
    # =================================================================
    # AUDIT TRAIL
    # =================================================================
    
    def store_transaction_result(self, txn_id: str, result: dict):
        if self._mode == "real":
            self._real_redis.hset(f"txn:result:{txn_id}", mapping={
                k: str(v) for k, v in result.items()
            })
    
    # =================================================================
    # SEED DATA
    # =================================================================
    
    def seed_data(self):
        if self._mode != "real":
            print("   ℹ️  Redis seed skipped (simulator mode)")
            return
        
        r = self._real_redis
        print("   📊 Seeding Redis Cloud data...")
        
        # ─── 0. Xóa dữ liệu cũ (tránh blacklist/velocity tồn đọng từ lần chạy trước) ───
        #r.flushdb()
        #print("      🧹 Đã xóa dữ liệu Redis cũ")
        
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
        
        # ─── 5. Velocity Counters ───
        hourly_key_007 = "velocity:ACC_007:hourly"
        for _ in range(15):
            r.incr(hourly_key_007)
        r.expire(hourly_key_007, 3600)
        daily_key_007 = "velocity:ACC_007:daily"
        for _ in range(15):
            r.incr(daily_key_007)
        r.expire(daily_key_007, 86400)
        
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
# SINGLETON INSTANCES - Dùng chung trong toàn bộ app
# =====================================================================

redis_sim = RedisSimulator()
dynamodb_sim = DynamoDBSimulator()
neptune_sim = NeptuneSimulator()
opensearch_sim = OpenSearchSimulator()
redis_service = RedisService()
