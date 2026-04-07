from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "university-rag"

    # Anthropic
    ANTHROPIC_API_KEY: str

    # Cohere (embed-v4 + rerank-v3.5)
    COHERE_API_KEY: str = ""

    # GCP
    GOOGLE_CLOUD_PROJECT: str = "cutip-rag"

    # Admin API Key
    ADMIN_API_KEY: str = ""

    @field_validator("PINECONE_API_KEY", "ANTHROPIC_API_KEY")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    # Models
    EMBEDDING_MODEL: str = "embed-v4.0"
    RERANKER_MODEL: str = "rerank-v3.5"
    LLM_MODEL: str = "claude-opus-4-6"

    # Chunking
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 150

    # Retrieval
    RETRIEVAL_K: int = 10  # จำนวน chunks ที่ดึงมาก่อน rerank
    TOP_K: int = 4  # จำนวน chunks สุดท้ายหลัง rerank

    # Conversation Memory
    MAX_HISTORY_TURNS: int = 5  # จำนวนรอบสนทนาที่เก็บไว้ต่อ user
    MEMORY_TTL: int = 1800  # หมดอายุหลัง 30 นาทีไม่มีข้อความ

    model_config = {"env_file": ".env"}


settings = Settings()
