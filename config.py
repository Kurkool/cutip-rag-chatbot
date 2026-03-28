from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str = "university-rag"
    ANTHROPIC_API_KEY: str
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    LLM_MODEL: str = "claude-sonnet-4-6"
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    TOP_K: int = 4

    model_config = {"env_file": ".env"}


settings = Settings()
