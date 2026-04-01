from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import settings


def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2048,
    )


@lru_cache()
def get_rag_chain():
    # RAG Chain หลัก: รับบริบท + ประวัติสนทนา + คำถาม แล้วสร้างคำตอบ
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "คุณคือผู้ช่วยด้านการศึกษาของมหาวิทยาลัย มีหน้าที่ตอบคำถามเกี่ยวกับหลักสูตรและเนื้อหาการเรียน\n\n"
            "กฎสำคัญ:\n"
            "1. ตอบคำถามโดยอ้างอิงจากบริบท (Context) ที่ให้มาเท่านั้น ห้ามแต่งเติมหรือใช้ความรู้ภายนอก\n"
            "2. หากไม่พบคำตอบในบริบทที่ให้มา ให้ตอบว่า "
            "\"ขออภัยครับ/ค่ะ ไม่พบข้อมูลที่เกี่ยวข้องกับคำถามนี้ในเอกสารที่มี "
            "กรุณาติดต่อสอบถามอาจารย์หรือเจ้าหน้าที่โดยตรง\"\n"
            "3. ตอบเป็นภาษาไทยที่สุภาพและเข้าใจง่าย\n"
            "4. ถ้าเป็นไปได้ ให้อ้างอิงหมายเลขหน้าของเอกสารที่ใช้ในการตอบ\n"
            "5. ใช้ประวัติสนทนาเพื่อเข้าใจบริบทของคำถามที่ต่อเนื่อง\n\n"
            "ประวัติสนทนา:\n{history}\n\n"
            "บริบท:\n{context}"
        )),
        ("human", "{query}"),
    ])

    llm = _get_llm()
    return prompt | llm | StrOutputParser()


@lru_cache()
def get_query_condenser():
    # Query Condenser: แปลงคำถามต่อเนื่อง (follow-up) ให้เป็นคำถามที่สมบูรณ์ในตัวเอง
    # เพื่อให้ค้นหาจาก Vector Store ได้แม่นยำขึ้น
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "จากประวัติสนทนาและคำถามล่าสุด ให้เขียนคำถามใหม่ที่สมบูรณ์ในตัวเอง "
            "โดยไม่ต้องอ้างอิงประวัติสนทนา\n"
            "ถ้าคำถามล่าสุดสมบูรณ์อยู่แล้ว ให้คืนคำถามเดิมโดยไม่ต้องแก้ไข\n"
            "ตอบเป็นคำถามเท่านั้น ห้ามอธิบายเพิ่มเติม"
        )),
        ("human", (
            "ประวัติสนทนา:\n{history}\n\n"
            "คำถามล่าสุด: {query}\n\n"
            "คำถามที่สมบูรณ์:"
        )),
    ])

    llm = _get_llm()
    return prompt | llm | StrOutputParser()
