# Design Spec — IS Thesis Book "VIRIYA"

**Date:** 2026-04-21
**Author:** Kurkool Ussawadisayangkool (6780016820)
**Advisor:** อ.นกุล คูหะโรจนานนท์
**Program:** TIP (Technopreneurship and Innovation Management), CU Graduate School
**Deadline:** ศุกร์ 2026-04-24 (3 วันนับจากวันนี้)

---

## 1. ภาพรวม

ผลิต IS thesis book ภาษาไทย ฉบับสมบูรณ์ (~120-140 หน้า) สำหรับโปรเจค **VIRIYA** — Multi-tenant agentic RAG chatbot platform สำหรับคณะ/หลักสูตรในมหาวิทยาลัย ที่ใช้ LINE OA เป็นหน้าบ้านและ Admin Portal เป็นหลังบ้าน

Manuscript ต้องผ่านมาตรฐานการพิมพ์วิทยานิพนธ์ของบัณฑิตวิทยาลัย จุฬาฯ (font Sarabun, margin ซ้าย 1.5" ขวา/บน/ล่าง 1", APA 7)

## 2. Constraints และ ground rules

- **Hard rules R1-R11** ที่ `docs/is-book/CLAUDE.md` มีผลบังคับทุก session — ไม่ fabricate ตัวเลข/quote/citation, ไม่แก้ raw data, log ทุก session ใน AI_LOG.md
- **Raw data** อยู่ที่ `IS-related/IS-Data/` (read-only) ตาม R3
- Manuscript อยู่ใน git repo `cutip-rag-chatbot/` — commit ทีละบท, user push เอง
- AI detector (akarawisut.com) เป็น post-check ปลาย pipeline — voice ต้อง pass ตาม R5+R6

## 3. Approach

**Approach B (Risk-first)** — เขียนบทที่ยากและต้องการ user input ก่อน

| ลำดับ | บท | เหตุผลจัดลำดับ |
|---|---|---|
| 1 | บท 4 (ผล/วิเคราะห์) | Data พร้อมแล้ว (interview + survey + eval), เขียนได้ทันที |
| 2 | บท 5-6 (ธุรกิจ/การเงิน) | ต้องรอ user ตอบ unlock questions — ถ้าช้าจะ block |
| 3 | บท 1-3 (บทนำ/lit review/วิธีวิจัย) | Derivative จาก source material, ทำภายหลังได้ |
| 4 | บท 7 + front/back matter | ต้องใช้เนื้อหาจากบท 1-6 ประกอบ |
| 5 | Pandoc export → `.docx` | Polish ปลาย pipeline |

## 4. โครงสร้างเล่ม

### 4.1 Front matter (~10-12 หน้า)
- ปกภาษาไทย + ปกภาษาอังกฤษ
- หน้าอนุมัติ (Approval Page)
- บทคัดย่อภาษาไทย + ภาษาอังกฤษ
- กิตติกรรมประกาศ (Acknowledgements — อ้างอิง AI_LOG.md ตาม R10)
- สารบัญ / สารบัญตาราง / สารบัญภาพ / คำอธิบายสัญลักษณ์

### 4.2 บทที่ 1 บทนำ (~6-8 หน้า)

- 1.1 ความเป็นมาและความสำคัญของปัญหา — information overload นิสิต + ภาระงานซ้ำของเจ้าหน้าที่
- 1.2 คำถามวิจัย (research questions)
- 1.3 วัตถุประสงค์ของการศึกษา
- 1.4 ขอบเขตของการศึกษา — tenant แรก = CU-TIP, pilot HSM + สิ่งแวดล้อม
- 1.5 ประโยชน์ที่คาดว่าจะได้รับ
- 1.6 นิยามศัพท์เฉพาะ — RAG, LLM, Agentic, Multi-tenant SaaS, LINE OA, namespace

**Source:** IS proposal + `thesis-project-detail.md` §1-3

### 4.3 บทที่ 2 ทบทวนวรรณกรรมและงานวิจัยที่เกี่ยวข้อง (~18-22 หน้า)

- 2.1 Generative AI และ Large Language Models
  - 2.1.1 Transformer architecture overview
  - 2.1.2 Claude family (Opus 4.7, Haiku 4.5) — Anthropic
  - 2.1.3 ข้อจำกัด: hallucination, knowledge cutoff
- 2.2 Retrieval-Augmented Generation (RAG)
  - 2.2.1 Lewis et al. (2020) — original RAG paper
  - 2.2.2 Hybrid search (dense + BM25) / reranking (cross-encoder)
  - 2.2.3 Agentic RAG (tool calling, multi-step retrieval)
- 2.3 Vector Embeddings และ Semantic Search
  - 2.3.1 Embedding models — Cohere embed-v4.0
  - 2.3.2 Vector databases — Pinecone serverless + namespaces
- 2.4 Multi-tenant SaaS Architecture
  - 2.4.1 Bezemer & Zaidman (2010)
  - 2.4.2 Data isolation patterns
- 2.5 Technology Acceptance Model (TAM)
  - 2.5.1 Davis (1989) — original TAM
  - 2.5.2 Perceived Usefulness / Ease of Use / Behavioral Intention
- 2.6 Chatbot ในบริบทการศึกษา
  - 2.6.1 Wang et al. (2023)
  - 2.6.2 LINE OA ในอุดมศึกษาไทย (ถ้าหา paper ได้)
- 2.7 กรอบแนวคิดของการศึกษา (Conceptual Framework)

**Source:** proposal §4-5 + WebSearch verified papers (ตาม R2)
**Budget:** ~20-25 refs × 5-10 นาที verify = 2-3 ชม. (D2 เช้า)

### 4.4 บทที่ 3 วิธีการดำเนินการวิจัย (~10-12 หน้า)

- 3.1 ประเภทของการวิจัย — Mixed methods (qualitative + quantitative) + design science research
- 3.2 กรอบการดำเนินงาน 3 ระยะ
  - Phase 1: Exploration (in-depth interview) — ม.ค.-ก.พ. 2569
  - Phase 2: Development (RAG pipeline v1 → v2 → v2.1) — ก.พ.-มี.ค. 2569
  - Phase 3: Evaluation (hands-on eval + TAM survey + post-eva interview) — เม.ย. 2569
- 3.3 กลุ่มตัวอย่าง — staff 5 ท่าน (CUTIP, HSM, สิ่งแวดล้อม), นิสิต 3 ท่าน (interview), นิสิต N=6 (survey), evaluator N=[TBD: 1 หรือ 3]
- 3.4 เครื่องมือวิจัย — question sets 3 ชุด (`RAG-indepth-เจ้าหน้าที่.docx`, `RAG-indepth-นิสิต.docx`, `Staff_InDepth_Interview_Post_Eva.docx`)
- 3.5 protocol การประเมิน
  - Chatbot evaluation: staff เปิดเอกสารต้นฉบับ → พิมพ์คำถาม → ประเมินคุณภาพ + deploy-ready + เอกสารอ้างอิง (7 Q)
  - Admin portal evaluation: demo 1 รอบ → staff ทำ 3 tasks (upload doc, chat logs, analytics) → บันทึกสำเร็จ/เวลา/ความยาก
  - Post-eva interview: 13 Q ตาม `Staff_InDepth_Interview_Post_Eva.docx`
- 3.6 การวิเคราะห์ข้อมูล — thematic analysis (qualitative) + descriptive stats (quantitative, Likert mean+SD)
- 3.7 จริยธรรมการวิจัย — anonymize ผู้ให้สัมภาษณ์ในภาคผนวก

**Source:** proposal §6 + question set files + `thesis-project-detail.md` §7-14

### 4.5 บทที่ 4 ผลการทำวิจัยและการวิเคราะห์ข้อมูล (~25-30 หน้า) ⭐ เขียนก่อน

- 4.1 ผล Phase 1 — in-depth interview
  - 4.1.1 กลุ่มเจ้าหน้าที่ (5 ท่าน) — themes: time allocation, top-3 คำถามซ้ำ, knowledge management workaround (Google Doc ลิงก์เดียว), pain points
  - 4.1.2 กลุ่มนิสิต (3 ท่าน) — themes: information-seeking behavior, trust gap, UX preferences, privacy concerns
  - 4.1.3 ข้อสรุป requirements ที่ได้นำเข้าสู่ Phase 2

- 4.2 ผล Phase 2 — system development
  - 4.2.1 สถาปัตยกรรม (ย่อจาก `architecture.md`)
  - 4.2.2 ไทม์ไลน์ v1 → v2 → v2.1 (อ้าง `thesis-project-detail.md` §7.1-7.7)
  - 4.2.3 ตัวชี้วัดเชิงเทคนิค — จำนวนเอกสารที่ ingest, test coverage (266 tests), response latency (อ้าง raw logs ถ้ามี)

- 4.3 ผล Phase 3 — evaluation
  - 4.3.1 Chatbot evaluation (N=[TBD: 1 หรือ 3]) — ตารางสรุป 7 คำถาม × evaluator ที่ประเมินคุณภาพ + deploy-readiness (%)
  - 4.3.2 Admin portal task evaluation — success rate, avg time, avg difficulty (per task × evaluator)
  - 4.3.3 Post-evaluation interview — themes: time-saving, willingness to pay, pricing model preference, USP, feature requests
  - 4.3.4 TAM survey N=6 — Likert mean+SD ต่อ construct (Usefulness, Ease of Use, Credibility, Intention), NPS-like recommendation
  - 4.3.5 Qualitative responses (Q29-31 ของ survey)

- 4.4 ข้อค้นพบสำคัญ (Key findings) ที่สังเคราะห์ข้าม Phase

**Source:** `IS-Data/indepth-interview/transcript/*.txt`, `IS-Data/evaluation/project-eva/TIP RAG EVALUATION.xlsx`, `IS-Data/evaluation/post-evaluation-interview/transcript/*.txt`, `IS-related/CUTIP RAG Final (Responses).xlsx`

**ข้อควรระวัง R3/R5:** quote > 3 คำ ใส่ `"..."` + ระบุ transcript file + บรรทัด; N evaluator รอ user confirm; ตัวเลขทุกตัวจากไฟล์ข้อมูลเท่านั้น ห้ามประมาณ

### 4.6 บทที่ 5 การศึกษาความเป็นไปได้ของผลิตภัณฑ์เชิงธุรกิจ (~14-18 หน้า) ⭐ block by user input

- 5.1 Market analysis
  - 5.1.1 ขนาดตลาด — จำนวนมหาวิทยาลัย/คณะในไทย (WebSearch verify)
  - 5.1.2 Segmentation — ม.รัฐ/เอกชน, ระดับ ป.ตรี/โท/เอก
- 5.2 Value proposition
  - 5.2.1 Pain points ที่ระบบแก้ (จากบท 4.1.1)
  - 5.2.2 Unique selling propositions — 24/7, multi-tenant, Thai-first, Opus 4.7
- 5.3 Target customer
  - 5.3.1 Buying center — หัวหน้าหลักสูตร / รองคณบดี / คณบดี (อ้าง post-eva Q11 [TBD])
- 5.4 Competitive analysis — คู่แข่งในไทยและต่างประเทศ [TBD: user ให้ข้อมูลหรือ WebSearch]
- 5.5 Business model
  - 5.5.1 Revenue streams — subscription, setup fee, custom integration
  - 5.5.2 Pricing tiers — [TBD: ใส่ pricing จาก user]
- 5.6 Go-to-market strategy
- 5.7 SWOT analysis
- 5.8 ช่องทางจัดจำหน่าย/partnership

**Block by user input:** Q1-3 ใน unlock list (pricing tier, willingness to pay จาก post-eva, competitors)

### 4.7 บทที่ 6 การศึกษาความเป็นไปได้ทางการเงิน (~8-12 หน้า) ⭐ block by user input

- 6.1 โครงสร้างต้นทุน (Cost structure)
  - 6.1.1 Variable — LLM API (Opus 4.7, Haiku 4.5), embeddings (Cohere), reranking (Cohere), Pinecone
  - 6.1.2 Fixed — Cloud Run, Firestore, domain, maintenance
  - 6.1.3 Cost per tenant / per query — [TBD: ใส่จาก GCP billing]
- 6.2 โครงสร้างรายได้ (Revenue projection) — อ้าง pricing จาก §5.5.2
- 6.3 Initial investment [TBD: user ให้ตัวเลขเวลาพัฒนา + cost ที่ลงไปแล้ว]
- 6.4 Break-even analysis
  - 6.4.1 จำนวน tenants ที่ต้องมีเพื่อคืนทุน
  - 6.4.2 Timeline คืนทุน (months)
- 6.5 Sensitivity analysis — best / base / worst case
- 6.6 ข้อจำกัดของการวิเคราะห์การเงิน

**Block by user input:** Q4-5 ใน unlock list (monthly cost ปัจจุบัน, initial investment)

### 4.8 บทที่ 7 สรุปผลงานวิจัย อภิปราย และข้อเสนอแนะ (~8-10 หน้า)

- 7.1 สรุปผลการวิจัย (ตามคำถามวิจัยใน §1.2)
- 7.2 อภิปรายผล — เชื่อมโยงผลใน §4 กับวรรณกรรมใน §2
- 7.3 ข้อจำกัดของการศึกษา — N evaluator เล็ก, bias ผู้วิจัยเป็นนิสิต TIP เอง, เอกสาร CU-TIP เท่านั้น
- 7.4 ข้อเสนอแนะ
  - 7.4.1 เชิงวิชาการ — ทำ RAG eval benchmark ภาษาไทย
  - 7.4.2 เชิงเทคนิค — Multi-modal RAG (รูป/ตาราง/แผนที่), streaming response
  - 7.4.3 เชิงธุรกิจ — pilot ในหลักสูตร/คณะอื่น
- 7.5 ทิศทางการวิจัยในอนาคต

### 4.9 Back matter (~20+ หน้า)
- บรรณานุกรม (APA 7) — verified refs only
- ภาคผนวก ก: แบบสอบถาม TAM
- ภาคผนวก ข: ชุดคำถาม in-depth interview (staff + student)
- ภาคผนวก ค: ชุดคำถาม post-evaluation interview
- ภาคผนวก ง: Raw responses (anonymized) — selected excerpts
- ภาคผนวก จ: Evaluation task scenarios (admin portal)
- ประวัติผู้เขียน

## 5. Data source mapping

| บท | Primary source | Secondary source |
|---|---|---|
| 1 | IS proposal (`CU TIP Independent Study Proposal Template.pdf`), `thesis-project-detail.md` §1-3 | — |
| 2 | verified WebSearch/WebFetch papers (R2) | proposal §4-5 |
| 3 | proposal §6, question set docx ทั้ง 3 ไฟล์, `architecture.md` §2 | `thesis-project-detail.md` §7-19 |
| 4 | `IS-Data/indepth-interview/transcript/*.txt` (8 files), `IS-Data/evaluation/project-eva/TIP RAG EVALUATION.xlsx`, `IS-Data/evaluation/post-evaluation-interview/transcript/*.txt`, `IS-related/CUTIP RAG Final (Responses).xlsx` | `thesis-project-detail.md` §7.1-7.7 |
| 5 | User inputs (Q1-3) + WebSearch market data | `thesis-project-detail.md` §20-23 |
| 6 | User inputs (Q4-5) + GCP pricing page | — |
| 7 | บท 1-6 ของเล่มนี้เอง | — |

## 6. Schedule (3 วัน)

### D1 — อังคาร 2026-04-21 (วันนี้)
- [x] setup workspace (CLAUDE.md, AI_LOG.md, folders)
- [x] spec นี้ + commit
- [ ] ส่ง unlock Q ให้ user + รอตอบ
- [ ] เริ่มเขียน **บท 4** — 4.1 (interview findings)

### D2 — พุธ 2026-04-22
- [ ] จบบท 4 — 4.2, 4.3, 4.4
- [ ] Citation verification loop (~25 refs, 2-3 ชม., dispatch subagent ถ้าคุ้ม)
- [ ] เขียนบท 5 (ขึ้นกับ user input)
- [ ] เขียนบท 6 (ขึ้นกับ user input)

### D3 — พฤหัสฯ 2026-04-23
- [ ] เขียนบท 1-3 (derivative, เร็ว)
- [ ] เขียนบท 7 + บทคัดย่อ TH+EN + กิตติกรรม
- [ ] บรรณานุกรม + ภาคผนวก + ประวัติ
- [ ] R11 final sweep: [TBD:] + citation recheck + voice review
- [ ] pandoc export → `VIRIYA-IS.docx` (Sarabun, margin, TOC)

### D4 — ศุกร์ 2026-04-24 (ส่ง)
- [ ] user review + แก้เล็กน้อย + ส่ง

## 7. Unlock questions (D1 เย็นตอบ)

### บท 5
- **Q1.** Pricing tier เบื้องต้น — Starter / Pro / Enterprise แต่ละระดับเดือนละเท่าไหร่ + แตกต่างอย่างไร (จำนวนคำถาม, tenant, ฟีเจอร์)
- **Q2.** จาก post-eva interview Q11-12 — เจ้าหน้าที่ CUTIP บอกช่วงราคาที่ "คุ้ม" ไว้เท่าไหร่ + pricing model แบบไหน (เหมาจ่าย/ต่อหัวนิสิต/ต่อเอกสาร)
- **Q3.** Competitors / alternatives — มีเจ้าอื่นทำ RAG chatbot สำหรับอุดมศึกษาไทยมั้ย? ถ้าไม่รู้ → ระบุ "ให้ claude research ให้"

### บท 6
- **Q4.** Monthly cost ปัจจุบัน — GCP + Anthropic + Pinecone + Cohere รวมกี่บาท/เดือน (ต่อ tenant ถ้าแยกได้) — ส่ง screenshot billing หรือตัวเลขก็ได้
- **Q5.** Initial investment — คน-เดือนที่ใช้พัฒนา + cost ที่ลงไปแล้ว (กะคร่าวๆ)

## 8. Output format และ conventions

- Manuscript: Markdown ต่อบท ที่ `docs/is-book/manuscript/`
- Heading: `# บทที่ X ชื่อบท` / `## X.Y หัวข้อ` / `### X.Y.Z หัวข้อย่อย`
- Quote > 3 คำ: `> "คำพูดตรง..." (file: transcript.txt, บรรทัด NN)`
- Placeholder: `[TBD: ใส่...จาก <source>]`
- Citation in-text: `(Lewis et al., 2020)` หรือ `Lewis et al. (2020) ระบุว่า...`
- Reference file: `manuscript/references.md` — APA 7 verified only
- Final export: pandoc → `.docx` ที่ `docs/is-book/VIRIYA-IS.docx`

## 9. Commit convention

```
docs(is-book): <action> <scope>

ตัวอย่าง:
docs(is-book): init workspace + design spec
docs(is-book): draft ch4 4.1 interview findings
docs(is-book): verify refs for ch2 RAG section
docs(is-book): pandoc export to docx
```

User push เอง ตาม git-push preference

## 10. Success criteria

- เล่ม IS ครบ 7 บท + front/back matter ภาษาไทย
- ผ่านมาตรฐาน Chula typography (font, margin, APA 7)
- ทุก citation verified (R2) — zero hallucinated refs
- ทุก [TBD:] ถูก resolve ก่อนส่ง (R11)
- Voice ผ่าน akarawisut.com check (R7 side effect)
- AI_LOG.md ครบทุก session สำหรับ acknowledgement

## 11. Risks และ mitigations

| Risk | Mitigation |
|---|---|
| User ตอบ unlock Q ช้า → ch 5-6 block | เริ่ม ch 4 ก่อน, citation verify parallel |
| Citation verify ใช้เวลาเกินประมาณ | dispatch subagent คู่ขนาน, ลด ref จำนวนถ้าจำเป็น |
| N evaluator ยัง = 1 ถึงวัน submit | เขียน ch 4 แบบ N=1 เป็น case study, ยอมรับใน limitations (§7.3) |
| Pandoc Thai font / margin ไม่ตรง Chula template | D3 buffer สำหรับ manual fix ใน Word หลัง export |
| Voice ติด akarawisut flag | R5 rewrite ส่วนที่ติด, ไม่ใช่ dodge detector |
| N evaluator เพิ่มเป็น 3 หลังเขียนไปแล้ว | §4.3.1-4.3.2 ออกแบบเป็นตาราง scale ได้ — เพิ่มแถวได้ไม่ต้อง rewrite |

## 12. Out of scope

- ภาพถ่ายผู้ให้สัมภาษณ์ / วิดีโอ raw
- การทดสอบ security / penetration
- Full business plan (เอาแค่ความเป็นไปได้)
- Go-to-market execution plan detail
