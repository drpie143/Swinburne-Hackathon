# ====================================================================
# GRAPH_DB.PY - Neo4j AuraDB Integration (Cloud-Hosted, Free Forever)
# ====================================================================
#
# Thay thế Amazon Neptune (Gremlin) bằng Neo4j AuraDB (Cypher).
#
# NEO4J AURADB FREE TIER:
#   - Cloud-hosted: KHÔNG cần cài local, chỉ cần URI + password
#   - Free forever: 200K nodes, 400K relationships
#   - Cypher query language: đơn giản, mạnh mẽ hơn Gremlin
#   - Graph visualization đẹp: Neo4j Browser/Bloom → gây ấn tượng giám khảo
#   - Đăng ký: https://neo4j.com/cloud/aura-free/
#
# FALLBACK:
#   Nếu chưa có Neo4j credentials → dùng NeptuneSimulator (in-memory)
#   Khi có credentials → tự động dùng Neo4j AuraDB thật
#
# SCHEMA:
#   (:Account {id, name, risk, type, kyc_status, account_age_days})
#   (:Device {id, label})
#   (:IP {id, label, is_vpn})
#   (:Merchant {id, label, is_shell})
#
#   (:Account)-[:TRANSFERS_TO {total_amount, count}]->(:Account)
#   (:Account)-[:USES_DEVICE {since}]->(:Device)
#   (:Account)-[:CONNECTS_FROM {frequency}]->(:IP)
#   (:Account)-[:PAYS_TO {total_amount, count}]->(:Merchant)
# ====================================================================

from __future__ import annotations
import re
from typing import Optional
from config import settings


class Neo4jClient:
    """
    Client cho Neo4j AuraDB (cloud-hosted graph database).
    
    Cloud-hosted → không cần cài database server local.
    Chỉ cần 3 thứ từ AuraDB console:
    1. NEO4J_URI (neo4j+s://xxxxx.databases.neo4j.io)
    2. NEO4J_USER (thường là "neo4j")
    3. NEO4J_PASSWORD (tạo khi setup instance)
    
    Khi không có credentials: fallback sang NeptuneSimulator.
    """
    
    def __init__(self):
        """
        Khởi tạo Neo4j driver.
        
        neo4j package chỉ là DRIVER (client library),
        KHÔNG phải database server. Database chạy trên cloud AuraDB.
        """
        self.driver = None
        self._use_simulator = True
        
        if settings.neo4j_uri and settings.neo4j_password:
            try:
                from neo4j import GraphDatabase
                self.driver = GraphDatabase.driver(
                    settings.neo4j_uri,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                )
                # Test connection
                self.driver.verify_connectivity()
                self._use_simulator = False
                print("✅ Neo4j AuraDB connected (cloud-hosted)")
            except Exception as e:
                print(f"⚠️  Neo4j connection failed: {e}")
                print("   → Fallback: dùng NeptuneSimulator (in-memory)")
                self.driver = None
                self._use_simulator = True
        else:
            print("ℹ️  Neo4j credentials chưa cấu hình → dùng NeptuneSimulator")
    
    @property
    def is_connected(self) -> bool:
        """Kiểm tra đã kết nối Neo4j AuraDB chưa."""
        return self.driver is not None and not self._use_simulator
    
    def close(self):
        """Đóng connection khi shutdown."""
        if self.driver:
            self.driver.close()
    
    # =================================================================
    # SEED DATA - Tạo sample data ban đầu cho demo
    # =================================================================
    
    def seed_demo_data(self):
        """
        Tạo graph data mẫu trong Neo4j AuraDB.
        
        Gọi 1 lần khi bắt đầu demo để populate graph.
        Data giống hệt NeptuneSimulator nhưng trên Neo4j thật
        → visualization đẹp trên Neo4j Browser/Bloom.
        
        Idempotent: chạy nhiều lần không bị duplicate (dùng MERGE).
        """
        if not self.is_connected:
            print("⚠️  Bỏ qua seed_demo_data (không có Neo4j connection)")
            return
        
        print("🌱 Seeding demo data vào Neo4j AuraDB...")
        
        with self.driver.session() as session:
            # Clear existing data (cho demo, chạy lại sạch)
            session.run("MATCH (n) DETACH DELETE n")
            
            # ─── Tạo Account nodes ───
            session.run("""
                CREATE (:Account {id: 'ACC_001', name: 'Nguyễn Văn An', risk: 'low', type: 'savings', kyc_status: 'verified', account_age_days: 1825})
                CREATE (:Account {id: 'ACC_002', name: 'Trần Minh Tuấn', risk: 'low', type: 'checking'})
                CREATE (:Account {id: 'ACC_007', name: 'Trần Thị B', risk: 'medium', type: 'checking', kyc_status: 'verified', account_age_days: 45})
                CREATE (:Account {id: 'ACC_008', name: 'Nguyễn Thị D', risk: 'low', type: 'savings'})
                CREATE (:Account {id: 'ACC_009', name: 'Lê Văn C', risk: 'medium', type: 'checking'})
                CREATE (:Account {id: 'ACC_050', name: 'Unknown Entity', risk: 'high', type: 'business', kyc_status: 'pending', account_age_days: 15})
                CREATE (:Account {id: 'ACC_666', name: 'Blocked Account', risk: 'critical'})
                CREATE (:Account {id: 'MULE_001', name: 'Phạm Văn X (Mule)', risk: 'high'})
                CREATE (:Account {id: 'MULE_002', name: 'Lê Thị Y (Mule)', risk: 'high'})
                CREATE (:Account {id: 'MULE_003', name: 'Ngô Văn Z (Mule)', risk: 'high'})
            """)
            
            # ─── Tạo Device nodes ───
            session.run("""
                CREATE (:Device {id: 'DEV_001', label: 'iPhone 15 Pro'})
                CREATE (:Device {id: 'DEV_002', label: 'Samsung Galaxy S24'})
                CREATE (:Device {id: 'DEV_SHARED', label: 'Shared Android Device'})
            """)
            
            # ─── Tạo IP nodes ───
            session.run("""
                CREATE (:IP {id: 'IP_NORMAL_1', label: '14.161.x.x (HCMC)', is_vpn: false})
                CREATE (:IP {id: 'IP_NORMAL_2', label: '113.190.x.x (Hanoi)', is_vpn: false})
                CREATE (:IP {id: 'IP_VPN', label: '185.220.x.x (Tor Exit)', is_vpn: true})
                CREATE (:IP {id: 'IP_SHARED', label: '103.45.x.x (Shared)', is_vpn: false})
            """)
            
            # ─── Tạo Merchant nodes ───
            session.run("""
                CREATE (:Merchant {id: 'MERCH_001', label: 'VinMart', is_shell: false})
                CREATE (:Merchant {id: 'MERCH_SHELL', label: 'Shell Company Ltd', is_shell: true})
            """)
            
            # ─── Tạo relationships ───
            # ACC_001 - Normal user
            session.run("""
                MATCH (a:Account {id: 'ACC_001'}), (d:Device {id: 'DEV_001'})
                CREATE (a)-[:USES_DEVICE {since: '2022-01'}]->(d)
            """)
            session.run("""
                MATCH (a:Account {id: 'ACC_001'}), (ip:IP {id: 'IP_NORMAL_1'})
                CREATE (a)-[:CONNECTS_FROM {frequency: 'daily'}]->(ip)
            """)
            session.run("""
                MATCH (a:Account {id: 'ACC_001'}), (b:Account {id: 'ACC_002'})
                CREATE (a)-[:TRANSFERS_TO {total_amount: 5000, count: 10}]->(b)
            """)
            session.run("""
                MATCH (a:Account {id: 'ACC_001'}), (m:Merchant {id: 'MERCH_001'})
                CREATE (a)-[:PAYS_TO {total_amount: 2000, count: 20}]->(m)
            """)
            
            # ACC_007 - Suspicious (structuring) → STAR TOPOLOGY to MULES
            session.run("""
                MATCH (a:Account {id: 'ACC_007'}), (d:Device {id: 'DEV_002'})
                CREATE (a)-[:USES_DEVICE {since: '2025-11'}]->(d)
            """)
            session.run("""
                MATCH (a:Account {id: 'ACC_007'}), (ip:IP {id: 'IP_NORMAL_2'})
                CREATE (a)-[:CONNECTS_FROM {frequency: 'daily'}]->(ip)
            """)
            session.run("""
                MATCH (a:Account {id: 'ACC_007'}), (m1:Account {id: 'MULE_001'}),
                      (m2:Account {id: 'MULE_002'}), (m3:Account {id: 'MULE_003'})
                CREATE (a)-[:TRANSFERS_TO {total_amount: 9500, count: 5}]->(m1)
                CREATE (a)-[:TRANSFERS_TO {total_amount: 8700, count: 5}]->(m2)
                CREATE (a)-[:TRANSFERS_TO {total_amount: 9200, count: 5}]->(m3)
            """)
            
            # MULE network → Shared device + IP (DENSE SUBGRAPH)
            session.run("""
                MATCH (m1:Account {id: 'MULE_001'}), (m2:Account {id: 'MULE_002'}),
                      (m3:Account {id: 'MULE_003'}), (d:Device {id: 'DEV_SHARED'}),
                      (ip:IP {id: 'IP_SHARED'})
                CREATE (m1)-[:USES_DEVICE {since: '2025-12'}]->(d)
                CREATE (m2)-[:USES_DEVICE {since: '2025-12'}]->(d)
                CREATE (m3)-[:USES_DEVICE {since: '2025-12'}]->(d)
                CREATE (m1)-[:CONNECTS_FROM {frequency: 'daily'}]->(ip)
                CREATE (m2)-[:CONNECTS_FROM {frequency: 'daily'}]->(ip)
                CREATE (m3)-[:CONNECTS_FROM {frequency: 'daily'}]->(ip)
            """)
            
            # MULES → ACC_666 (CIRCULAR FLOW)
            session.run("""
                MATCH (m1:Account {id: 'MULE_001'}), (m2:Account {id: 'MULE_002'}),
                      (m3:Account {id: 'MULE_003'}), (acc666:Account {id: 'ACC_666'})
                CREATE (m1)-[:TRANSFERS_TO {total_amount: 9000, count: 3}]->(acc666)
                CREATE (m2)-[:TRANSFERS_TO {total_amount: 8500, count: 3}]->(acc666)
                CREATE (m3)-[:TRANSFERS_TO {total_amount: 9000, count: 3}]->(acc666)
            """)
            
            # ACC_050 - New suspicious + VPN
            session.run("""
                MATCH (a:Account {id: 'ACC_050'}), (ip:IP {id: 'IP_VPN'})
                CREATE (a)-[:CONNECTS_FROM {frequency: 'always'}]->(ip)
            """)
            session.run("""
                MATCH (a:Account {id: 'ACC_050'}), (acc666:Account {id: 'ACC_666'}),
                      (m2:Account {id: 'MULE_002'}), (ms:Merchant {id: 'MERCH_SHELL'})
                CREATE (a)-[:TRANSFERS_TO {total_amount: 25000, count: 1}]->(acc666)
                CREATE (a)-[:TRANSFERS_TO {total_amount: 15000, count: 1}]->(m2)
                CREATE (a)-[:PAYS_TO {total_amount: 10000, count: 2}]->(ms)
            """)
        
        print("✅ Demo data seeded vào Neo4j AuraDB!")
    
    # =================================================================
    # QUERY METHODS - Executor Agent gọi các hàm này
    # =================================================================
    
    def get_neighbors(self, node_id: str, depth: int = 2) -> dict:
        """
        Tìm tất cả nodes kết nối với 1 account (BFS).
        
        Cypher query:
          MATCH path = (a {id: $id})-[*1..depth]-(connected)
          RETURN nodes(path), relationships(path)
        
        Trả về format giống NeptuneSimulator để backward compatible.
        """
        if self._use_simulator:
            from simulators import neptune_sim
            return neptune_sim.get_neighbors(node_id, depth)
        
        with self.driver.session() as session:
            # FIX: depth dùng parameter an toàn thay vì string concat
            # Neo4j không hỗ trợ parameter cho variable-length path,
            # nhưng ta validate depth là int trong range an toàn
            safe_depth = max(1, min(int(depth), 4))
            query = f"""MATCH path = (start {{id: $id}})-[*1..{safe_depth}]-(connected)
                WITH nodes(path) AS ns, relationships(path) AS rs
                UNWIND ns AS n
                WITH COLLECT(DISTINCT n) AS nodes, rs
                UNWIND nodes AS node
                WITH COLLECT(DISTINCT {{
                    id: node.id,
                    type: CASE 
                        WHEN 'Account' IN labels(node) THEN 'account'
                        WHEN 'Device' IN labels(node) THEN 'device'
                        WHEN 'IP' IN labels(node) THEN 'ip'
                        WHEN 'Merchant' IN labels(node) THEN 'merchant'
                        ELSE 'unknown'
                    END,
                    label: COALESCE(node.name, node.label, node.id),
                    risk: node.risk
                }}) AS node_list, rs
                UNWIND rs AS r
                RETURN node_list,
                       COLLECT(DISTINCT {{
                           source: startNode(r).id,
                           target: endNode(r).id,
                           relationship: type(r),
                           total_amount: r.total_amount,
                           count: r.count,
                           since: r.since,
                           frequency: r.frequency
                       }}) AS edge_list
            """
            result = session.run(query, id=node_id)
            
            record = result.single()
            if not record:
                return {"center": node_id, "nodes": {}, "edges": []}
            
            nodes = {}
            for n in record["node_list"]:
                nodes[n["id"]] = {
                    "type": n["type"],
                    "label": n["label"],
                    "risk": n.get("risk", "unknown"),
                }
            
            edges = []
            for e in record["edge_list"]:
                edge = {
                    "source": e["source"],
                    "target": e["target"],
                    "relationship": e["relationship"].lower(),
                }
                if e.get("total_amount"):
                    edge["total_amount"] = e["total_amount"]
                if e.get("count"):
                    edge["count"] = e["count"]
                if e.get("since"):
                    edge["since"] = e["since"]
                if e.get("frequency"):
                    edge["frequency"] = e["frequency"]
                edges.append(edge)
            
            return {"center": node_id, "nodes": nodes, "edges": edges}
    
    def find_shared_entities(self, node_id: str, entity_type: str = "device") -> list[dict]:
        """
        Tìm devices/IPs dùng chung giữa nhiều accounts.
        
        Cypher (ví dụ cho device):
          MATCH (a:Account {id: $id})-[:USES_DEVICE]->(d:Device)<-[:USES_DEVICE]-(other:Account)
          RETURN d, COLLECT(other.id) AS shared_with
        
        RED FLAG: Nhiều accounts dùng chung 1 device → cùng 1 người.
        """
        if self._use_simulator:
            from simulators import neptune_sim
            return neptune_sim.find_shared_entities(node_id, entity_type)
        
        label = "Device" if entity_type == "device" else "IP"
        rel = "USES_DEVICE" if entity_type == "device" else "CONNECTS_FROM"
        
        with self.driver.session() as session:
            result = session.run(f"""
                MATCH (a:Account {{id: $id}})-[:{rel}]->(entity:{label})<-[:{rel}]-(other:Account)
                WHERE other.id <> $id
                WITH entity, COLLECT(DISTINCT other.id) AS shared_with
                RETURN entity.id AS entity_id,
                       entity.label AS entity_label,
                       shared_with,
                       SIZE(shared_with) >= 2 AS is_suspicious
            """, id=node_id)
            
            shared = []
            for record in result:
                shared.append({
                    "entity_id": record["entity_id"],
                    "entity_info": {"label": record["entity_label"], "type": entity_type},
                    "shared_with": record["shared_with"],
                    "is_suspicious": record["is_suspicious"],
                })
            return shared
    
    def detect_circular_flows(self, node_id: str) -> list[dict]:
        """
        Phát hiện fund flow vòng tròn (money laundering pattern).
        
        Cypher:
          MATCH (a:Account {id: $id})-[:TRANSFERS_TO]->(b)-[:TRANSFERS_TO]->(c)
          RETURN a.id, b.id, c.id, (c.id = a.id) AS is_circular
        
        Pattern: A → B → C → A (tiền quay vòng để rửa)
        """
        if self._use_simulator:
            from simulators import neptune_sim
            return neptune_sim.detect_circular_flows(node_id)
        
        with self.driver.session() as session:
            result = session.run("""
                MATCH (a:Account {id: $id})-[r1:TRANSFERS_TO]->(b:Account)-[r2:TRANSFERS_TO]->(c:Account)
                RETURN a.id AS start_id, b.id AS mid_id, c.id AS end_id,
                       r1.total_amount AS amount1, r2.total_amount AS amount2,
                       (c.id = a.id) AS is_circular
            """, id=node_id)
            
            flows = []
            for record in result:
                flows.append({
                    "path": f"{record['start_id']} → {record['mid_id']} → {record['end_id']}",
                    "amounts": [record.get("amount1", 0), record.get("amount2", 0)],
                    "is_circular": record["is_circular"],
                })
            return flows
    
    def find_connections_to_blacklisted(self, node_id: str) -> list[dict]:
        """
        Tìm kết nối (trực tiếp/gián tiếp) đến accounts bị blacklist.
        
        Cypher:
          MATCH (a {id: $id})-[:TRANSFERS_TO*1..3]->(b:Account)
          WHERE b.risk IN ['critical', 'high']
          RETURN b, LENGTH of path
        
        Đây là signal mạnh cho fraud: kết nối đến known bad actors.
        """
        if self._use_simulator:
            from simulators import neptune_sim
            neighbors = neptune_sim.get_neighbors(node_id, depth=2)
            connections = []
            for nid, info in neighbors.get("nodes", {}).items():
                if info.get("risk") in ["critical", "high"] and nid != node_id:
                    connections.append({
                        "account_id": nid,
                        "label": info.get("label", ""),
                        "risk": info.get("risk", ""),
                    })
            return connections
        
        with self.driver.session() as session:
            result = session.run("""
                MATCH path = (a:Account {id: $id})-[:TRANSFERS_TO*1..3]->(b:Account)
                WHERE b.risk IN ['critical', 'high'] AND b.id <> $id
                RETURN DISTINCT b.id AS account_id, b.name AS label, b.risk AS risk,
                       length(path) AS distance
                ORDER BY distance
            """, id=node_id)
            
            return [
                {
                    "account_id": r["account_id"],
                    "label": r["label"],
                    "risk": r["risk"],
                    "distance": r["distance"],
                }
                for r in result
            ]
    
    def run_cypher(self, query: str, params: Optional[dict] = None) -> list[dict]:
        """
        Chạy Cypher query tùy ý (cho Executor Agent flexibility).
        
        FIX: Validate query trước khi chạy — chặn destructive operations
        để tránh LLM-injected harmful queries.
        
        Args:
            query: Cypher query string (chỉ READ-ONLY)
            params: Query parameters (tránh injection)
            
        Returns:
            List of record dicts
        """
        if self._use_simulator:
            print("⚠️  run_cypher không khả dụng với simulator")
            return []
        
        # FIX: Chặn destructive operations
        _BLOCKED_KEYWORDS = [
            "DELETE", "DETACH", "CREATE", "SET ", "REMOVE",
            "DROP", "MERGE", "LOAD CSV", "CALL ", "FOREACH",
        ]
        query_upper = query.upper().strip()
        for keyword in _BLOCKED_KEYWORDS:
            if keyword in query_upper:
                print(f"🚫 Blocked destructive Cypher query: contains '{keyword.strip()}'")
                return []
        
        with self.driver.session() as session:
            result = session.run(query, **(params or {}))
            return [dict(record) for record in result]


# =====================================================================
# SINGLETON INSTANCE
# =====================================================================

neo4j_client = Neo4jClient()
