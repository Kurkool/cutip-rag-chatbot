from functools import lru_cache

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config import settings


@lru_cache()
def get_rag_chain():
    # สร้าง RAG Chain: Prompt Template -> LLM (Claude) -> Output Parser
    # กำหนด System Prompt ให้ AI ตอบเฉพาะจากบริบทที่ให้มา เพื่อป้องกัน Hallucination
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "คุณคือผู้ช่วยด้านการศึกษาของมหาวิทยาลัย มีหน้าที่ตอบคำถามเกี่ยวกับหลักสูตรและเนื้อหาการเรียน\n\n"
            "กฎสำคัญ:\n"
            "1. ตอบคำถามโดยอ้างอิงจากบริบท (Context) ที่ให้มาเท่านั้น ห้ามแต่งเติมหรือใช้ความรู้ภายนอก\n"
            "2. หากไม่พบคำตอบในบริบทที่ให้มา ให้ตอบว่า "
            "\"ขออภัยครับ/ค่ะ ไม่พบข้อมูลที่เกี่ยวข้องกับคำถามนี้ในเอกสารที่มี "
            "กรุณาติดต่อสอบถามอาจารย์หรือเจ้าหน้าที่โดยตรง\"\n"
            "3. ตอบเป็นภาษาไทยที่สุภาพและเข้าใจง่าย\n"
            "4. ถ้าเป็นไปได้ ให้อ้างอิงหมายเลขหน้าของเอกสารที่ใช้ในการตอบ\n\n"
            "บริบท:\n{context}"
        )),
        ("human", "{query}"),
    ])

    # สร้าง LLM instance โดยตั้ง temperature ต่ำเพื่อให้ตอบตรงประเด็นและลด Hallucination
    llm = ChatAnthropic(
        model=settings.LLM_MODEL,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        temperature=0.1,
        max_tokens=2048,
    )

    # เชื่อม Chain: Prompt -> LLM -> แปลงผลลัพธ์เป็น String
    return prompt | llm | StrOutputParser()
