from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "university-rag"
    ANTHROPIC_API_KEY: str

    @field_validator("PINECONE_API_KEY", "ANTHROPIC_API_KEY")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    LLM_MODEL: str = "claude-sonnet-4-6"
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    TOP_K: int = 4

    model_config = {"env_file": ".env"} #for local development


settings = Settings()
