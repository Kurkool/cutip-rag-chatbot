from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import settings

DEFAULT_PERSONA = (
    "คุณคือผู้ช่วย AI ของมหาวิทยาลัย มีหน้าที่ตอบคำถามนักศึกษาอย่างถูกต้องและเป็นมิตร\n\n"
    "กฎการตอบ:\n"
    "1. ตอบเฉพาะจากข้อมูลในบริบท (Context) ที่ให้มาเท่านั้น ห้ามแต่งเติมหรือเดา\n"
    "2. หากไม่พบคำตอบในบริบท ให้ตอบว่า \"ขออภัยค่ะ ไม่พบข้อมูลที่เกี่ยวข้องกับคำถามนี้ กรุณาติดต่อเจ้าหน้าที่โดยตรง\"\n"
    "3. ถ้าคำถามเป็นภาษาไทย → ตอบภาษาไทย, ถ้าเป็นภาษาอังกฤษ → ตอบภาษาอังกฤษ\n"
    "4. ตอบกระชับ ตรงประเด็น จัดรูปแบบให้อ่านง่าย ใช้ bullet points ตามเหมาะสม\n"
    "5. ข้อมูลตัวเลข (ค่าเทอม, หน่วยกิต, GPA, วันที่) ต้องอ้างอิงจากบริบทเท่านั้น\n"
    "6. ถ้ามีแหล่งอ้างอิง ให้ระบุชื่อเอกสารหรือหน้าที่ใช้\n"
    "7. ใช้ประวัติสนทนาเพื่อเข้าใจบริบทของคำถามที่ต่อเนื่อง"
)


@lru_cache()
def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2048,
    )


def create_rag_chain(persona: str | None = None):
    """สร้าง RAG Chain ด้วย persona เฉพาะ tenant (หรือใช้ default)"""
    system_prompt = persona or DEFAULT_PERSONA
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "{persona}\n\n"
            "ประวัติสนทนา:\n{history}\n\n"
            "บริบท:\n{context}"
        )),
        ("human", "{query}"),
    ])
    return prompt | _get_llm() | StrOutputParser(), system_prompt


@lru_cache()
def get_query_condenser():
    """Query Condenser: แปลงคำถามต่อเนื่อง (follow-up) ให้เป็นคำถามที่สมบูรณ์ในตัวเอง"""
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
    return prompt | _get_llm() | StrOutputParser()
