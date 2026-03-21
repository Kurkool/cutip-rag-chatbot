from functools import lru_cache

from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from config import settings
from services.embedding import get_embedding_model


@lru_cache()
def get_vectorstore() -> PineconeVectorStore:
    # เชื่อมต่อกับ Pinecone และสร้าง Vector Store สำหรับจัดเก็บ/ค้นหา Embedding
    pc = Pinecone(api_key=settings.PINECONE_API_KEY)
    index = pc.Index(settings.PINECONE_INDEX_NAME)
    return PineconeVectorStore(
        index=index,
        embedding=get_embedding_model(),
    )
