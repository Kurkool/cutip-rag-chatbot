import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import settings
from schemas import ChatRequest, ChatResponse, IngestResponse
from services.embedding import get_embedding_model
from services.rag_chain import get_rag_chain
from services.vectorstore import get_vectorstore


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: โหลด Embedding Model, เชื่อมต่อ Pinecone, และสร้าง RAG Chain ล่วงหน้า
    # เพื่อให้ Application พร้อมรับ request ได้ทันทีโดยไม่ต้องรอ initialize ตอนเรียกใช้
    get_embedding_model()
    get_vectorstore()
    get_rag_chain()
    yield


app = FastAPI(
    title="University RAG Microservice",
    description="AI Microservice สำหรับระบบถาม-ตอบหลักสูตรมหาวิทยาลัย (เรียกใช้งานผ่าน n8n)",
    version="1.0.0",
    lifespan=lifespan,
)

# Text Splitter สำหรับแบ่งเอกสาร PDF เป็น Chunks ขนาดเล็ก
# chunk_overlap ช่วยให้บริบทระหว่าง Chunks ไม่ขาดหาย
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
        # บันทึกไฟล์ PDF ลง temp เพื่อให้ PyPDFLoader อ่านได้
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # โหลด PDF และแบ่งเป็น Chunks ด้วย RecursiveCharacterTextSplitter
        # Loader จะแยกข้อความแต่ละหน้าพร้อม metadata (หมายเลขหน้า)
        loader = PyPDFLoader(tmp_path)
        documents = loader.load()
        chunks = text_splitter.split_documents(documents)

        # เพิ่ม metadata ชื่อไฟล์ต้นฉบับ เพื่อใช้อ้างอิงแหล่งที่มาตอนตอบคำถาม
        for chunk in chunks:
            chunk.metadata["source_filename"] = file.filename

        # แปลง Chunks เป็น Vectors (ผ่าน BGE-M3) แล้ว Upsert ลง Pinecone
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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    หัวใจหลักของ RAG Pipeline - รับคำถามนักศึกษาแล้วตอบโดยอ้างอิงจากเอกสาร
    ขั้นตอน: รับคำถาม -> ค้นหาบริบทจาก Pinecone -> ส่งให้ Claude สร้างคำตอบ
    """
    try:
        vectorstore = get_vectorstore()
        rag_chain = get_rag_chain()

        # ค้นหา Chunks ที่มีความหมายใกล้เคียงกับคำถามมากที่สุดจาก Pinecone (Similarity Search)
        # BGE-M3 จะแปลงคำถามเป็น Vector แล้วเทียบกับ Vectors ที่เก็บไว้
        relevant_docs = await vectorstore.asimilarity_search(
            request.query, k=settings.TOP_K
        )

        if not relevant_docs:
            return ChatResponse(
                answer="ขออภัยครับ/ค่ะ ยังไม่มีข้อมูลในระบบ กรุณานำเข้าเอกสารก่อน",
                sources=[],
            )

        # รวมเนื้อหาจาก Chunks ที่ค้นพบเป็นบริบท (Context) สำหรับส่งให้ LLM
        context = "\n\n---\n\n".join(
            [doc.page_content for doc in relevant_docs]
        )

        # ส่งบริบทและคำถามเข้า RAG Chain -> Claude สร้างคำตอบจากบริบทที่ให้เท่านั้น
        answer = await rag_chain.ainvoke({
            "context": context,
            "query": request.query,
        })

        # รวบรวม metadata ของ Chunks ที่ใช้อ้างอิง (หมายเลขหน้า, ชื่อไฟล์)
        sources = [
            {
                "page": doc.metadata.get("page", "N/A"),
                "source": doc.metadata.get(
                    "source_filename", doc.metadata.get("source", "N/A")
                ),
            }
            for doc in relevant_docs
        ]

        return ChatResponse(answer=answer, sources=sources)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"เกิดข้อผิดพลาดในการประมวลผลคำถาม: {str(e)}",
        )
