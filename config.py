from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "university-rag"

    # Anthropic
    ANTHROPIC_API_KEY: str

    # Cohere (embed-v4 + rerank-v3.5)
    COHERE_API_KEY: str

    # GCP
    GOOGLE_CLOUD_PROJECT: str = "cutip-rag"

    # Admin API Key
    ADMIN_API_KEY: str = ""

    @field_validator("PINECONE_API_KEY", "ANTHROPIC_API_KEY", "COHERE_API_KEY")
    @classmethod
    def strip_and_validate(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("API key must not be empty")
        return v

    # Models
    LLM_MODEL: str = "claude-opus-4-6"
    EMBEDDING_MODEL: str = "embed-v4.0"
    RERANKER_MODEL: str = "rerank-v3.5"
    VISION_MODEL: str = "claude-haiku-4-5-20251001"

    # Chunking
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 150

    # Retrieval
    RETRIEVAL_K: int = 10
    TOP_K: int = 4

    # Conversation Memory
    MAX_HISTORY_TURNS: int = 5
    MEMORY_TTL: int = 1800  # seconds

    # Ingestion
    LIBREOFFICE_TIMEOUT: int = 120  # seconds
    PDF_VISION_THRESHOLD: int = 100  # chars — pages below this use Vision
    PDF_BATCH_SIZE: int = 2  # concurrent Vision calls per batch (low to avoid rate limit)
    XLSX_BATCH_ROWS: int = 100  # rows per Claude interpretation batch

    model_config = {"env_file": ".env"}


settings = Settings()
