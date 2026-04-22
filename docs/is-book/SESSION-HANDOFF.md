# Session Handoff — IS Book Writing

Use this file to pick up work on a new session or computer.

## Status snapshot (as of 2026-04-22 end of D2)

**Deadline:** ศุกร์ 2026-04-24 (2 days left after D2)

### Done (~64 pages of body text + toolchain)

| บท | สถานะ | ขนาด | ไฟล์ |
|---|---|---|---|
| 1 บทนำ | ✅ | ~7 pages / 9.4K chars | `manuscript/ch01-introduction.md` |
| 2 ทบทวนวรรณกรรม | ✅ | ~11 pages / 14.2K chars | `manuscript/ch02-literature-review.md` |
| 3 วิธีการดำเนินการวิจัย | ✅ | ~11 pages / 15.4K chars | `manuscript/ch03-methodology.md` |
| 4 ผลการทำวิจัย (4.1 + 4.2 + 4.3) | ✅ | ~35 pages / 45.5K chars | `manuscript/ch04-results.md` |
| EndNote workflow | ✅ validated | — | `endnote-sample/` |
| docx rendering | ✅ validated (user confirmed) | — | `IS-book-thai-test.docx` |
| verified-refs.ris | ✅ 13 refs | — | `manuscript/verified-refs.ris` |

### Pending

| บท | สถานะ | ประมาณหน้า | Blocker |
|---|---|---|---|
| 5 ความเป็นไปได้เชิงธุรกิจ | ⏳ | 14-18 | **5 unlock Qs from user (see below)** |
| 6 ความเป็นไปได้ทางการเงิน | ⏳ | 8-12 | **Q4-5 from user (see below)** |
| 7 สรุปผลและข้อเสนอแนะ | ⏳ | 8-10 | needs ch 5-6 done |
| front matter | ⏳ | 10+ | ปก/อนุมัติ/บทคัดย่อ TH+EN/กิตติกรรม/สารบัญ |
| back matter | ⏳ | 20+ | บรรณานุกรม (EndNote auto) + ภาคผนวก + ประวัติ |
| docx export | ⏳ D3 last step | 1 | python-docx pipeline |

## 5 Unlock Questions — STILL PENDING USER

### บท 5 (business feasibility)

1. **Pricing tiers** — Starter/Pro/Enterprise rates + differentiation
   - Hint from ch4.3: S-05 (พี่แมน) prefers weighted-per-student, NOT flat rate. Can use as design starting point.
2. **Competitors** — Thai university chatbot vendors (Mindana? Skooldio? Botnoi? Zwiz AI?) or "Claude, please research"
3. **Market size** — number of Thai universities/programs (claude can WebSearch)

### บท 6 (financial feasibility)

4. **Monthly cost** — GCP + Anthropic + Pinecone + Cohere (per-tenant or total; ballpark OK)
5. **Initial investment** — person-months + sunk cost

**Partial answers already captured in ch4.3:**
- S-05 explicitly declined specific WTP rate → defers to ผอ.หลักสูตร
- Buying center confirmed: ผอ. หลักสูตร (all 4 staff unanimous in ch4.1)
- Time saved estimates: S-01 16-17 hr/week, S-05 ลดครึ่ง (4→2 hr/day)
- TIP TA outsource rate: ~19K/month (from ch4.1 Table 4.3)

## User also owes (non-blocking)

- **Screenshots:** Admin Portal (Dashboard, Chat Logs, Analytics, Upload) + LINE bot Q&A examples → `docs/is-book/figures/user-captured/`
- **N evaluator final:** xlsx has N=2 filled (ธารา + พี่แมน) + 1 template sheet — if a 3rd evaluator comes, tables scale easily

## How to restart on a new session/computer

1. **Read these first in order:**
   - `docs/is-book/CLAUDE.md` — R1-R11 hard rules (MUST follow)
   - `docs/is-book/AI_LOG.md` — 6 sessions logged so far
   - `docs/superpowers/specs/2026-04-21-is-book-design.md` — overall design
   - This file (SESSION-HANDOFF.md)
   - `cutip-rag-chatbot/CLAUDE.md` — project-level rules + tenant/toolchain notes

2. **Verify environment:**
   ```bash
   cd cutip-rag-chatbot
   git log --oneline -15   # expect commits through d0bf343 or later
   .venv/Scripts/python.exe -c "import docx; print('docx:', docx.__version__)"
   ls ../IS-related/IS-Data/indepth-interview/transcript/  # 9 files
   ls ../IS-related/IS-Data/evaluation/post-evaluation-interview/transcript/  # 3 files
   ```

3. **Re-confirm unlock status with user** before starting ch 5-6:
   - Q1 Pricing tiers, Q2 Competitors, Q3 Market size, Q4 Monthly cost, Q5 Initial investment

4. **If user gives green light to use research-backed defaults:**
   - WebSearch for Thai higher-ed chatbot market
   - Reference GCP pricing + Anthropic Claude API + Pinecone + Cohere rate cards
   - Flag every estimate with `[USER-VERIFY: rationale]` marker

## Source data locations

### Read-only raw (R3 — never modify)

```
IS-related/
├── CUTIP RAG Final (Responses).xlsx               ← TAM survey N=6
├── CU TIP IS Proposal Template...pdf
├── thesis_handbook.pdf                             ← Chula format spec
├── ตัวอย่าง IS พี่อู๋.pdf                         ← voice reference
├── Chula_Reference APA7thupdate_23สค64.pdf        ← APA 7 guide
└── IS-Data/
    ├── indepth-interview/
    │   ├── transcript/ (9 .txt)                    ← 4 staff + 3 student + 2 multi-part
    │   ├── question-set/ (2 .docx)
    │   └── raw-mp4a/ (9 .m4a audio — cannot process directly)
    └── evaluation/
        ├── project-eva/VIRIYA RAG EVALUATION.xlsx
        │   sheets: ธารา (filled), ธารา admin (filled), พี่แมน (filled), พี่แมน admin (filled), template 3, template 3
        └── post-evaluation-interview/
            ├── post-eva-question-set/ (1 .docx, 13 Qs)
            ├── raw-mp4a/ (3 .m4a)
            └── transcript/ (3 .txt — ธารา + พี่แมน part 1 + part 2)
```

### Thesis source docs (for ch1-3, 7)

```
cutip-rag-chatbot/docs/
├── thesis-project-detail.md    ← 1696 lines / 24 sections
├── architecture.md             ← 733 lines / 13 sections
├── logo/                       ← VIRIYA SVGs for cover
└── is-book/                    ← this workspace
    ├── CLAUDE.md
    ├── AI_LOG.md
    ├── SESSION-HANDOFF.md (this file)
    ├── endnote-sample/
    └── manuscript/
        ├── verified-refs.ris   (13 refs)
        ├── ch01-introduction.md
        ├── ch02-literature-review.md
        ├── ch03-methodology.md
        └── ch04-results.md
```

## Anonymization codes in use

| Code | Group | Program | Where used |
|---|---|---|---|
| S-01 | Staff (ธารา) | TIP (CUTIP) | ch4.1 in-depth + ch4.3 post-eva |
| S-02 | Staff (ศิมาพร) | HSM | ch4.1 only |
| S-03 | Staff (พี่จิ๋ว/วรัญญา) | HSM | ch4.1 only |
| S-04 | Staff (พี่แหวน) | วิทยาศาสตร์สิ่งแวดล้อม | ch4.1 only |
| **S-05** | Staff (พี่แมน) | TIP | **ch4.3 only — evaluator #2** |
| ST-01 | Student (จีน — Thai) | TIP | ch4.1 |
| ST-02 | Student (เอ๋) | TIP | ch4.1 |
| ST-03 | Student (ปุ้ย) | TIP | ch4.1 |

**All 3 students Thai. No international students interviewed.** Visa context in ch4.1 relates to HSM program demographic (via S-02), not interview cohort.

## Voice calibration reference

Match ตัวอย่าง IS พี่อู๋.pdf (2023 TIP graduate):
- "ผู้วิจัย" for first-person
- Thai term + `(English term)` for technical vocabulary
- Heading depth up to 4 levels (e.g. `3.2.3.2.1`)
- Citation inline `{Author, Year #RecNum}` (EndNote temp format)
- Mostly prose; bullets for explicit lists only
- Avoid AI patterns (CLAUDE.md R6): no "ในยุคปัจจุบัน", no em-dash flood, no triadic bullets per paragraph, no "โดยสรุปแล้ว", keep "อย่างไรก็ตาม"/"ดังนั้น"/"นอกจากนี้" minimal

## Commit convention

```
docs(is-book): <action> <scope>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

User pushes commits themselves per `feedback_git_push.md` preference.

## Commits through D2 (most recent first)

```
d0bf343 docs(is-book): draft ch2 literature review + 8 new verified refs
076ff77 docs(is-book): draft ch1 introduction (~7 pages)
eded484 docs(is-book): draft ch4.2 system development
85ae95f docs(is-book): draft ch4.3 evaluation results (N=2 eval + N=6 TAM)
430d8a9 docs(is-book): fix sample descriptions — no international students
9c5e865 docs(is-book): add SESSION-HANDOFF + log session end for handoff
87bead8 docs(is-book): draft ch4.1 in-depth interview findings + ch3 fix
ba84b5f docs(is-book): draft ch3 methodology + canonical refs.ris
f07a1c0 docs(is-book): validate EndNote workflow end-to-end
8560c15 docs(is-book): fix RIS reference types for APA 7 rendering
eb2c2a2 docs(is-book): add EndNote POC with 3 verified refs
afc4265 docs(is-book): init workspace + design spec for IS thesis
```

## Quick-start prompt for next session

> อ่าน `docs/is-book/SESSION-HANDOFF.md` + `AI_LOG.md` ก่อน แล้วเริ่ม — เสร็จถึง ch1-4 แล้ว 64 หน้า รอ user ตอบ 5 unlock Qs สำหรับ ch5-6 ถ้ายังไม่ตอบให้ถามก่อน หรือถ้า user สั่งให้ใช้ research-backed defaults ก็ลุยได้เลย (mark ทุกตัวเลขด้วย `[USER-VERIFY:]`)
