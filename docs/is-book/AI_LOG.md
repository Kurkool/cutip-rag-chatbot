# AI Session Log

บันทึกทุก session ที่ Claude เข้ามาช่วยงานเล่ม IS ใช้สำหรับ acknowledgement และ audit trail ตาม R10

Format:
```
## YYYY-MM-DD
- Task: <polish | translate | lit search | analyze | outline | code | other>
- Files touched: <paths>
- References verified: <list with DOIs>
- Notes / decisions: <anything the committee might ask about>
```

---

## 2026-04-21 (session end — handoff setup)
- Task: other (session handoff)
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/SESSION-HANDOFF.md` (new — startup guide for next session/computer)
  - `~/.claude/projects/.../memory/project_is_book.md` (new — persistent memory for IS book work)
  - `~/.claude/projects/.../memory/MEMORY.md` (add pointer to project_is_book.md)
  - `~/.claude/projects/.../memory/project_tip_rag.md` (replaced "user uses Gemini to write thesis" with IS Book Writing Phase note pointing at project_is_book + SESSION-HANDOFF)
- References verified: ไม่มี
- Notes / decisions:
  - Auto-memory + handoff doc + updated project memory = next session can pick up from clean start
  - Quick-start prompt added to SESSION-HANDOFF.md: read CLAUDE.md + AI_LOG.md + spec + handoff, confirm unlock Q status, then resume
  - D2 priority order: ch4.2 (derivative, no blocker) → ch4.3 (partial blocker on N) → ch1 (derivative) → ch2 (ref verify) → ch5-6 (blocked on user inputs)

---

## 2026-04-21 (session 3 — draft ch4.1)
- Task: analyze, draft
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch04-results.md` (new — §4.1 only, ~12K chars, 8-10 pages)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch03-methodology.md` (fix — program name correction)
- Data sources used:
  - 8 transcripts ใน `IS-related/IS-Data/indepth-interview/transcript/*.txt` (read: CUTIP partial, HSM_ผู้ช่วย, HSM_จิ๋ว parts 1-2, สิ่งแวดล้อม_แหวน, จีน partial, เอ๋, ปุ้ย parts 1-2)
  - Question set docx ในโฟลเดอร์ `question-set/`
- Quotes extracted: ~25 direct quotes พร้อม file+line references (R3+R5 compliant)
- Anonymization: S-01..S-04 (staff), ST-01..ST-03 (student)
- Notes / decisions:
  - Confirmed staff breakdown: 1 TIP (ธารา) + 2 HSM (ศิมาพร, วรัญญา) + 1 วิทยาศาสตร์สิ่งแวดล้อม (แหวน) ← user confirmed program name
  - Program full names: HSM = "สหสาขาวิชาการจัดการสารอันตรายและสิ่งแวดล้อม", พี่แหวน = "สหสาขาวิชาวิทยาศาสตร์สิ่งแวดล้อม"
  - Students ทั้ง 3 ท่านจากหลักสูตร TIP (จากข้อมูล survey + transcripts)
  - ไม่มี [TBD:] ใน §4.1 — data หนาแน่น (อาจเพิ่ม [TBD:] ถ้า user ตรวจพบจุดคลาดเคลื่อน)
  - §4.1 อ้างถึง §4.2 (development) และ §4.3 (evaluation) — ยังไม่เขียน

---

## 2026-04-21 (session 2 — draft ch3)
- Task: draft, lit search
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/verified-refs.ris` (new — canonical refs file, 5 entries so far)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch03-methodology.md` (new — full draft ~4500 words, 10-12 pages)
- References verified (in addition to 3 from session 1):
  - Creswell, J. W., & Plano Clark, V. L. (2018). Designing and Conducting Mixed Methods Research (3rd ed.). SAGE Publications. — verified via SAGE + multiple citing sources
  - Braun, V., & Clarke, V. (2006). Using thematic analysis in psychology. Qualitative Research in Psychology, 3(2), 77-101. DOI 10.1191/1478088706qp063oa — verified via Taylor & Francis + Scholar
- Placeholders remaining in ch3:
  - `[TBD: ระบุช่องทาง Zoom/in-person]` สำหรับวิธีสัมภาษณ์ Phase 1
  - `[TBD: ระบุช่วงเวลา 30-60 นาที]` สำหรับระยะเวลาสัมภาษณ์
  - `[TBD: N=1 หรือ 3]` × 2 จุดสำหรับจำนวนผู้ประเมิน chatbot/portal
  - `[FIGURE 3.1]` 3-phase process diagram
  - `[FIGURE 3.2]` system architecture
- Notes / decisions:
  - Voice calibrated จากตัวอย่างพี่อู๋ — ใช้ "ผู้วิจัย", ศัพท์ไทย+(English), heading ลึก 4 ชั้น
  - Self-review รอบแรกพบ fabricated specifics ("3 เดือน experience", "6 เดือน history", "45-90 นาที"): แก้เป็น `[TBD:]` หรือ soften language (R1 compliance)
  - v1 architecture ไม่ใช่ rule-based (เดิมเคยเรียกผิด) — แก้เป็น "Static Pipeline" ที่แยก logic per doc type
  - ใช้ temp cite `{Author, Year #N}` ทั้งหมด 4 จุด (Creswell×1, Braun×2, Davis×1)

---

## 2026-04-21 (session 1 — setup)
- Task: outline, setup workspace, toolchain verification (docx + EndNote)
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/CLAUDE.md` (new — copy จาก `C:\Users\USER\Downloads\CLAUDE.md`)
  - `cutip-rag-chatbot/docs/is-book/AI_LOG.md` (new)
  - `cutip-rag-chatbot/docs/is-book/manuscript/` (empty dir placeholder)
  - `cutip-rag-chatbot/docs/is-book/endnote-sample/{verified-refs-sample.ris, sample-manuscript.docx, README.md}` (new — EndNote POC)
  - `cutip-rag-chatbot/docs/superpowers/specs/2026-04-21-is-book-design.md` (new — design spec)
  - `IS-related/IS-book-thai-test.docx` (one-off — test Thai rendering in Word, user confirmed OK)
- References verified:
  - Lewis, P., et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS 33, 9459-9474. — verified via NeurIPS proceedings + dblp + arXiv 2005.11401
  - Davis, F. D. (1989). Perceived Usefulness, Perceived Ease of Use, and User Acceptance of Information Technology. MIS Quarterly, 13(3), 319-340. DOI 10.2307/249008 — verified via misq.umn.edu + AIS eLibrary
  - Bezemer, C.-P., & Zaidman, A. (2010). Multi-tenant SaaS applications: maintenance dream or nightmare? Proceedings of the Joint ERCIM Workshop on Software Evolution (EVOL) and IWPSE, 88-92. ACM. — verified via Semantic Scholar + author publication list
- Notes / decisions:
  - Deadline ส่งเล่ม IS: **ศุกร์ 2026-04-24**
  - Approach = B (risk-first: บท 4-6 ก่อน, บท 1-3 และ 7 หลัง)
  - N evaluator ปัจจุบัน = 1 (จะ update เป็น 3 ถ้าได้เพิ่ม) — ch 4 เขียนแบบ N ตัวแปร
  - Raw data ห้ามแก้ อยู่ที่ `IS-related/IS-Data/`
  - Manuscript อยู่ใน git repo (`cutip-rag-chatbot/docs/is-book/`)
  - Output pipeline: `python-docx` (ไม่ใช่ pandoc — pandoc ไม่ติดตั้ง, python-docx ควบคุม Thai rendering ได้ละเอียดกว่า)
  - docx test ผ่าน: TH Sarabun New 16pt + th-TH lang tag + Chula margins (L 1.5", RTB 1")
  - Citation workflow: EndNote temp cite `{Author, Year #RecNum}` + `.ris` import — **VALIDATED** end-to-end 2026-04-21 (v2 RIS fix: Lewis=JOUR, Bezemer=CHAP+BT → APA 7 render ครบทุก field)
  - Figures: mix plan — ผม gen Mermaid/matplotlib, user capture screenshots + business canvas, markers `[FIGURE X.Y]`/`[USER-FIGURE X.Y]`/`[TBD:]`/`[USER-VERIFY:]`
