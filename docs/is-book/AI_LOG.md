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

## 2026-04-21
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
  - Citation workflow: EndNote temp cite `{Author, Year #RecNum}` + `.ris` import — รอ user test sample-manuscript.docx + POC ก่อนลงแรง
  - Figures: mix plan — ผม gen Mermaid/matplotlib, user capture screenshots + business canvas, markers `[FIGURE X.Y]`/`[USER-FIGURE X.Y]`/`[TBD:]`/`[USER-VERIFY:]`
