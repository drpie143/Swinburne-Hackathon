# ====================================================================
# VECTOR_STORE.PY - ChromaDB Cloud Vector Store (trychroma.com)
# ====================================================================
#
# ChromaDB Cloud - host trên trychroma.com:
#   - Kết nối qua HTTP API (api.trychroma.com)
#   - Dùng API key + tenant + database để xác thực
#   - Hỗ trợ semantic search bằng vector embeddings
#   - Free tier đủ cho hackathon demo
#
# Thay thế OpenSearch RAG:
#   - Lưu Known Fraud Patterns
#   - Lưu Past Investigation Cases
#   - Lưu Regulatory Rules
#   - Semantic search (tốt hơn keyword matching)
#
# ADAPTIVE INTELLIGENCE:
#   Khi Detective Agent kết luận BLOCK → pattern mới được index
#   → Lần sau gặp tương tự → phát hiện nhanh hơn
# ====================================================================

from __future__ import annotations
import json
import uuid
from typing import Optional

from config import settings

# ChromaDB có thể không tương thích Python 3.14+
# → Fallback sang OpenSearchSimulator nếu import lỗi
try:
    import chromadb
    _CHROMADB_AVAILABLE = True
except Exception:
    _CHROMADB_AVAILABLE = False
    print("⚠️  ChromaDB không tương thích Python hiện tại")


class VectorStore:
    """
    ChromaDB Cloud Vector Store - RAG Knowledge Base cho Fraud Detection.
    
    Kết nối ChromaDB Cloud trên trychroma.com:
    - HTTP API: api.trychroma.com
    - Xác thực bằng API key + tenant + database
    - Tự động tạo embeddings cho semantic search
    
    So sánh với OpenSearchSimulator cũ:
    - Cũ: keyword matching đơn giản → miss nhiều trường hợp
    - Mới: vector embedding → semantic search chính xác hơn
    """
    
    def __init__(self):
        """
        Khởi tạo ChromaDB Cloud client và collection.
        
        Kết nối đến ChromaDB Cloud qua HttpClient.
        Collection "fraud_knowledge_base" chứa tất cả fraud knowledge.
        """
        try:
            if not _CHROMADB_AVAILABLE:
                raise RuntimeError("ChromaDB not available")
            
            if not settings.chroma_api_key:
                raise RuntimeError("CHROMA_API_KEY chưa cấu hình")
            
            # HttpClient: kết nối ChromaDB Cloud
            self.client = chromadb.HttpClient(
                host=settings.chroma_host,
                ssl=True,
                headers={
                    "x-chroma-token": settings.chroma_api_key,
                },
                tenant=settings.chroma_tenant,
                database=settings.chroma_database,
            )
            
            # Get or create collection
            self.collection = self.client.get_or_create_collection(
                name=settings.chroma_collection_name,
                metadata={"description": "Fraud detection knowledge base"}
            )
            
            print(f"✅ ChromaDB Cloud connected ({settings.chroma_host})")
            print(f"   Tenant: {settings.chroma_tenant}")
            print(f"   Database: {settings.chroma_database}")
            print(f"   Collection: {settings.chroma_collection_name} "
                  f"({self.collection.count()} documents)")
            
        except Exception as e:
            print(f"⚠️  ChromaDB init error: {e}")
            self.client = None
            self.collection = None
    
    def seed_knowledge_base(self):
        """
        Populate ChromaDB với fraud knowledge ban đầu.
        
        Data giống OpenSearchSimulator nhưng dùng vector embeddings
        → semantic search chính xác hơn keyword matching.
        
        Idempotent: check trước khi add để tránh duplicate.
        """
        if not self.collection:
            print("⚠️  Bỏ qua seed (ChromaDB chưa init)")
            return
        
        # Skip nếu đã có data
        if self.collection.count() > 0:
            print(f"ℹ️  ChromaDB đã có {self.collection.count()} documents, bỏ qua seed.")
            return
        
        print("🌱 Seeding fraud knowledge vào ChromaDB...")
        
        # ─── Known Fraud Patterns ───
        documents = [
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
                "metadata": {
                    "type": "fraud_pattern",
                    "risk_level": "high",
                    "confidence_boost": 0.3,
                    "title": "Structuring / Smurfing Pattern",
                },
            },
            {
                "id": "pattern_money_mule",
                "text": (
                    "Money Mule Network: Mạng lưới tài khoản trung gian (money mules) "
                    "được sử dụng để chuyển tiền phi pháp qua nhiều lớp. Các mule "
                    "accounts thường dùng chung thiết bị hoặc IP, được tạo gần đây, "
                    "và nhận tiền từ nhiều nguồn rồi chuyển đến một tài khoản tập trung. "
                    "Indicators: Nhiều accounts dùng chung device/IP, tài khoản mới "
                    "(<90 ngày), nhận tiền từ nhiều nguồn → chuyển đến 1 đích, "
                    "star topology trong graph."
                ),
                "metadata": {
                    "type": "fraud_pattern",
                    "risk_level": "critical",
                    "confidence_boost": 0.35,
                    "title": "Money Mule Network",
                },
            },
            {
                "id": "pattern_ato",
                "text": (
                    "Account Takeover (ATO): Tài khoản bị chiếm đoạt - thay đổi "
                    "đột ngột về device, IP, location, hoặc pattern giao dịch. "
                    "Kẻ gian thường thực hiện GD lớn ngay sau khi take over. "
                    "Indicators: Device mới chưa từng thấy, IP/Location khác biệt "
                    "hoàn toàn, GD lớn đột ngột (>5x average), thay đổi password gần đây."
                ),
                "metadata": {
                    "type": "fraud_pattern",
                    "risk_level": "high",
                    "confidence_boost": 0.25,
                    "title": "Account Takeover (ATO)",
                },
            },
            {
                "id": "pattern_app_fraud",
                "text": (
                    "Authorized Push Payment (APP) Fraud: Nạn nhân bị social engineering "
                    "lừa tự nguyện chuyển tiền. Thường có đặc điểm: GD lớn bất thường, "
                    "chuyển đến tài khoản lạ, nạn nhân gọi ngân hàng xác nhận (vì bị ép). "
                    "Indicators: GD lớn đến tài khoản mới (first-time recipient), "
                    "nạn nhân thay đổi hành vi đột ngột, urgency signals, "
                    "recipient là tài khoản mới/không rõ."
                ),
                "metadata": {
                    "type": "fraud_pattern",
                    "risk_level": "high",
                    "confidence_boost": 0.2,
                    "title": "Authorized Push Payment (APP) Fraud",
                },
            },
            {
                "id": "case_acc666",
                "text": (
                    "Past Case: ACC_666 Money Laundering Ring - ACC_666 được xác nhận "
                    "là trung tâm của mạng lưới rửa tiền. Nhận tiền từ 15+ mule accounts, "
                    "tổng $500K+ trong 3 tháng. Liên quan: MULE_001, MULE_002, MULE_003, "
                    "ACC_050. Đã bị BLOCK và chuyển cho cơ quan chức năng. Date: 2025-09-15."
                ),
                "metadata": {
                    "type": "past_investigation",
                    "decision": "BLOCK",
                    "title": "Case: ACC_666 Money Laundering Ring",
                    "related_accounts": "MULE_001,MULE_002,MULE_003,ACC_050",
                },
            },
            {
                "id": "rule_bsa_aml",
                "text": (
                    "BSA/AML Reporting Threshold: Bank Secrecy Act yêu cầu báo cáo "
                    "CTR (Currency Transaction Report) cho mọi giao dịch > $10,000. "
                    "Structuring để tránh threshold này là vi phạm pháp luật liên bang. "
                    "Threshold: $10,000 cho CTR, $5,000 cho SAR review."
                ),
                "metadata": {
                    "type": "regulatory_rule",
                    "title": "BSA/AML Reporting Threshold",
                    "threshold": "10000",
                },
            },
        ]
        
        # Batch add vào ChromaDB
        self.collection.add(
            ids=[d["id"] for d in documents],
            documents=[d["text"] for d in documents],
            metadatas=[d["metadata"] for d in documents],
        )
        
        print(f"✅ Seeded {len(documents)} documents vào ChromaDB")
    
    def search(self, query: str, top_k: int = 3, filter_type: Optional[str] = None) -> list[dict]:
        """
        Semantic search trong fraud knowledge base.
        
        ChromaDB tự động:
        1. Embed query thành vector
        2. Tìm top-K documents gần nhất (cosine similarity)
        3. Trả về kết quả + metadata + distance
        
        Tốt hơn keyword matching vì hiểu NGHĨA:
        - "nhiều GD nhỏ liên tiếp" → match "Structuring Pattern"
        - "tài khoản dùng chung thiết bị" → match "Money Mule Network"
        
        Args:
            query: Câu truy vấn (tiếng Việt hoặc tiếng Anh)
            top_k: Số kết quả tối đa
            filter_type: Filter theo type (fraud_pattern, past_investigation, etc.)
            
        Returns:
            List[dict] - mỗi dict chứa text, metadata, distance
        """
        if not self.collection or self.collection.count() == 0:
            # Fallback nếu ChromaDB chưa có data
            from simulators import opensearch_sim
            return opensearch_sim.search(query, top_k)
        
        try:
            where_filter = None
            if filter_type:
                where_filter = {"type": filter_type}
            
            results = self.collection.query(
                query_texts=[query],
                n_results=min(top_k, self.collection.count()),
                where=where_filter,
            )
            
            # Format kết quả
            docs = []
            for i in range(len(results["ids"][0])):
                doc = {
                    "id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "distance": results["distances"][0][i] if results.get("distances") else 0,
                }
                if results.get("metadatas") and results["metadatas"][0]:
                    doc.update(results["metadatas"][0][i])
                docs.append(doc)
            
            return docs
            
        except Exception as e:
            print(f"⚠️  ChromaDB search error: {e}")
            from simulators import opensearch_sim
            return opensearch_sim.search(query, top_k)
    
    def index_new_pattern(self, pattern: dict) -> str:
        """
        Thêm fraud pattern MỚI vào knowledge base.
        
        Gọi sau khi Detective Agent kết luận BLOCK:
        → Pattern mới được lưu
        → Lần sau gặp tương tự → phát hiện nhanh hơn
        → Đây là ADAPTIVE INTELLIGENCE
        
        Args:
            pattern: Dict chứa title, description, risk_factors, etc.
            
        Returns:
            ID của document mới
        """
        doc_id = f"case_{uuid.uuid4().hex[:8]}"
        
        if not self.collection:
            # Fallback
            from simulators import opensearch_sim
            return opensearch_sim.index_new_pattern(pattern)
        
        try:
            text = f"{pattern.get('title', '')} - {pattern.get('description', '')}"
            if pattern.get('risk_factors'):
                text += f" Risk factors: {', '.join(pattern['risk_factors'][:5])}"
            
            metadata = {
                "type": pattern.get("type", "past_investigation"),
                "title": pattern.get("title", "Unknown Case"),
                "decision": pattern.get("decision", "BLOCK"),
            }
            
            self.collection.add(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata],
            )
            
            print(f"   📚 Indexed new pattern: {doc_id}")
            return doc_id
            
        except Exception as e:
            print(f"⚠️  ChromaDB index error: {e}")
            return doc_id


# =====================================================================
# SINGLETON INSTANCE
# =====================================================================

vector_store = VectorStore()
