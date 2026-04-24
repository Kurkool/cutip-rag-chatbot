"""Generate 5 diagram PNGs for VIRIYA IS thesis book.

Outputs to docs/is-book/figures/generated/ — referenced by ch02/ch03/ch04 markdown.

Figures:
  fig_2_1_conceptual_framework.png      — matplotlib (box layout)
  fig_3_1_methodology_phases.png        — matplotlib (horizontal phases)
  fig_3_2_system_architecture.png       — mermaid (auto-routed arrows)
  fig_4_2_detailed_architecture.png     — mermaid (auto-routed arrows)
  fig_4_3_evolution_timeline.png        — matplotlib (timeline)

Mermaid rendering via npx @mermaid-js/mermaid-cli (must have node/npm).
Thai rendering: TH Sarabun New via matplotlib fontproperties for matplotlib figures.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).parent / "figures" / "generated"
OUT_DIR.mkdir(parents=True, exist_ok=True)
MERMAID_DIR = Path(__file__).parent / "figures" / "mermaid"


def render_mermaid(mmd_name: str, out_name: str, *, width: int = 1600):
    """Render a mermaid .mmd file to PNG using npx @mermaid-js/mermaid-cli.
    Requires npm/npx installed on PATH."""
    mmd_path = MERMAID_DIR / mmd_name
    out_path = OUT_DIR / out_name
    if not mmd_path.exists():
        print(f"  SKIP: {mmd_name} not found")
        return
    # Use npx to avoid global install; -y auto-confirms
    cmd = ["npx", "-y", "@mermaid-js/mermaid-cli@latest",
           "-i", str(mmd_path), "-o", str(out_path),
           "-b", "white", "--width", str(width)]
    try:
        # shell=True on Windows so npx.cmd resolves correctly
        result = subprocess.run(cmd, capture_output=True, text=True,
                                shell=(sys.platform == "win32"), timeout=120)
        if result.returncode != 0:
            print(f"  ERROR rendering {mmd_name}:")
            print(f"    stderr: {result.stderr[:300]}")
            return
        print(f"  saved (mermaid): {out_name}")
    except FileNotFoundError:
        print(f"  SKIP: npx not found — install node.js to render {mmd_name}")
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT rendering {mmd_name}")

# Force Thai font globally
plt.rcParams["font.family"] = "TH Sarabun New"
plt.rcParams["axes.unicode_minus"] = False

TH_TITLE = FontProperties(family="TH Sarabun New", size=18, weight="bold")
TH_LABEL = FontProperties(family="TH Sarabun New", size=14, weight="bold")
TH_BODY = FontProperties(family="TH Sarabun New", size=13)
TH_SMALL = FontProperties(family="TH Sarabun New", size=11)

# Color palette
C_INPUT = "#FFF2CC"
C_PROCESS = "#BDD7EE"
C_OUTPUT = "#C6E0B4"
C_EXTERNAL = "#E7E6E6"
C_BORDER = "#2F5496"
C_ARROW = "#404040"


def _box(ax, x, y, w, h, text, *, fill=C_PROCESS, fontprops=TH_BODY,
         edge=C_BORDER, lw=1.5):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        facecolor=fill, edgecolor=edge, linewidth=lw,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontproperties=fontprops, wrap=True)


def _arrow(ax, x1, y1, x2, y2, *, color=C_ARROW, style="->"):
    arrow = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=style, mutation_scale=20,
        color=color, linewidth=1.8,
    )
    ax.add_patch(arrow)


def _finish(fig, path, *, dpi=180):
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  saved: {path.name}")


# ============================================================
# FIGURE 2.1 — กรอบแนวคิดของการศึกษา (conceptual framework)
# ============================================================
def fig_2_1():
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6)
    ax.axis("off")

    ax.text(6, 5.6, "ภาพที่ 2.1 กรอบแนวคิดของการศึกษา",
            ha="center", fontproperties=TH_TITLE)

    # Input column
    _box(ax, 0.3, 1.5, 2.8, 3, "Input\n\n• เอกสารหลักสูตร\n  ของ tenant\n• คำถามของนิสิต",
         fill=C_INPUT, fontprops=TH_BODY)
    ax.text(1.7, 1.1, "ปัจจัยนำเข้า", ha="center", fontproperties=TH_LABEL)

    # Process column (wider)
    _box(ax, 3.8, 1.0, 4.4, 3.8,
         "ระบบ VIRIYA\n\n"
         "Agentic RAG\n"
         "(Lewis 2020 + Gao 2024)\n\n"
         "Multi-tenant SaaS\n"
         "(Bezemer 2010)",
         fill=C_PROCESS, fontprops=TH_BODY)
    ax.text(6.0, 0.6, "กระบวนการ", ha="center", fontproperties=TH_LABEL)

    # Output column (3 stacked)
    _box(ax, 8.9, 3.6, 2.8, 1.2, "คุณภาพคำตอบ\n(มุมมองเจ้าหน้าที่)",
         fill=C_OUTPUT, fontprops=TH_BODY)
    _box(ax, 8.9, 2.2, 2.8, 1.2, "การยอมรับ UTAUT\n(Venkatesh 2003)",
         fill=C_OUTPUT, fontprops=TH_BODY)
    _box(ax, 8.9, 0.8, 2.8, 1.2, "ความเป็นไปได้\nเชิงพาณิชย์",
         fill=C_OUTPUT, fontprops=TH_BODY)
    ax.text(10.3, 0.3, "ผลลัพธ์", ha="center", fontproperties=TH_LABEL)

    # Arrows
    _arrow(ax, 3.15, 3.0, 3.75, 3.0)
    _arrow(ax, 8.25, 4.2, 8.85, 4.2)
    _arrow(ax, 8.25, 2.8, 8.85, 2.8)
    _arrow(ax, 8.25, 1.4, 8.85, 1.4)

    # Feedback arrow
    ax.annotate("", xy=(6.0, 1.0), xytext=(10.3, 0.5),
                arrowprops=dict(arrowstyle="->", color="#C55A11",
                                linewidth=1.5, linestyle="--",
                                connectionstyle="arc3,rad=0.3"))
    ax.text(8.2, 0.1, "Feedback loop (ปรับปรุงฐานความรู้)",
            ha="center", fontproperties=TH_SMALL, color="#C55A11")

    _finish(fig, OUT_DIR / "fig_2_1_conceptual_framework.png")


# ============================================================
# FIGURE 3.1 — 3 phases methodology
# ============================================================
def fig_3_1():
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 5.5)
    ax.axis("off")

    ax.text(6.5, 5.1, "ภาพที่ 3.1 ขั้นตอนการดำเนินการวิจัย 3 ระยะ",
            ha="center", fontproperties=TH_TITLE)

    phases = [
        (0.2, "Phase 1\nสำรวจปัญหา\n(Exploration)",
         "• สัมภาษณ์เจ้าหน้าที่ 4 ท่าน\n• สัมภาษณ์นิสิต 3 ท่าน\n• Thematic analysis",
         "ความต้องการ\nของผู้มีส่วนได้เสีย"),
        (4.4, "Phase 2\nพัฒนาระบบ\n(Development)",
         "• Iterative development\n• Test-driven development\n• v1 -> v2 -> v2.1",
         "ระบบ VIRIYA\nพร้อม deploy"),
        (8.6, "Phase 3\nประเมินระบบ\n(Evaluation)",
         "• Chatbot Quality (N=2)\n• Admin Portal Task (N=2)\n• UTAUT Interview (N=6)\n• Staff Post-eva (N=2)",
         "คุณภาพคำตอบ\n+ การยอมรับ\n+ ความเป็นไปได้"),
    ]

    y_head = 3.4
    y_method = 1.7

    for x, title, method, output in phases:
        # Phase header box
        _box(ax, x, y_head, 4.0, 1.3, title, fill=C_PROCESS,
             fontprops=TH_LABEL)
        # Method box
        _box(ax, x, y_method, 4.0, 1.5, method, fill=C_INPUT,
             fontprops=TH_BODY)
        # Output box at bottom
        _box(ax, x, 0.2, 4.0, 1.3, f"Output\n{output}", fill=C_OUTPUT,
             fontprops=TH_BODY)

    # Arrows between phases
    for x in [4.2, 8.4]:
        _arrow(ax, x, 4.05, x + 0.2, 4.05)

    _finish(fig, OUT_DIR / "fig_3_1_methodology_phases.png")


# NOTE: fig_3_2 and fig_4_2 now rendered from Mermaid source (figures/mermaid/*.mmd)
# via render_mermaid() — dagre auto-routes arrows orthogonally, avoiding crossings.


# ============================================================
# FIGURE 4.3 — v1 → v2 → v2.1 evolution timeline
# ============================================================
def fig_4_3():
    fig, ax = plt.subplots(figsize=(14, 6.5))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6.5)
    ax.axis("off")

    ax.text(7, 6.1, "ภาพที่ 4.3 Timeline การวิวัฒนาการของระบบ VIRIYA",
            ha="center", fontproperties=TH_TITLE)

    # Timeline horizontal line
    ax.plot([0.8, 13.2], [3.5, 3.5], color=C_BORDER, linewidth=3, zorder=1)

    # Milestones
    milestones = [
        (1.5, "v0\nม.ค. 2569", "ต้นแบบ\nสำรวจ Chula PDFs",
         "• PDF parsing (pypdf)\n• Basic embedding\n• Local only"),
        (4.5, "v1\nมี.ค. 2569",
         "Dispatch-based\n~1,500 LOC",
         "• ingestion.py (750)\n• chunking.py (320)\n• enrichment.py (450)\n• Per-format branches\n• PDF/XLSX/DOCX"),
        (8.5, "v2\n19 เม.ย. 2569",
         "Universal multimodal\n~250 LOC",
         "• Opus 4.7 parse+chunk\n• LibreOffice -> PDF -> Opus\n• Single code path\n• 85% code reduction"),
        (12.0, "v2.1\n20 เม.ย. 2569",
         "Post-demo hardening",
         "• drive_file_id\n• Pinecone-first delete\n• LINE RENAME state\n• fonts-thai-tlwg fix"),
    ]

    for i, (x, label, title, details) in enumerate(milestones):
        # Milestone dot
        ax.plot(x, 3.5, "o", markersize=18, color=C_BORDER, zorder=2)

        # Label below dot
        ax.text(x, 3.15, label, ha="center", va="top",
                fontproperties=TH_LABEL, color=C_BORDER)

        # Title box (above dot)
        y_title = 4.3
        _box(ax, x - 1.3, y_title, 2.6, 0.9, title,
             fill=C_PROCESS, fontprops=TH_LABEL)

        # Detail box (below dot)
        y_detail = 0.6
        _box(ax, x - 1.3, y_detail, 2.6, 2.2, details,
             fill=C_INPUT, fontprops=TH_BODY)

        # Connector line
        ax.plot([x, x], [3.6, y_title], color=C_ARROW, linewidth=1, linestyle="--")
        ax.plot([x, x], [y_detail + 2.2, 3.4], color=C_ARROW, linewidth=1, linestyle="--")

    _finish(fig, OUT_DIR / "fig_4_3_evolution_timeline.png")


# ============================================================
# main
# ============================================================
if __name__ == "__main__":
    print(f"Output directory: {OUT_DIR}")
    print()
    print("Matplotlib figures:")
    fig_2_1()
    fig_3_1()
    fig_4_3()
    print()
    # NOTE: fig 3.2 and 4.2 are now user-provided hi-res images at
    # figures/generated/fig_{3_2,4_2}_*_new.png. The .mmd sources are
    # kept as reference/backup only and are NOT rendered in the normal
    # build flow. Uncomment below if you need to regenerate from mermaid.
    # render_mermaid("fig_3_2_system_architecture.mmd",
    #                "fig_3_2_system_architecture.png", width=1400)
    # render_mermaid("fig_4_2_detailed_architecture.mmd",
    #                "fig_4_2_detailed_architecture.png", width=1600)
    print()
    print("3 figures generated (fig 3.2 and 4.2 use user-provided hi-res images).")
