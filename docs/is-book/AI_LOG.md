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

## 2026-04-25 (session 20 — appendix headings centered + iThesis cache nuke)
- Task: code, other (iThesis troubleshoot)
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/build_viriya_ithesis.py` — `create_heading_para` now returns list; appendix level-2 case emits [separator_para with sectPr vAlign=top, heading_para with sectPr vAlign=center]. New helper `_clone_sectpr_base(doc, v_align)` deepcopies body final sectPr (pgSz/pgMar/cols/docGrid) + inserts nextPage type + vAlign. `pageBreakBefore=false` override on appendix Heading 1 prevents double break (section break already handled page boundary).
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-staging.docx` — rebuilt, 8 appendices × 2 sectPrs = 16 new vAlign sectPrs verified in document.xml.
- Output verified: each appendix ก-ซ heading renders on own page, centered horizontally (Heading 1 style) + vertically (section vAlign=center), with soft break splitting "ภาคผนวก X" and title onto 2 lines; body content starts on next page.
- iThesis upload troubleshooting (off-manuscript):
  - Diagnosed `URIError: URI malformed` in `getCookie` → cookie corruption; cascade causes `committeeList is not defined` + `Cannot read 'sort' of undefined` + silent upload failure (add-in UI shows "complete" but POST never reaches server because `getToken()` throws).
  - Nuked Office/IE/WebView caches on this machine: Wef, WebServiceCache, OfficeFileCache, BackstageInAppNavCache, MruServiceCache, SmartLookupCache, ResourceInfoCache, DocumentActivityQueue, INetCache, INetCookies — ~22 MB total. WebCache locked by Windows Search service (left partial).
  - EdgeWebView\User Data path doesn't exist on this machine (runtime installed but user data at different location). Not a blocker.
  - Procedure captured in SESSION-HANDOFF.md "Cookie/auth corruption" gotcha section + memory feedback file for future reuse.
- Keywords proposed (not yet added to frontmatter.md — awaiting user confirmation):
  - TH: Retrieval-Augmented Generation; ปัญญาประดิษฐ์เชิงตัวแทน (Agentic AI); แชทบอทให้บริการนิสิต; ทฤษฎี UTAUT; การวิเคราะห์ความเป็นไปได้ทางธุรกิจ
  - EN: Retrieval-Augmented Generation (RAG); Agentic AI Chatbot; Multi-tenant SaaS; UTAUT Framework; Business Feasibility Analysis
- Notes / decisions:
  - SESSION-HANDOFF.md rewritten for 2026-04-25 state — covers entire manuscript done, staging docx formatting decisions, iThesis submission gotchas, keyword proposal, restart guide.
  - EndNote import steps + Update Citations procedure reiterated (RIS Reference Manager filter, UTF-8 encoding, APA 7th style).

---

## 2026-04-24 (session 19 — ch6 expanded to match พี่อู๋ structure + xlsx revised)
- Task: draft, code
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch06-financial-feasibility.md` (rewrote — 8 sections → 13, +5 new matching อู๋'s TIP IS 2566)
  - `cutip-rag-chatbot/docs/is-book/build_financial_model.py` (5 sheets → 9)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-Financial-Model.xlsx` (rebuilt 20K)
- New ch6 sections:
  - §6.1 สินทรัพย์ที่ใช้ในการประกอบธุรกิจ (asset list + depreciation schedule)
  - §6.2 สมมติฐานการเงิน (centralized)
  - §6.5 ประมาณการค่าใช้จ่ายในการขายและการบริหาร (SG&A breakdown)
  - §6.7 งบแสดงฐานะทางการเงิน (Balance Sheet 3-year)
  - §6.12 บทสรุปทางการเงิน (KPI summary)
- Kept from original: Break-even + Sensitivity (not in อู๋'s but adds value)
- xlsx additions: Assets, SG&A, BalanceSheet, Summary sheets. Sheet order follows ch6 flow. Cross-sheet formulas: Summary → BreakEven/P&L/CF/Assets; BalanceSheet → CashFlow/P&L.
- Also: removed 80 transcript-citations `(ST-NN, line NN)` / `(S-NN, post-eva line NN)` from ch4 + ch5 (79 + 1) per user request. No double-space or orphan parenthesis left.

---

## 2026-04-24 (session 18 — Heading blue color fix + size 16 + Chula watermark)
- Task: code
- Files touched: `build_viriya_ithesis.py`, `VIRIYA-IS-staging.docx`
- Blue heading fix: iThesis template sets `<w:color w:val="0F4761" w:themeColor="accent1" w:themeShade="BF"/>` on Heading 1-9. That's Word 2024's default Office theme accent1 = dark teal. Fixed by removing `<w:color>` element from rPr during `force_thai_font_on_style` — headings fall back to auto (black).
- Heading uniform size + bold: all Heading 1-9 now TH Sarabun New 16pt bold (was 20/16/14pt with no explicit bold). Visual hierarchy via bold instead of size. `force_thai_font_on_style` gained `bold=True` param that adds `<w:b/>` + `<w:bCs/>`.
- Chula watermark: added `add_chula_watermark()` that inserts `background-img.jpg` (111K, Chula emblem seal) into section 0 header as behind-text anchored drawing. Only section 0 needed — other 16 sections inherit via header-linking (all `is_linked_to_previous=True`).
  - Technique: `run.add_picture()` creates inline → rewrite `<wp:inline>` to `<wp:anchor behindDoc="1"` via lxml. `positionH/positionV=center relativeFrom=page` centers watermark on every page, `wrapNone` lets body text overlay.
  - Width 4 inches; image relationship handled by python-docx.
  - File size 622K → 667K.

---

## 2026-04-24 (session 17 — Revert Thai Distributed + enable SEQ fields for TOC auto-population)
- Task: code
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/build_viriya_ithesis.py` (removed `set_thai_distribute()` calls from create_*_para; added `create_caption_para()` that emits SEQ field; updated `create_figure_paragraphs`; added table-caption detection `"ตารางที่ X.Y ..."` in markdown parser)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-staging.docx` (rebuilt — 5 figure SEQ + 23 table SEQ fields)
- Rationale: (1) Thai distributed alignment caused visual issues; revert to default left-justified body text. (2) iThesis template has 3 TOC fields pre-built: main (TOC \o "1-3"), tables (TOC \c "ตารางที่"), figures (TOC \c "ภาพที่"). The `\c` switch requires SEQ fields with matching identifier — added them.
- Caption implementation:
  - `create_caption_para(doc, label, title)` emits `<w:p>` with: run "label ", `<w:fldSimple w:instr=" SEQ {label} \* ARABIC ">`, run " title"
  - Figure captions: `create_figure_paragraphs` calls `create_caption_para("ภาพที่", caption)`
  - Table captions: regex `^ตารางที่\s+[\d.]+\s+(.+)$` in markdown parser → extracts title → `create_caption_para("ตารางที่", title)`
- On F9 refresh in Word: SEQ fields auto-number globally (ภาพที่ 1..5, ตารางที่ 1..23). User loses the chapter-based hardcoded "2.1 / 4.1" numbering from markdown — this is the tradeoff for auto-TOC. Chapter-based would need STYLEREF + SEQ reset (more complex).
- User workflow post-build: open docx → F9 on main TOC → F9 on สารบัญตาราง → F9 on สารบัญรูปภาพ

---

## 2026-04-24 (session 16 — Auto-format body to TH Sarabun 16pt + Thai Distributed)
- Task: code
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/build_viriya_ithesis.py` (+size_pt param to `force_thai_font_on_style`; +`set_thai_distribute()` helper; +`_ensure_pPr()`; call inline on create_normal/bullet/number_para)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-staging.docx` (rebuilt)
- Rationale: User frustrated with manually setting font+size+alignment per paragraph in Word. Auto-apply Chula academic standard so no manual formatting needed.
- Applied:
  - Normal + List Paragraph: TH Sarabun New 16pt via style rPr (`w:sz val=32, w:szCs val=32`)
  - Body + bullet + numbered paragraphs: `w:jc val=thaiDistribute` inline (via `set_thai_distribute`)
  - Headings 1-9: font forced to TH Sarabun New, size kept from iThesis template default
  - Table cells: inherit Normal 16pt, alignment left (no inline jc — thaiDistribute in narrow cells splits 2-3 words weirdly)
  - Template paragraphs (cover, approval, TOC, abstract): not touched — iThesis controls those
- Verify: 429 of 644 paragraphs in docx have thaiDistribute alignment; Normal style rPr shows sz=32 (16pt) correctly

---

## 2026-04-24 (session 15 — Rewrite ch4 quotes to summary)
- Task: polish, paraphrase
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch04-results.md` (converted 50+ direct verbatim quotes to paraphrased summary)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-staging.docx` (rebuilt 620K)
- Rationale: User wanted summarized/paraphrased writing instead of verbatim quotes pasted directly from transcripts. More academic + cleaner reading.
- Scope: 4.1.1 (staff), 4.1.2 (students), 4.3.1 (chatbot eval), 4.3.2 (admin portal), 4.3.3 (staff post-eva), 4.3.4 (UTAUT student interview)
- Pattern applied: keep `(S-XX, line XX)` / `(ST-XX, post-eva line XX)` citations for traceability; rephrase quoted text into indirect speech ("ผู้ให้สัมภาษณ์ S-XX ระบุว่า..."); preserve facts/numbers/reasoning exactly
- R3 (raw data integrity) upheld: source transcripts untouched; only manuscript body paraphrased
- R5 (deep paraphrase): restructured sentence-level, not just swapping a few words
- 4 remaining quotes are acceptable: proper nouns ("Principles of Innovation", "อาคารจามจุรี 10") or brief emphasis words ("ส่วนเสริม", "CU TIP Assistant")

---

## 2026-04-24 (session 14 — Migrate fig 3.2 + 4.2 to Mermaid)
- Task: code, refactor
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/figures/mermaid/fig_3_2_system_architecture.mmd` (new)
  - `cutip-rag-chatbot/docs/is-book/figures/mermaid/fig_4_2_detailed_architecture.mmd` (new)
  - `cutip-rag-chatbot/docs/is-book/build_figures.py` (+render_mermaid() via npx, removed matplotlib fig_3_2/4_2)
  - `cutip-rag-chatbot/docs/is-book/figures/generated/fig_3_2_system_architecture.png` (re-rendered via mermaid)
  - `cutip-rag-chatbot/docs/is-book/figures/generated/fig_4_2_detailed_architecture.png` (re-rendered via mermaid)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-staging.docx` (rebuilt 622K)
- Rationale: User complained matplotlib diagrams had arrows crossing through boxes. Mermaid uses dagre layout engine → auto-orthogonal routing → no crossings.
- Render pipeline: `npx -y @mermaid-js/mermaid-cli` (one-time download, no global install). Timeout 120s, shell=True on Windows.
- Color palette preserved: yellow=user/channels, blue=app/services, green=data, grey=external. Subgraphs for layers with labels.
- fig 3.2: 3-layer (User/App/Data) + External Services in subgraph
- fig 4.2: 4 subgraphs (Channels / Cloud Run / Data Stores / External Services)

---

## 2026-04-24 (session 13 — Generate 5 figure PNGs + embed in docx)
- Task: code, build
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/build_figures.py` (new — matplotlib figure generator)
  - `cutip-rag-chatbot/docs/is-book/figures/generated/fig_2_1_conceptual_framework.png`
  - `cutip-rag-chatbot/docs/is-book/figures/generated/fig_3_1_methodology_phases.png`
  - `cutip-rag-chatbot/docs/is-book/figures/generated/fig_3_2_system_architecture.png`
  - `cutip-rag-chatbot/docs/is-book/figures/generated/fig_4_2_detailed_architecture.png`
  - `cutip-rag-chatbot/docs/is-book/figures/generated/fig_4_3_evolution_timeline.png`
  - `cutip-rag-chatbot/docs/is-book/build_viriya_ithesis.py` (+FIGURE_MAP + create_figure_paragraphs + regex hook in parser)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-staging.docx` (rebuilt 685K, +5 inline images)
- Thai rendering via matplotlib `FontProperties(family='TH Sarabun New')`. Used ascii arrows (->) instead of Unicode → because glyph 8594 missing from TH Sarabun New.
- Figures render at 180 dpi, 6 inches wide in docx (Inches(6.0)), centered + italic caption below
- UI screenshots (Admin Portal + LINE bot) still user-owed — those go in `figures/user-captured/`
- Installed matplotlib 3.10.8 + contourpy/cycler/kiwisolver into `.venv/`

---

## 2026-04-24 (session 12 — Financial model xlsx)
- Task: code, build
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/build_financial_model.py` (new — openpyxl builder)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-Financial-Model.xlsx` (new — 14K, 5 sheets with live Excel formulas)
- Sheets: Assumptions (yellow input cells), P&L 3-yr, CashFlow 3-yr, BreakEven, Sensitivity (worst/base/best)
- All P&L / Cash Flow / Break-even / Sensitivity cells are formulas referencing Assumptions — user edits yellow cells → everything recalculates automatically
- Verification: base-case formulas match ch6 table 6.7 within ~222 THB rounding error (due to Cohere Embed 0.42 THB swallowed in ch6's "~2,580")
- Tenant averaging uses start + growth*6.5 (mid-year) not simple (start+end)/2 — matches ch6 convention (Y1=13, Y2=37, Y3=54.5)
- Tax uses MAX(0, EBT*rate) to avoid negative tax when EBT<0
- Thai rendering: TH Sarabun New 14pt on all cells; header 16pt bold

---

## 2026-04-24 (session 11 — TAM → UTAUT migration for student evaluation)
- Task: draft, rewrite, export
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/verified-refs.ris` (+Venkatesh 2003 UTAUT as RecNum 14 → 14 total refs)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch01-introduction.md` (RQ3, Obj 4, glossary +UTAUT)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch02-literature-review.md` (new §2.5.3 UTAUT, updated 2.7 conceptual framework)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch03-methodology.md` (3.2.3.1 / 3.2.3.3 / 3.2.3.4 — rewrote student eval as UTAUT interview; §3.2.3.2.3 data collection)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch04-results.md` (§4.3.4 fully rewritten as N=6 UTAUT in-depth interview with PE/EE/SI/FC/BI constructs; §4.3.5 synthesis updated)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch05-business-feasibility.md` (lines 45, 69, 176 — adoption signals now qualitative UTAUT not TAM mean scores)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch07-conclusion.md` (§7.1 RQ3 answer, §7.2.1 discussion citing Venkatesh 2003, §7.3 limitations, §7.5 future work)
  - `cutip-rag-chatbot/docs/is-book/manuscript/frontmatter.md` (TH + EN abstract rewritten; acknowledgements "ตอบแบบสอบถาม" → "สัมภาษณ์เชิงลึกทั้งก่อนและหลัง"; TOC appendix ก renamed)
  - `cutip-rag-chatbot/docs/is-book/manuscript/backmatter.md` (Appendix ก fully replaced: 31-item TAM Likert questionnaire → 18-question UTAUT interview guide in 4 parts + rationale note for qualitative UTAUT)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-staging.docx` (rebuilt 132K)
- Rationale: post-evaluation Google Form response file (CUTIP RAG Final (Responses).xlsx) only had 6 respondents. N=6 is too small for quantitative TAM (cannot run inferential statistics, Likert means unreliable). User switched to qualitative UTAUT in-depth interview approach — captures depth + rationale per participant, matches Braun & Clarke 2006 thematic analysis methodology already in use for Phase 1 interviews. UTAUT chosen over base TAM because it covers Social Influence + Facilitating Conditions (relevant in student peer/senior context + need for staff escalation when bot can't answer).
- References verified: Venkatesh, V., Morris, M.G., Davis, G.B., & Davis, F.D. (2003). User acceptance of information technology: Toward a unified view. MIS Quarterly, 27(3), 425-478. https://doi.org/10.2307/30036540
- Notes / decisions:
  - UTAUT deductive coding: all 5 constructs (PE, EE, SI, FC, BI) + moderator age/gender/experience
  - 18 interview questions (part 1: background 3Q, part 2: overall bot impression 4Q, part 3: UTAUT 8Q, part 4: closing 3Q)
  - 6 participants: ST-01 จีน, ST-02 เอ๋, ST-04 ดรีม, ST-05 พี่แป้ง, ST-06 พี่โม, ST-07 พีท (all Thai TIP students)
  - Adjacent appendix ค (staff interview) unchanged — that's a separate N=2 evaluation
  - TAM references retained in ch02 §2.5.1-2.5.2 (literature review context) and ch07 §7.2.1 (citing Davis 1989 as origin of theory that UTAUT extends)
- [TBD:] markers remaining: ST-04/05/07 occupation details (user must fill from raw data)

---

## 2026-04-23 (session 10 — TIP-aligned framework expansion)
- Task: draft (add standard TIP-expected frameworks to ch5 + ch6)
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch05-business-feasibility.md` (+PESTEL, Five Forces, STP, 7Ps — now 25K chars, 11 sections)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch06-financial-feasibility.md` (+P&L 3-year, Cash Flow 3-year — now 16K chars, 8 sections)
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch01-introduction.md` (session earlier: added 1.5 methodology brief)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-ithesis.docx` (rebuilt 127K)
- Rationale: comparison with พี่อู๋'s TIP 2566 example IS revealed 6 gaps in ch5 (4 marketing frameworks) + ch6 (2 financial statements). User chose option A = add all.
- Ch 5 additions:
  - 5.8 PESTEL (6 factors) — macro environment analysis
  - 5.9 Porter's Five Forces — industry competition analysis with 5-row table
  - 5.10 STP Marketing (3 sub-sections: Segmentation, Targeting niche=graduate programs, Positioning statement)
  - 5.11 Marketing Mix 7Ps for SaaS (Product/Price/Place/Promotion/People/Process/Physical Evidence)
- Ch 6 additions:
  - 6.6 งบกำไรขาดทุน 3 ปี — full P&L table with revenue/COGS/gross profit/operating expenses/depreciation/tax/net profit for Y1-Y3. Shows break-even Y1 + 27% net margin Y2 + 30% Y3.
  - 6.7 งบกระแสเงินสด 3 ปี — cash flow from operations/investing/financing activities. Initial investment ฿400K + ฿300K system dev, reaches ฿3.76M cash by end Y3.
  - 6.8 ข้อจำกัด (was 6.6, renumbered)
- Assumptions in P&L:
  - Tenant growth 2/month Y1-Y2, slowing to 1/month Y3 (base case)
  - Weighted avg revenue ฿11,650/tenant/mo
  - Variable cost ฿2,580/tenant/mo
  - Personnel ฿1.44M Y1 / ฿1.8M Y2 / ฿2.4M Y3
  - Corporate tax 20%
  - 3-year depreciation of initial investment
- All new financial numbers tagged [USER-VERIFY:]
- Total [USER-VERIFY:] markers now: ch5=19, ch6=16 (35 total across ch5-6)

---

## 2026-04-23 (session 9 — iThesis Next Gen integration)
- Task: other (format integration)
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/build_viriya_ithesis.py` (new — iThesis template-based export pipeline)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS-ithesis.docx` (new — 119K bytes)
- Source: `docs/is-book/VIRIYA-iThesis.docx` (blank iThesis Next Gen template generated by user via iThesis add-in)
- Template inspection findings:
  - 17 sections pre-defined (cover TH/EN, approval, abstracts TH/EN, ack, TOC, LOT, LOF, abbreviations, [empty chapter placeholder section], bibliography, appendix ก/ข/ค, vita)
  - 26 iThesis-specific paragraph styles (cover thesis name, approval header, abstract content, TOC style, Index_1/2, mendeley bibliography, vita title/content)
  - Margins L=1.5", R=1", T=1.5", B=1" (Chula-compliant)
  - TOC pre-populated with placeholder front/back items but NO chapter entries — chapters added dynamically will auto-populate TOC when Word refreshes
- Script approach:
  - Open iThesis template as base via Document()
  - Locate insertion point (the <w:p> containing "บรรณานุกรม" in iThesisIndex1 style)
  - Parse each ch01-ch07 markdown file
  - Create OxmlElement for each chunk (Heading 1-4, Normal paragraph, bullet/number list as "List Paragraph" style, Grid tables)
  - Insert all chapter elements BEFORE bibliography paragraph
  - Preserve all iThesis template sections, styles, and field codes
- Output: 7 Heading 1 (chapters) + 37 Heading 2 + 60 Heading 3 + 24 Heading 4 + 29 tables
- Gotchas fixed:
  - "List Number"/"List Bullet" styles not in iThesis template → use "List Paragraph" with manual "1. " / "• " prefix
  - "List Paragraph" available, using for both bullet and numbered lists
- User actions remaining in Word:
  1. Open VIRIYA-IS-ithesis.docx in Word — iThesis add-in should auto-detect
  2. Fill cover / approval / abstract TH+EN / กิตติกรรม via iThesis UI form (fields are linked to student metadata)
  3. Press F9 on TOC to refresh (all 7 chapters will auto-populate with page numbers)
  4. Manually paste backmatter.md content: bibliography + appendix ก/ข/ค + ประวัติผู้เขียน
  5. Import verified-refs.ris to EndNote → Update Citations and Bibliography in Word

---

## 2026-04-23 (session 8 — ch7 + front/back matter + docx export — MANUSCRIPT COMPLETE)
- Task: draft, polish, export
- Files touched:
  - `cutip-rag-chatbot/docs/is-book/manuscript/ch07-conclusion.md` (new ~10 pages)
  - `cutip-rag-chatbot/docs/is-book/manuscript/frontmatter.md` (new — cover TH/EN, approval page, abstracts TH+EN, acknowledgements with AI use disclosure, TOC skeleton)
  - `cutip-rag-chatbot/docs/is-book/manuscript/backmatter.md` (new — bibliography manual listing with EndNote fallback, 6 appendices: TAM questionnaire, interview questions, post-eva guide, knowledge base docs, eval test set, AI usage statement + biography placeholder)
  - `cutip-rag-chatbot/docs/is-book/build_viriya_docx.py` (new — python-docx pipeline)
  - `cutip-rag-chatbot/docs/is-book/VIRIYA-IS.docx` (new — 121K bytes, 748 paragraphs, 23 tables, Chula margins L=1.5"/RTB=1", TH Sarabun New 16pt + th-TH lang tag throughout)
- Ch 7 structure: 7.1 summary per RQ / 7.2 discussion linking to lit review + Thai context / 7.3 limitations (sample size, scope, researcher bias, data currency, financial estimates) / 7.4 recommendations (academic, technical, business) / 7.5 future research (4 directions)
- Export script features:
  - Converts markdown headings (# through ######) to Word headings with size 22/18/16/16/16
  - Page break before each chapter (detected by first `# ` in chapter files)
  - Markdown tables → Word tables with grid style
  - Bullet/numbered lists preserved
  - Bold (`**`) + inline code (`` ` ``) handled
  - TH Sarabun New applied at all font fields (ascii/hAnsi/cs/eastAsia) + szCs + lang bidi
  - Center-aligned top-level headings
- Acknowledgements explicitly disclose Claude Opus 4.7 usage per CLAUDE.md R10 + Appendix ฉ details the rules and scope (R1 no fabrication, R2 verified citations, R3 raw data integrity)
- Bibliography: listed manually in backmatter.md for preview; user imports verified-refs.ris to EndNote library and runs Update Citations and Bibliography in Word to replace manual list with properly-formatted APA 7
- **MANUSCRIPT STATUS: COMPLETE — all chapters drafted, exported to docx, ready for user review + EndNote bibliography step + final polish**
- Total pages estimate: ~124 (front 10 + ch1-7 93 + back 21)

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
