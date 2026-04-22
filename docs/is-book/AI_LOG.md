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

## 2026-04-23 (session 7 — draft ch5 + ch6 with research defaults)
- Task: lit search, draft, analyze
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch05-business-feasibility.md` (new ~15K chars, 12 pages)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch06-financial-feasibility.md` (new ~11K chars, 9 pages)
- Research sources (not added to verified-refs.ris — used as market intelligence, not academic citations):
  - MHESI: 154 accredited Thai higher-ed institutions (2023 count)
  - Grand View Research: Thailand bot market USD 125.5M (2024), CAGR 23.6% 2025-2030
  - Botnoi Group: point-based pricing, 7,500 free points/month (1,500 msg)
  - ZWIZ.AI: starts 500 THB/mo, free tier available
  - Anthropic: Opus 4.7 $5/$25 per M tokens
  - Cohere: embed $0.08/M tokens, rerank $2/1K requests
  - Pinecone: Standard $50/mo min, storage $0.33/GB/mo
- Key estimated numbers (all marked with [USER-VERIFY:]):
  - Per-tenant variable cost ~฿2,580/mo (3K queries baseline)
  - Fixed system cost ~฿3,500/mo
  - Personnel cost ~฿120,000/mo (solo baseline)
  - Pricing tiers: Starter 5-8K, Pro 12-18K, Enterprise 25-40K THB/mo
  - Break-even: 14 tenants (base case), 11-12 months payback
  - Initial investment ~300K THB (including dev labor)
- Notes / decisions:
  - User chose option (C) — claude researches defaults with [USER-VERIFY:] markers throughout
  - 31 [USER-VERIFY:] markers total across ch5 (17) + ch6 (14) — every specific number flagged
  - Ch 5 structure: 5.1 market + 5.2 value prop + 5.3 buying center + 5.4 competitors + 5.5 pricing + 5.6 go-to-market + 5.7 SWOT
  - Ch 6 structure: 6.1 cost structure (variable/fixed/personnel) + 6.2 revenue projection + 6.3 initial investment + 6.4 break-even + 6.5 sensitivity (3 scenarios) + 6.6 limitations
  - Running total: ch1-6 done ≈ 85 pages. Remaining: ch7 + front matter + back matter + docx export

---

## 2026-04-22 (D2 end — handoff refresh)
- Task: other (handoff setup)
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/SESSION-HANDOFF.md` (refresh with D2 state: ch1-4 done, 64 pages, 13 refs verified)
  - `~/.claude/.../memory/project_is_book.md` (refresh with updated status, refs table, commit history)
- Notes / decisions:
  - D1 done: ch3 + ch4.1 (~22 pages)
  - D2 done: ch4.2 + ch4.3 + ch1 + ch2 (~42 more pages → total 64 pages)
  - D3 plan: ch5-6 (if unlock Qs answered or user approves research-backed defaults with `[USER-VERIFY:]` markers) + ch7 + front/back matter + docx export
  - D4: submit
  - verified-refs.ris: 13 refs total (started session 1 with 3, added 2 in session 2, added 8 in session 6)
  - No NEW data from user expected unless they add more post-eva or fill sheet 3 of xlsx
  - If blocked indefinitely on unlock Qs, Ch 5-6 can proceed with research-backed defaults tagged `[USER-VERIFY:]` — user can edit before submit

---

## 2026-04-22 (session 6 — draft ch1 + ch2)
- Task: draft, lit search
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch01-introduction.md` (new ~9.4K chars, 7 pages)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch02-literature-review.md` (new ~14.2K chars, 11 pages)
  - `cutip-rag-chatbot/docs/is-book/manuscript/verified-refs.ris` (+8 refs, now RecNum 1-13)
- References verified (this session):
  - Vaswani et al. 2017 — Attention Is All You Need. NeurIPS 30 (#6)
  - Karpukhin et al. 2020 — Dense Passage Retrieval. EMNLP 6769-6781 (#7)
  - Gao et al. 2024 — RAG Survey. arXiv:2312.10997 (#8)
  - Venkatesh & Davis 2000 — TAM2. Management Science 46(2) 186-204 (#9)
  - Anthropic 2024 — Claude 3 Model Card (technical report) (#10)
  - Nogueira & Cho 2019 — Passage Re-ranking with BERT. arXiv:1901.04085 (#11)
  - Robertson & Zaragoza 2009 — BM25 Probabilistic Relevance Framework. Foundations & Trends IR 3(4) 333-389 (#12)
  - Labadze et al. 2023 — AI chatbots in education systematic review. IJEHE 20(1) 56 (#13)
- Ch 1 structure: 1.1-1.6 (problem, RQs, objectives, scope, benefits, terms)
- Ch 2 structure: 2.1 Transformer+Claude, 2.2 RAG (Naive/Advanced/Modular+Agentic), 2.3 DPR+BM25+Reranker, 2.4 Multi-tenant, 2.5 TAM+TAM2, 2.6 Chatbot-edu, 2.7 Conceptual framework
- 24 inline citations spanning 11 unique refs (#1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13)
- Note: Ch 2 is ~11 pages vs 18-22 page design target. Content is complete across 7 sections; pragmatic ship decision — can expand in R11 sweep if needed
- 0 heavy AI patterns (1 "ดังนั้น" usage in ch 2, acceptable)
- 1 [FIGURE 2.1] placeholder (conceptual framework diagram — to generate with Mermaid later)

---

## 2026-04-22 (session 5 — draft ch4.2)
- Task: draft
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch04-results.md` (+ §4.2 ~10K chars)
- Data sources used:
  - `cutip-rag-chatbot/docs/architecture.md` §§1-2 (system overview, microservices), §11 (v1→v2→v2.1 evolution)
  - `cutip-rag-chatbot/docs/thesis-project-detail.md` (referenced)
- Notes / decisions:
  - Structure: 4.2.1 architecture / 4.2.2 evolution v1→v2→v2.1 / 4.2.3 technical metrics
  - Key figures tracked: 266 tests (237 backend + 29 frontend), 14 files → 148 chunks, 24/24 Thai names + 23/23 student IDs + 2/2 emails preserved, 20/20 adversarial probe pass, cold-start 7s → 1.14s (85% ingestion code reduction v1→v2)
  - Citations: Bezemer 2010 #3 used 2x for multi-tenant SaaS architecture
  - 2 FIGURE markers: 4.2 architecture, 4.3 evolution timeline
  - Ch 4 total now 45.5K chars ≈ 35 pages rendered. ~20% over budget (25-30 page target) — trim in R11 final sweep before export

---

## 2026-04-22 (session 4 — draft ch4.3)
- Task: analyze, draft
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch04-results.md` (+ §4.3 ~20K chars, full draft)
- Data sources used:
  - `IS-related/IS-Data/evaluation/project-eva/VIRIYA RAG EVALUATION.xlsx` — sheets "chatbot-evaluation - ธารา" (N=1 Q1-7 with ratings), "admin-portal-task - ธารา", "chatbot-evaluation - พี่แมน" (N=2 evaluator new, 7 topics), "admin-portal-task - พี่แมน"
  - `IS-related/IS-Data/evaluation/post-evaluation-interview/transcript/` — 3 new .txt (ธารา 115 lines + พี่แมน parts 1+2 = 61 lines)
  - `IS-related/CUTIP RAG Final (Responses).xlsx` — TAM survey N=6
- Anonymization additions: introduced **S-05** for พี่แมน (TIP staff #2, evaluator only, not in §4.1 in-depth cohort)
- TAM aggregation:
  - PU 4.25 (Q15-18), PEOU 4.33 (Q19-22), Credibility 4.22 (Q23-25), Intention 4.22 (Q26-28) — all means >4.20/5.0
  - Widest spread: Q20 (pipe+receive without confusion) SD=1.10
- Eval summary (N=2, 14 Qs): 50% deploy-ready / 28.6% need fix / 21.4% unusable. Gaps = ตารางเรียน + ประกาศทุน + ค่าเล่าเรียน (data freshness issue, not model capability)
- Admin portal: Task 1 upload avg 10.5 min diff 3.5 (hardest), Task 2/3 easy 1-2 min 100% success
- Post-eva key quotes (R3+R5 compliant, file+line references preserved):
  - S-01: 16-17 hr/week time saved estimate, chat logs want per-user categorization
  - S-05: 4→2 hr/day reduction, pricing "weighted per student not flat", WTP declined (deferred to ผอ.หลักสูตร), feature wishlist = cross-platform federation with บัณฑิตวิทยาลัย
- Notes / decisions:
  - §4.3 partial answers unlock Q2 (WTP): S-05 explicitly said "can't give price — ผอ. หลักสูตรตัดสิน" + preference for weighted per-student model. Ch5-6 inputs still pending from user on other Qs.
  - Soften 2 minor AI-pattern usages (ดังนั้น → เจ้าหน้าที่จึง; อย่างไรก็ตาม → ข้อที่มีความหลากหลายสูงที่สุด)
  - 0 [TBD:] in §4.3 — data complete for N=2 + N=6
  - 1 [FIGURE 4.1] placeholder for TAM bar chart — to generate later with matplotlib

---

## 2026-04-21 (session end — corrections before handoff)
- Task: other (fix)
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch03-methodology.md` (remove false "นิสิตต่างชาติ" claim in sample description)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch04-results.md` (fix table 4.1 — drop unverified "(ภาคปกติ)" and "ชาวไทย", soften "โรงพยาบาลเอกชน"→"โรงพยาบาลแห่งหนึ่ง", "นักแปลอิสระ"→"นักแปลภาษาญี่ปุ่น")
  - `~/.claude/.../memory/project_is_book.md` (correct ST-01 annotation — จีน is Thai nickname, not Chinese)
- Notes / decisions:
  - User correction: in-depth interview cohort = 4 Thai staff (2 HSM, 1 CUTIP, 1 สิ่งแวดล้อม) + 3 Thai CUTIP students. **No international students interviewed.** Earlier prose wrongly suggested "ครอบคลุมทั้งนิสิตชาวไทยและนิสิตต่างชาติ" — now corrected.
  - References to "นิสิตต่างชาติ" in ch4.1 §4.1.1 (lines 25, 37) remain — they describe HSM's program demographic and visa-operations context per S-02 quote, not the interview cohort. Factually correct.

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
