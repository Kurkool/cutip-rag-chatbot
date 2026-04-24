# Session Handoff — IS Book Writing

Use this file to pick up work on a new session or computer.

## Status snapshot (as of 2026-04-25)

**Original deadline:** ศุกร์ 2026-04-24 — manuscript complete, now in iThesis submission phase.

### Done — entire manuscript + staging docx + supporting artifacts

| บท | สถานะ | ไฟล์ |
|---|---|---|
| 1 บทนำ | ✅ | `manuscript/ch01-introduction.md` |
| 2 ทบทวนวรรณกรรม | ✅ (+ §2.5.3 UTAUT) | `manuscript/ch02-literature-review.md` |
| 3 วิธีการดำเนินการวิจัย | ✅ (UTAUT methodology) | `manuscript/ch03-methodology.md` |
| 4 ผลการวิจัย | ✅ (§4.3.4 UTAUT N=6 interview) | `manuscript/ch04-results.md` |
| 5 ความเป็นไปได้เชิงธุรกิจ | ✅ (PESTEL + 5F + STP + 7Ps, pricing 6500/15000/32500) | `manuscript/ch05-business-feasibility.md` |
| 6 ความเป็นไปได้ทางการเงิน | ✅ (5yr + loan 1M@5%, NPV 4.25M, IRR 37%, MIRR 27.13%) | `manuscript/ch06-financial-feasibility.md` |
| 7 สรุปผล | ✅ (RQ3 + UTAUT/Venkatesh discussion) | `manuscript/ch07-conclusion.md` |
| front matter | ✅ (TH+EN abstract UTAUT) | `manuscript/frontmatter.md` |
| back matter | ✅ (ก UTAUT, ข in-depth, ค post-eva, ง-ฉ existing, ช Thematic Analysis, ซ Financial) | `manuscript/backmatter.md` |
| docx export | ✅ `VIRIYA-IS-staging.docx` (~11 MB) | `build_viriya_ithesis.py` |
| financial xlsx | ✅ (10 sheets, live PMT/NPV/IRR/MIRR formulas) | `build_financial_model.py` |
| thematic analysis xlsx | ✅ (6 sheets, 25 codes, 40 excerpts, 10 themes, Braun & Clarke 6-phase) | `build_thematic_analysis.py` |
| figures | ✅ 5 auto (matplotlib + Mermaid) + 6 user-captured | `figures/generated/` + `figures/user-captured/` |
| verified-refs.ris | ✅ 19 refs (+ Venkatesh 2003, MHESI, Grand View, NDESC, Botnoi, ZWIZ) | `manuscript/verified-refs.ris` |

### Currently pending (iThesis submission phase)

| Task | Blocker | Owner |
|---|---|---|
| iThesis cover/approval/abstract via add-in UI | user fills via form | user |
| iThesis committee list (blocked upload — `committeeList is not defined` error) | user fills | user |
| EndNote refs.ris import + Update Citations | user runs in Word | user |
| F9 refresh TOC + List of Figures + List of Tables | user runs in Word | user |
| Keywords TH/EN (proposed below, not yet added to frontmatter.md) | user confirms or modifies | user |
| Upload to iThesis system | cookie/auth issue (see gotcha below) | user |

## Proposed keywords (add to frontmatter.md abstract)

**คำสำคัญ:** Retrieval-Augmented Generation; ปัญญาประดิษฐ์เชิงตัวแทน (Agentic AI); แชทบอทให้บริการนิสิต; ทฤษฎี UTAUT; การวิเคราะห์ความเป็นไปได้ทางธุรกิจ

**Keywords:** Retrieval-Augmented Generation (RAG); Agentic AI Chatbot; Multi-tenant SaaS; UTAUT Framework; Business Feasibility Analysis

## Build pipeline (rebuild staging docx from manuscript .md)

```bash
cd cutip-rag-chatbot/
.venv/Scripts/python.exe docs/is-book/build_viriya_ithesis.py
# → docs/is-book/VIRIYA-IS-staging.docx
# Fallback VIRIYA-IS-staging-v2.docx if primary is locked in Word
```

Builder does: open `VIRIYA-iThesis-Template.docx` → force TH Sarabun New 16pt + centered Heading 1 + set black on Heading 1-9 (override template's Aptos + blue accent1) → inject chapters before บรรณานุกรม anchor → replace template appendix placeholders (iThesisIndex2) with backmatter content → apply Thai lang/layout tags on every run → remove คำอธิบายสัญลักษณ์ empty section → save.

## Staging docx — key formatting decisions baked in

- **TH Sarabun New 16pt** forced on Normal/List Paragraph/Heading 1-9 via `force_thai_font_on_style` (overrides Word 2024 Aptos theme).
- **Heading 1 centered + `pageBreakBefore`** — chapters + appendix label pages.
- **Italic removed from Heading 4/6/8** (template default).
- **Blue `accent1` (#0F4761) removed** from all heading levels — default black rendering.
- **Thai Distributed dropped** — root cause was `eastAsia="th-TH"` (CJK tag, wrong). Removed. Keep `w:val="th-TH"` + `w:bidi="th-TH"` only.
- **useAsianBreakRules** compat flag in `word/settings.xml` — preserves Thai grapheme clusters when breaking lines.
- **SEQ field complex form** (begin/separate/end + `w:dirty="true"` + document-level `updateFields=true`) — figure/table captions auto-number on F9 refresh.
- **Appendix headings**: each appendix heading is alone in its own section with `<w:sectPr vAlign="center" type="nextPage"/>` → centered both H+V on a divider page; a separator paragraph before each heading has `vAlign="top"` to prevent the preceding section from also being centered; `pageBreakBefore=false` override on appendix Heading 1 to avoid double page break.
- **Watermark** Chula logo from `background-img.jpg` added to all headers.

## Supporting xlsx artifacts

- `build_financial_model.py` → `viriya-financial-model.xlsx` — 10 sheets (Assumptions, Loan amort, Assets, SG&A, P&L, CashFlow, BalanceSheet, BreakEven, Sensitivity, Summary). All formulas live — change an assumption, all downstream sheets recompute. Base case: NPV 4.25M, IRR 37%, MIRR 27.13%, Payback 2.78 years.
- `build_thematic_analysis.py` → `viriya-thematic-analysis.xlsx` — 6 sheets (Overview, 12 Participants, 25-code Codebook (14 UTAUT + 11 inductive), 40 Excerpts, 10 Themes, Braun & Clarke 6-phase log). Appendix ช has a summary table referencing this xlsx.

## iThesis submission — gotchas

### Cookie/auth corruption (`URIError: URI malformed` in `getCookie`)

The iThesis Next Gen Word add-in stores its auth cookie in Office's WebView/IE cache. When the cookie becomes corrupted (partial write, truncated token, mismatched encoding), *every* add-in API call fails silently — `getCookie()` throws `URIError: URI malformed` on `decodeURIComponent`, cascading into `committeeList is not defined`, `Cannot read 'sort' of undefined`, etc. The "Upload complete" toast can lie — the underlying POST never reached the server because `getToken()` threw before the request was even built.

**Symptoms:** upload "completes" in add-in but nothing appears in the web portal; committee dropdown empty; no errors shown to user unless DevTools console is open.

**Fix (tried and verified pattern):**

```powershell
# Kill all Office
taskkill /F /IM WINWORD.EXE
taskkill /F /IM msoadfsb.exe
# Nuke caches (safe — all are recreated on next launch)
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Microsoft\Office\16.0\Wef"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Microsoft\Office\16.0\WebServiceCache"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Microsoft\Office\16.0\OfficeFileCache"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Microsoft\Windows\INetCache"
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Microsoft\Windows\INetCookies"
# EdgeWebView User Data sometimes doesn't exist — that's fine, skip
```

Then reopen Word → iThesis tab → fresh login to CU account.

If the error persists: open DevTools in the iThesis pane (F12 / right-click Inspect) → Application tab → Storage → Clear site data → reload pane.

### Upload ≠ Submit

"Upload" in the add-in sends the file as draft to the server. Document does NOT appear in the advisor's queue until user explicitly clicks **ส่งเล่ม / Submit for Approval** on the web portal (https://ithesis.grad.chula.ac.th). Check portal → My Thesis → status should be `Pending Advisor Review` after submit.

## Source data locations (read-only per R3)

```
IS-related/IS-Data/
├── indepth-interview/transcript/ (8 files: 4 staff + 3 student + 2 multi-part)
│   └── question-set/
├── evaluation/
│   ├── project-eva/VIRIYA RAG EVALUATION.xlsx (N=2 filled: ธารา + พี่แมน)
│   └── post-evaluation-interview/
│       ├── transcript/ (3 files: staff post-eva + 6 UTAUT student transcripts elsewhere)
│       └── post-eva-question-set/
└── [raw .m4a audio — cannot process directly]
```

## Anonymization codes (12 participants total)

| Code | Group | Program | Where |
|---|---|---|---|
| S-01 | Staff (ธารา) | TIP | ch4.1 + ch4.3 |
| S-02 | Staff (ศิมาพร) | HSM | ch4.1 |
| S-03 | Staff (พี่จิ๋ว/วรัญญา) | HSM | ch4.1 |
| S-04 | Staff (พี่แหวน) | วิทยาศาสตร์สิ่งแวดล้อม | ch4.1 |
| S-05 | Staff (พี่แมน) | TIP | ch4.3 (evaluator #2) |
| ST-01 | Student (จีน — มนทนา) | TIP | ch4.1 + ch4.3.4 UTAUT |
| ST-02 | Student (เอ๋ — พรทิพย์) | TIP | ch4.1 + ch4.3.4 UTAUT |
| ST-03 | Student (ปุ้ย — นัดนลี) | TIP | ch4.1 |
| ST-04 | Student (ดรีม) Business Analyst | TIP | ch4.3.4 UTAUT |
| ST-05 | Student (พี่แป้ง) วิศวกร | TIP | ch4.3.4 UTAUT |
| ST-06 | Student (พี่โม) | TIP | ch4.3.4 UTAUT |
| ST-07 | Student (พีท) ธุรกิจส่วนตัว | TIP | ch4.3.4 UTAUT |

## Verified refs (19 in verified-refs.ris)

Core academic (14): Lewis 2020, Davis 1989, Bezemer & Zaidman 2010, Creswell & Plano Clark 2018, Braun & Clarke 2006, Vaswani 2017, Karpukhin 2020, Gao 2024, Venkatesh & Davis 2000, Anthropic 2024, Nogueira & Cho 2019, Robertson & Zaragoza 2009, Labadze 2023, **Venkatesh 2003** (UTAUT).

Public market/industry refs for ch5 (5): MHESI (กระทรวงการอุดมศึกษาฯ 2566), Grand View Research 2567, NDESC (สำนักงานสภาพัฒนาการเศรษฐกิจฯ), Botnoi Group 2569, ZWIZ.AI 2569.

## How to restart on a new session/computer

1. **Read in order:**
   - `docs/is-book/CLAUDE.md` — R1-R11 hard rules (MUST follow)
   - `docs/is-book/AI_LOG.md` — session history (13+ sessions through 2026-04-25)
   - This file (SESSION-HANDOFF.md)
   - `cutip-rag-chatbot/CLAUDE.md` — project-level rules

2. **Verify environment:**
   ```bash
   cd cutip-rag-chatbot
   git status && git log --oneline -10
   .venv/Scripts/python.exe -c "import docx, openpyxl, matplotlib; print('ok')"
   ls docs/is-book/manuscript/        # 7 ch + front + back + .ris
   ls docs/is-book/figures/generated/ # 5 auto figures
   ls docs/is-book/figures/user-captured/ # 6 user screenshots (4.4-4.9)
   ```

3. **Rebuild staging docx:**
   ```bash
   .venv/Scripts/python.exe docs/is-book/build_viriya_ithesis.py
   ```

4. **If user needs to fix iThesis upload:** see "Cookie/auth corruption" gotcha above.

## Commit convention

```
docs(is-book): <action> <scope>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

User pushes commits themselves per `feedback_git_push.md` preference.

## Quick-start prompt for next session

> Manuscript + staging docx เสร็จแล้ว (all 7 chapters + front/back + appendices ก-ซ + 19 refs + financial xlsx + thematic xlsx + figures). เหลือ user submit เข้า iThesis — ถ้าเจอ `URIError: URI malformed` ใน add-in ให้ทำ cache nuke ตามที่ระบุใน SESSION-HANDOFF.md iThesis gotcha section. ถ้าจะแก้ manuscript ต่อ อ่าน `AI_LOG.md` session ล่าสุดก่อน.
