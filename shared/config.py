from pydantic import field_validator
from pydantic_settings import BaseSettings

APP_VERSION = "6.1.0"


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

    @field_validator("ADMIN_API_KEY")
    @classmethod
    def validate_admin_api_key(cls, v: str) -> str:
        """Either unset (dev/local) or at least 32 chars (prod).

        An 8-char key can be brute-forced; leaving it empty is explicit intent
        to disable the API-key auth path. We reject anything in between so a
        weak production secret can never sneak past code review.
        """
        v = v.strip()
        if v and len(v) < 32:
            raise ValueError("ADMIN_API_KEY must be at least 32 characters (or empty)")
        return v

    # Models
    # Opus 4.7 for the agent — same price as 4.6, better on long-horizon tool use,
    # supports adaptive thinking. Sampling parameters (temperature/top_p/top_k)
    # are removed on 4.7; get_opus() no longer passes temperature.
    LLM_MODEL: str = "claude-opus-4-7"
    EMBEDDING_MODEL: str = "embed-v4.0"
    RERANKER_MODEL: str = "rerank-v3.5"
    # Haiku stays on 4.5 — sub-tasks (decompose/variants/rewrite/summarize/
    # enrichment/vision) don't need Opus; 5× cost for marginal gain.
    VISION_MODEL: str = "claude-haiku-4-5-20251001"

    # Chunking
    CHUNK_SIZE: int = 1500
    CHUNK_OVERLAP: int = 200

    # Retrieval
    RETRIEVAL_K: int = 10
    TOP_K: int = 5           # simple single-topic queries (default)
    TOP_K_COMPLEX: int = 8   # multi-topic or comparison queries (more context)

    # MMR (Maximal Marginal Relevance) — diversify rerank output
    # 0.0 = pure diversity, 1.0 = pure relevance. 0.7 keeps relevance dominant
    # while adding enough diversity to avoid top-K collapsing into near-duplicates.
    MMR_LAMBDA: float = 0.7

    # Search-quality telemetry thresholds
    TELEMETRY_LOW_TOP1_SCORE: float = 0.3        # log if rerank top-1 < this
    TELEMETRY_HIGH_TOOL_COUNT: int = 5           # log if agent makes this many+ tool calls

    # Minimum rerank confidence for a chunk to reach the LLM as context. Below
    # this is treated as irrelevant noise and filtered out. Tunable at runtime
    # so we can loosen during defense Q&A if a valid answer exists but ranks low.
    RERANKER_MIN_CONFIDENCE: float = 0.3

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

    # Ingestion concurrency + retry — shared across enrichment, DOCX image vision,
    # XLSX batch interpretation. Haiku allows ~50 req/min; 5 concurrent with
    # exponential backoff stays well under that.
    INGEST_CONCURRENCY: int = 5
    INGEST_MAX_RETRIES: int = 3

    # Pre-flight size limits — reject oversized docs at upload instead of
    # silent timeout / 429 explosion after minutes of processing.
    PDF_MAX_PAGES: int = 300
    DOCX_MAX_IMAGES: int = 100
    XLSX_MAX_ROWS: int = 20000   # total rows across all sheets

    # Semantic Chunking
    SEMANTIC_CHUNK_PERCENTILE: int = 90

    # Reciprocal Rank Fusion
    RRF_K: int = 60

    # Agent loop
    # Max LangGraph ReAct steps per request. Bumped from 8→12 for Opus 4.7:
    # adaptive thinking consumes steps more aggressively on complex Thai
    # queries, and LangGraph silently returns "Sorry, need more steps…" when
    # remaining_steps < 2 with pending tool_calls (NOT a GraphRecursionError).
    # 12 keeps us under that trigger for typical 2-3 search-call queries with
    # room for one retry variant — without letting a broken loop run wild.
    AGENT_RECURSION_LIMIT: int = 12

    model_config = {"env_file": ".env"}


settings = Settings()
