from functools import lru_cache

from langchain_community.embeddings import HuggingFaceBgeEmbeddings

from config import settings


@lru_cache()
def get_embedding_model() -> HuggingFaceBgeEmbeddings:
    # สร้าง Embedding Model (BGE-M3) สำหรับแปลงข้อความเป็น Vector
    # ใช้ normalize_embeddings=True เพื่อให้ Vector มีขนาดเท่ากัน เหมาะกับ Cosine Similarity
    return HuggingFaceBgeEmbeddings(
        model_name=settings.EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
