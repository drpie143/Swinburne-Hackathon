# ====================================================================
# CONFIG.PY - Quản lý cấu hình hệ thống (Zero-Cost Stack)
# ====================================================================
# Thay thế AWS services bằng các dịch vụ miễn phí / open-source:
#   - LLM (ALL agents) → Gemini 2.5 Flash (free tier)
#   - Amazon Neptune → Neo4j AuraDB (free forever tier)
#   - Amazon OpenSearch → ChromaDB Cloud (trychroma.com)
#   - Orchestration → LangGraph (open-source)
#   - Backend → FastAPI + BackgroundTasks
# ====================================================================

import os
from pydantic import BaseModel
from dotenv import load_dotenv

# Đọc file .env vào environment variables
load_dotenv()


class Settings(BaseModel):
    """
    Cấu hình toàn cục của hệ thống Fraud Detection.
    
    Zero-Cost Stack:
    - Gemini 2.5 Flash: Free tier cho TẤT CẢ agents (Planner, Detective, Vision, Report)
    - Neo4j AuraDB: Free forever tier cho Graph DB
    - ChromaDB Cloud: Vector store trên trychroma.com (free tier)
    """
    
    # --- Chế độ Demo ---
    # True = dùng simulated Redis/DynamoDB (không cần AWS)
    # Neo4j + ChromaDB + Gemini luôn dùng thật (miễn phí)
    demo_mode: bool = True
    
    # --- Gemini 2.5 Flash ---
    # Free tier: 15 req/min, 1,500 req/day per key
    # Mỗi agent dùng API key riêng để tránh hết quota khi demo
    # Nếu key riêng trống → fallback về gemini_api_key chung
    gemini_api_key: str = ""
    gemini_model_id: str = "gemini-2.5-flash"
    gemini_api_key_planner: str = ""
    gemini_api_key_executor: str = ""
    gemini_api_key_executor_pool: str = ""
    gemini_api_key_detective: str = ""
    gemini_api_key_vision: str = ""
    gemini_api_key_report: str = ""
    
    # --- Neo4j AuraDB (Thay thế Amazon Neptune) ---
    # Free forever tier: 200K nodes, 400K relationships
    # Cypher query language (thay vì Gremlin)
    # Graph visualization đẹp → gây ấn tượng ban giám khảo
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    
    # --- ChromaDB Cloud (Thay thế Amazon OpenSearch) ---
    # Host trên trychroma.com (free tier)
    # Lưu fraud patterns + past cases cho RAG
    chroma_host: str = "api.trychroma.com"
    chroma_api_key: str = ""
    chroma_tenant: str = ""
    chroma_database: str = ""
    chroma_collection_name: str = "fraud_knowledge_base"
    
    # --- Redis Cloud (Thay thế Amazon ElastiCache) ---
    # Redis Cloud free tier hoặc paid tier
    # Dùng cho Phase 1: whitelist, blacklist, risk scores, velocity
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_username: str = "default"
    redis_password: str = ""
    
    # --- MongoDB Atlas (Thay thế DynamoDB) ---
    # Free M0 tier: 512MB storage, shared cluster
    # Lưu customer profiles + transaction history
    mongodb_uri: str = ""
    mongodb_db_name: str = "fraud_detection"
    
    # --- DynamoDB (giữ simulator làm fallback) ---
    dynamodb_endpoint: str = "http://localhost:8000"
    dynamodb_table_transactions: str = "fraud_transactions"
    dynamodb_table_profiles: str = "customer_profiles"
    
    # --- FastAPI ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # --- Agent Configuration ---
    max_investigation_steps: int = 10
    investigation_timeout: int = 30
    confidence_threshold: float = 0.85


def get_settings() -> Settings:
    """
    Tạo Settings object từ environment variables.
    """
    return Settings(
        demo_mode=os.getenv("DEMO_MODE", "true").lower() == "true",
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model_id=os.getenv("GEMINI_MODEL_ID", "gemini-2.5-flash"),
        gemini_api_key_planner=os.getenv("GEMINI_API_KEY_PLANNER", ""),
        gemini_api_key_executor=os.getenv("GEMINI_API_KEY_EXECUTOR", ""),
        gemini_api_key_executor_pool=os.getenv("GEMINI_API_KEY_EXECUTOR_POOL", ""),
        gemini_api_key_detective=os.getenv("GEMINI_API_KEY_DETECTIVE", ""),
        gemini_api_key_vision=os.getenv("GEMINI_API_KEY_VISION", ""),
        gemini_api_key_report=os.getenv("GEMINI_API_KEY_REPORT", ""),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
        chroma_host=os.getenv("CHROMA_HOST", "api.trychroma.com"),
        chroma_api_key=os.getenv("CHROMA_API_KEY", ""),
        chroma_tenant=os.getenv("CHROMA_TENANT", ""),
        chroma_database=os.getenv("CHROMA_DATABASE", ""),
        chroma_collection_name=os.getenv("CHROMA_COLLECTION_NAME", "fraud_knowledge_base"),
        mongodb_uri=os.getenv("MONGODB_URI", ""),
        mongodb_db_name=os.getenv("MONGODB_DB_NAME", "fraud_detection"),
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        redis_username=os.getenv("REDIS_USERNAME", "default"),
        redis_password=os.getenv("REDIS_PASSWORD", ""),
        dynamodb_endpoint=os.getenv("DYNAMODB_ENDPOINT", "http://localhost:8000"),
        dynamodb_table_transactions=os.getenv("DYNAMODB_TABLE_TRANSACTIONS", "fraud_transactions"),
        dynamodb_table_profiles=os.getenv("DYNAMODB_TABLE_PROFILES", "customer_profiles"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8000")),
        max_investigation_steps=int(os.getenv("MAX_INVESTIGATION_STEPS", "10")),
        investigation_timeout=int(os.getenv("INVESTIGATION_TIMEOUT", "30")),
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.85")),
    )


# Singleton instance - import từ các module khác
settings = get_settings()
