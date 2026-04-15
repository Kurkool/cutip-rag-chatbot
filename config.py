from pydantic import field_validator
from pydantic_settings import BaseSettings

APP_VERSION = "4.1.0"


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
    FIREBASE_PROJECT_ID: str = "cutip-rag"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://cutip-admin-portal-265709916451.asia-southeast1.run.app",
    ]

    # Slack alerting (optional — leave empty to disable)
    SLACK_WEBHOOK_URL: str = ""
    SLACK_ALERT_CHANNEL: str = "#rag-alerts"

    # Backup
    BACKUP_GCS_BUCKET: str = "cutip-rag-backups"

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
    CHUNK_SIZE: int = 1500
    CHUNK_OVERLAP: int = 200

    # Retrieval
    RETRIEVAL_K: int = 10
    TOP_K: int = 5

    # Conversation Memory
    MAX_HISTORY_TURNS: int = 5
    MEMORY_TTL: int = 1800  # seconds

    # Rate Limiting (requests per window)
    RATE_LIMIT_CHAT: str = "20/minute"        # per user — LINE + /api/chat
    RATE_LIMIT_ADMIN: str = "60/minute"        # per user — admin CRUD
    RATE_LIMIT_INGESTION: str = "10/minute"    # per tenant — heavy operations
    RATE_LIMIT_AUTH: str = "3/minute"          # per IP — login brute-force protection

    # File upload limits
    MAX_UPLOAD_SIZE_MB: int = 50  # max file size in MB
    ALLOWED_CONTENT_TYPES: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
        "application/vnd.ms-excel",
    ]

    # PDPA / Privacy
    RETENTION_DAYS: int = 90  # days to keep chat logs

    # Ingestion
    LIBREOFFICE_TIMEOUT: int = 120  # seconds
    PDF_VISION_THRESHOLD: int = 100  # chars — pages below this use Vision
    PDF_BATCH_SIZE: int = 2  # concurrent Vision calls per batch (low to avoid rate limit)
    XLSX_BATCH_ROWS: int = 100  # rows per Claude interpretation batch

    # Semantic Chunking
    SEMANTIC_CHUNK_PERCENTILE: int = 90

    # BM25
    BM25_K_CONSTANT: int = 60

    model_config = {"env_file": ".env"}


settings = Settings()
