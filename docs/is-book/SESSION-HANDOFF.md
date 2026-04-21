# Session Handoff — IS Book Writing

Use this file to pick up work on a new session or computer.

## Status snapshot (as of 2026-04-21 end of D1)

**Deadline:** ศุกร์ 2026-04-24 (3 days from start)
**Approach:** B (risk-first) with revised order accounting for chapter dependencies

### Done

- [x] Design spec — `docs/superpowers/specs/2026-04-21-is-book-design.md`
- [x] Workspace + rules (CLAUDE.md) + log (AI_LOG.md)
- [x] Toolchain validated: python-docx Thai rendering + EndNote workflow end-to-end
- [x] Canonical RIS with 5 verified refs (`manuscript/verified-refs.ris`)
- [x] **ch03-methodology.md** — ~10-14 pages, full draft
- [x] **ch04-results.md §4.1** — in-depth interview findings, ~8-10 pages, anonymized

### Next up (priority order)

| # | Task | Blocker | Source material |
|---|---|---|---|
| 1 | ch4 §4.2 system development | None — derivative | `thesis-project-detail.md` §4, §7; `architecture.md` §2-5, §11 |
| 2 | ch4 §4.3 evaluation results | Partial — N=1 evaluator (user recruiting more); post-eva transcript available | `IS-Data/evaluation/project-eva/TIP RAG EVALUATION.xlsx`, `post-evaluation-interview/transcript/เจ้าหน้าที่_Post_Eva_CUTIP.txt`, `../CUTIP RAG Final (Responses).xlsx` (N=6 TAM) |
| 3 | ch1 introduction | None — derivative | `CU TIP Independent Study Proposal Template...pdf`, `thesis-project-detail.md` §1-3 |
| 4 | ch2 literature review | Needs ref verification via WebSearch (~2-3 hr, dispatch subagent if tight) | Verified: Lewis/Davis/Bezemer/Creswell/Braun. Still need: Anthropic Claude ref, Cohere embed ref, Pinecone whitepaper, TAM extensions, chatbot education (Wang 2023), NPS/recommendation refs |
| 5 | ch5 business feasibility | **Waiting on user** (Q1-3 unlock) | User input + `thesis-project-detail.md` §20-23 |
| 6 | ch6 financial feasibility | **Waiting on user** (Q4-5 unlock) | User input + GCP pricing |
| 7 | ch7 + front/back matter | After ch1-6 | ch1-6 content + `thesis_handbook.pdf` format guide |
| 8 | python-docx export → `VIRIYA-IS.docx` | Last step D3 | Same pipeline as `IS-book-thai-test.docx` which user confirmed OK |

## How to restart on a new session/computer

1. **Read these first in order:**
   - `docs/is-book/CLAUDE.md` — R1-R11 hard rules (mandatory, MUST follow)
   - `docs/is-book/AI_LOG.md` — what prior sessions did
   - `docs/superpowers/specs/2026-04-21-is-book-design.md` — overall design
   - This file (`SESSION-HANDOFF.md`)

2. **Verify environment:**
   ```bash
   # from cutip-rag-chatbot/ dir
   .venv/Scripts/python.exe -c "import docx; print(docx.__version__)"
   git log --oneline -10   # expect commits ending around 87bead8 or later
   git status --short      # should be clean or have WIP files only
   ```

3. **Re-confirm unlock status with user (do NOT start ch5-6 without):**
   - Q1 Pricing tiers
   - Q2 WTP from post-eva Q11-12
   - Q3 Competitors
   - Q4 Monthly cost
   - Q5 Initial investment

4. **Ask user about:**
   - N evaluator final count (currently 1; user recruiting more)
   - Screenshots for admin portal + LINE bot
   - Any ch3/ch4.1 feedback to address before continuing

## Source data locations

### Read-only raw (R3 — never modify)

```
../IS-related/
├── CUTIP RAG Final (Responses).xlsx         ← TAM survey N=6
├── CU TIP Independent Study Proposal Template - Kurkool Ussawadisayangkool 6780016820.pdf
├── thesis_handbook.pdf                       ← Chula format spec (56 pages)
├── ตัวอย่าง IS พี่อู๋.pdf                    ← Voice reference (139 pages, 7 chapters)
├── Chula_Reference APA7thupdate_23สค64.pdf  ← APA 7 guide
└── IS-Data/
    ├── indepth-interview/
    │   ├── transcript/                      ← 8 .txt (read individually; CUTIP = 248 lines, too big for one Read — offset/limit)
    │   ├── question-set/                    ← 2 .docx (staff + student Q guides)
    │   └── raw-mp4a/                        ← audio (claude cannot process directly)
    └── evaluation/
        ├── project-eva/TIP RAG EVALUATION.xlsx  ← 6 sheets: chatbot-eval 1/2/3 + admin-portal-task 1/2/3; only sheet 1 filled
        └── post-evaluation-interview/
            ├── post-eva-question-set/       ← 1 .docx with 13 Qs
            ├── raw-mp4a/                    ← audio
            └── transcript/                  ← 1 .txt (post-eva CUTIP staff)
```

### Thesis source docs (for ch1-3, 7)

```
cutip-rag-chatbot/docs/
├── thesis-project-detail.md    ← 1696 lines, 24 sections — primary source for ch1, ch4.2, ch7
├── architecture.md             ← 733 lines, 13 sections — primary source for ch3.2.2, ch4.2
├── logo/                       ← VIRIYA SVGs for cover
└── is-book/                    ← this workspace
```

## Voice calibration reference

Match ตัวอย่าง IS พี่อู๋.pdf (2023 TIP graduate):
- "ผู้วิจัย" for first-person
- Thai term + `(English term)` for technical vocabulary
- Heading depth up to 4 levels (e.g. `3.2.3.2.1`)
- Citation inline `(Author, Year)` or `Author (Year) ระบุว่า...`
- Mostly prose; bullets for explicit lists only
- Avoid AI patterns (see CLAUDE.md R6): no "ในยุคปัจจุบัน", no em-dash flood, no triadic bullets per paragraph, no "โดยสรุปแล้ว"

## Commit convention

```
docs(is-book): <action> <scope>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

User pushes commits themselves per `feedback_git_push.md` preference.

## Quick-start prompt for next session

> อ่าน docs/is-book/SESSION-HANDOFF.md และ AI_LOG.md ก่อน แล้วเริ่มจาก task "Next up" ถัดไป — ตอนนี้ถึงไหนแล้ว? ได้ data สำหรับ ch4.3 เพิ่มมั้ย? หรือตอบ 5 unlock Qs สำหรับ ch5-6 ได้รึยัง?
