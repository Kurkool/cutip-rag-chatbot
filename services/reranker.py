from functools import lru_cache

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from config import settings


@lru_cache()
def get_reranker() -> CrossEncoder:
    # โหลด Cross-Encoder สำหรับ Reranking เพื่อจัดลำดับความเกี่ยวข้องของ Chunks ใหม่
    return CrossEncoder(settings.RERANKER_MODEL)


def rerank_documents(
    query: str, documents: list[Document], top_k: int
) -> list[Document]:
    """
    รับ Chunks ที่ได้จาก Vector Search แล้วใช้ Cross-Encoder ให้คะแนนความเกี่ยวข้องใหม่
    Cross-Encoder แม่นยำกว่า Bi-Encoder (Embedding) เพราะเปรียบเทียบ query กับ document พร้อมกัน
    """
    if not documents:
        return documents

    pairs = [[query, doc.page_content] for doc in documents]
    scores = get_reranker().predict(pairs)

    scored_docs = sorted(
        zip(scores, documents), key=lambda x: x[0], reverse=True
    )
    return [doc for _, doc in scored_docs[:top_k]]
