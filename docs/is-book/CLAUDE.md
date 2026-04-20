## 🚫 HARD RULES (ห้ามละเมิดเด็ดขาด)

### R1. NO FABRICATION
ห้ามสร้างข้อมูลเหล่านี้ขึ้นเองทุกกรณี :
- ตัวเลข / สถิติ / ผล quantitative / p-value / effect size
- คำสัมภาษณ์ / quote / case study / persona
- ชื่อบุคคล บริษัท สถานที่ เหตุการณ์

ถ้าจำเป็นต้องมี placeholder → ใช้ `[TBD: ใส่ข้อมูลจริงจาก <source>]` เสมอ

### R2. NO HALLUCINATED CITATIONS
ก่อนใส่ reference ใดๆ ในเล่ม ต้องทำตามลำดับนี้:
1. ใช้ `WebSearch` / `WebFetch` verify ว่า paper / book มีอยู่จริง
2. ตรวจ author / year / title / journal / volume / pages ให้ตรงต้นฉบับ
3. ถ้า DOI มี → fetch ตรวจหน้าที่อ้าง
4. ห้ามใส่ หาก verify ไม่ได้

**Red flag:** reference ที่ทุก field ครบสมบูรณ์เป๊ะจากความจำ → สงสัยไว้ก่อนเสมอ

### R3. RAW DATA INTEGRITY
Raw data files (transcripts, surveys, field notes, datasets):
- อ่าน / วิเคราะห์ / สรุปได้
- **ห้ามแก้ไขคำพูดต้นฉบับ หรือดัดแปลงตัวเลข**
- ก่อน paste ลงเล่ม → เทียบกับ raw ว่าไม่เพี้ยน ถ้าต้อง clean ต้อง log การ clean ไว้ด้วย
- raw files ทั้งหมดให้อยู่ใน `IS-related/IS-Data` ห้ามแก้ ห้ามเขียนทับ

### R4. CALIBRATED UNCERTAINTY
- ไม่แน่ใจ 100% → พูดตรงๆ ว่า "ยังไม่แน่ใจ ต้องตรวจ"
- ห้ามเดาให้ดูมั่นใจ
- niche topic / specific number / specific date / quote → verify ทุกครั้ง ไม่พึ่งความจำ

---

## ✍️ WRITING RULES

### R5. Deep paraphrase
- เปลี่ยนทั้งโครงประโยค + ศัพท์ ไม่ใช่สลับคำ 2-3 คำ
- เทียบกับต้นฉบับแล้วยังเห็นโครงเดิม → rewrite อีก
- direct quote > 3 คำ → ใส่ `"..."` + หน้า/บรรทัด

### R6. รักษาเสียงของการเขียน
ก่อนเขียน → อ่านส่วนที่มีอยู่ จับ tone / ศัพท์ / ความยาวประโยค
output ต้องกลืนกับส่วนนั้น

**หลีกเลี่ยงสำนวน AI generic:**
- วลีเปิดแบบ "ในโลกที่เปลี่ยนแปลงอย่างรวดเร็ว..." / "ในยุคปัจจุบัน..."
- em-dash ถี่เกินเหตุ
- bullet list ซ้อนกันยาวๆ เมื่อ prose เหมาะกว่า
- คำเชื่อมสำเร็จรูปถี่ ("นอกจากนี้" / "อย่างไรก็ตาม" / "ดังนั้น" ทุก 2 ประโยค)
- ประโยคปิดแบบ "โดยสรุปแล้ว..."
- การยกสามประเด็นแบบ triadic ทุกย่อหน้า

เป้าหมาย: อ่านแล้วเหมือนนิสิต ปโท เขียน

### R7. AI detector = ผลข้างเคียง ไม่ใช่เป้าหมาย
ถ้าทำ R5-R6 ถูก detector จะไม่จับเอง
ถ้าโดนจับ = เนื้อหา/เสียงยังไม่พอ → แก้ที่ต้นเหตุ ไม่ใช่ "หลบ detector"

---

## 📋 WORKFLOW

### R8. ก่อนเริ่ม task
- อ่าน chapter/section ที่เกี่ยวข้องก่อน (`Read` tool)
- อ่าน `AI_LOG.md` ดูว่าทำอะไรไปแล้ว
- context ไม่พอ → ถามก่อน อย่าเดา

### R9. ระหว่างทำงาน
- จะใส่ข้อเท็จจริง / ตัวเลข / ref. → `WebSearch` verify ก่อน ทุกครั้ง
- แก้เป็น small diffs ให้นิสิตตรวจทีละส่วน
- ห้ามแก้หลายไฟล์พร้อมกันโดยไม่แจ้ง

### R10. Update `AI_LOG.md` ทุก session
ใช้สำหรับเขียน acknowledgement ตอนจบ format:
```
## YYYY-MM-DD
- Task: <polish | translate | lit search | analyze | outline | code | other>
- Files touched: <paths>
- References verified: <list with DOIs>
- Notes / decisions: <anything the committee might ask about>
```

### R11. ก่อน finalize บท
- ไล่ตรวจ citation ทุกอันอีกรอบ (ไม่ trust session ก่อนหน้า)
- หา placeholder `[TBD:...]` ที่ยังค้าง
- ประโยคไหนอธิบายไม่ได้ = ลบหรือเขียนใหม่

---

## 🚩 STOP AND ASK(red flags ที่ต้องหยุดแล้วเตือน)

- เจอตัวเลข/สถิติ ที่หา source ไม่ได้

---

## MODEL
- **Model:** Claude Opus 4.7
- **Provider:** Anthropic
- **Interface:** Claude Code
