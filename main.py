import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from schemas import ChatRequest, ChatResponse, IngestResponse
from services.embedding import get_embedding_model
from services.memory import conversation_memory
from services.rag_chain import get_query_condenser, get_rag_chain
from services.reranker import get_reranker, rerank_documents
from services.vectorstore import get_vectorstore


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: โหลด Models ทั้งหมดล่วงหน้า
    get_embedding_model()
    get_vectorstore()
    get_rag_chain()
    get_query_condenser()
    get_reranker()
    yield


app = FastAPI(
    title="University RAG Microservice",
    description="AI Microservice สำหรับระบบถาม-ตอบหลักสูตรมหาวิทยาลัย (เรียกใช้งานผ่าน n8n)",
    version="2.0.0",
    lifespan=lifespan,
)

# Text Splitter สำหรับแบ่งเอกสาร PDF เป็น Chunks ขนาดเล็ก
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=settings.CHUNK_SIZE,
    chunk_overlap=settings.CHUNK_OVERLAP,
)


@app.post("/api/ingest", response_model=IngestResponse)
async def ingest_pdf(file: UploadFile = File(...)):
    """
    รับไฟล์ PDF แล้วประมวลผลเข้าสู่ระบบ RAG
    ขั้นตอน: รับไฟล์ -> อ่าน PDF -> แบ่ง Chunks -> สร้าง Embedding -> บันทึกลง Pinecone
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="รองรับเฉพาะไฟล์ PDF เท่านั้น")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        loader = PyPDFLoader(tmp_path)
        documents = loader.load()
        chunks = text_splitter.split_documents(documents)

        for chunk in chunks:
            chunk.metadata["source_filename"] = file.filename

        vectorstore = get_vectorstore()
        await vectorstore.aadd_documents(chunks)

        return IngestResponse(
            message=f"นำเข้าไฟล์ '{file.filename}' สำเร็จ",
            chunks_processed=len(chunks),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"เกิดข้อผิดพลาดในการประมวลผลเอกสาร: {str(e)}",
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _format_history(history: list[dict]) -> str:
    """แปลงประวัติสนทนาเป็น string สำหรับใส่ใน prompt"""
    if not history:
        return "ไม่มีประวัติสนทนา"
    lines = []
    for turn in history:
        lines.append(f"นักศึกษา: {turn['query']}")
        lines.append(f"ผู้ช่วย: {turn['answer']}")
    return "\n".join(lines)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    RAG Pipeline พร้อม Reranking และ Conversation Memory
    ขั้นตอน: ดึงประวัติ -> Rewrite query -> ค้นหา -> Rerank -> สร้างคำตอบ -> บันทึกประวัติ
    """
    try:
        vectorstore = get_vectorstore()
        rag_chain = get_rag_chain()

        # --- 1. ดึงประวัติสนทนา (ถ้ามี user_id) ---
        history = []
        if request.user_id:
            history = conversation_memory.get_history(request.user_id)

        # --- 2. Rewrite query ถ้ามีประวัติสนทนา ---
        # แปลงคำถามต่อเนื่อง เช่น "แล้วเรื่องนั้นล่ะ?" ให้เป็นคำถามสมบูรณ์
        search_query = request.query
        if history:
            condenser = get_query_condenser()
            search_query = await condenser.ainvoke({
                "history": _format_history(history),
                "query": request.query,
            })

        # --- 3. ค้นหา Chunks จาก Pinecone (ดึงมามากกว่าปกติเพื่อให้ Reranker คัดเลือก) ---
        relevant_docs = await vectorstore.asimilarity_search(
            search_query, k=settings.RETRIEVAL_K
        )

        if not relevant_docs:
            return ChatResponse(
                answer="ขออภัยครับ/ค่ะ ยังไม่มีข้อมูลในระบบ กรุณานำเข้าเอกสารก่อน",
                sources=[],
            )

        # --- 4. Rerank: ใช้ Cross-Encoder จัดลำดับความเกี่ยวข้องใหม่ ---
        reranked_docs = rerank_documents(
            search_query, relevant_docs, top_k=settings.TOP_K
        )

        # --- 5. สร้างคำตอบจาก Claude พร้อมบริบทและประวัติ ---
        context = "\n\n---\n\n".join(
            [doc.page_content for doc in reranked_docs]
        )

        answer = await rag_chain.ainvoke({
            "context": context,
            "history": _format_history(history),
            "query": request.query,
        })

        # --- 6. บันทึกประวัติสนทนา ---
        if request.user_id:
            conversation_memory.add_turn(request.user_id, request.query, answer)

        # รวบรวม metadata ของ Chunks ที่ใช้อ้างอิง
        sources = [
            {
                "page": doc.metadata.get("page", "N/A"),
                "source": doc.metadata.get(
                    "source_filename", doc.metadata.get("source", "N/A")
                ),
            }
            for doc in reranked_docs
        ]

        return ChatResponse(answer=answer, sources=sources)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"เกิดข้อผิดพลาดในการประมวลผลคำถาม: {str(e)}",
        )
