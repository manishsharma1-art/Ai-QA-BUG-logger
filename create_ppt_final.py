"""
Generate a 4-slide QA Bug Logger presentation using the 30-year IndiaMART template.

Slide 1 — Manual QA Problem & Current Flow
Slide 2 — Our Solution: Technical Flow & Time Saving
Slide 3 — Cost Analysis (1,500 bugs/month, token breakdown)
Slide 4 — Market Comparison & Differentiators
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor

# ── Design tokens from template ──────────────────────────────────
ACCENT      = RGBColor(0xC8, 0x18, 0x1B)   # IndiaMART red
DARK_TEXT   = RGBColor(0x3F, 0x3F, 0x3F)
WHITE       = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_BG    = RGBColor(0xF5, 0xF5, 0xF5)
GREEN       = RGBColor(0x28, 0xA7, 0x45)
BLUE        = RGBColor(0x00, 0x6D, 0xCB)
DARK_BG     = RGBColor(0x2D, 0x2D, 0x2D)
AMBER       = RGBColor(0xFF, 0x8F, 0x00)
FONT_NAME   = "Open Sans"

SW = 12192000   # slide width EMU
SH = 6858000    # slide height EMU


# ── helpers ──────────────────────────────────────────────────────
def _add_underline_bar(slide, left_in=0.74, top_in=1.50, width_in=1.76):
    """Replicate the red accent bar from the template."""
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in), Inches(width_in), Inches(0.06))
    bar.fill.solid()
    bar.fill.fore_color.rgb = ACCENT
    bar.line.fill.background()
    return bar


def _set_title(slide, text):
    """Set the title placeholder text with template styling."""
    title = slide.shapes.title
    title.text = text
    for para in title.text_frame.paragraphs:
        for run in para.runs:
            run.font.name = FONT_NAME
            run.font.size = Pt(28)
            run.font.bold = True
            run.font.color.rgb = DARK_TEXT


def _add_box(slide, left, top, w, h, fill_color,
             title_text="", body_lines=None, title_size=Pt(16),
             body_size=Pt(13), text_color=WHITE, title_color=None):
    """Add a rounded rectangle with title + bullet body."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    shape.line.fill.background()
    shape.shadow.inherit = False

    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.15)
    tf.margin_right = Inches(0.15)
    tf.margin_top = Inches(0.12)

    if title_text:
        p = tf.paragraphs[0]
        p.text = title_text
        p.font.name = FONT_NAME
        p.font.size = title_size
        p.font.bold = True
        p.font.color.rgb = title_color or text_color
        p.alignment = PP_ALIGN.LEFT

    if body_lines:
        for line in body_lines:
            p = tf.add_paragraph()
            p.text = line
            p.font.name = FONT_NAME
            p.font.size = body_size
            p.font.color.rgb = text_color
            p.space_before = Pt(4)
            p.space_after = Pt(2)
    return shape


def _add_arrow(slide, left, top, w, h, color=ACCENT):
    """Add a right-pointing arrow chevron."""
    shape = slide.shapes.add_shape(MSO_SHAPE.CHEVRON, left, top, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _add_flow_step(slide, left, top, w, h, number, title, subtitle,
                   bg_color=ACCENT, num_color=WHITE, txt_color=WHITE):
    """Add a numbered flow step box."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = bg_color
    shape.line.fill.background()
    shape.shadow.inherit = False

    tf = shape.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.1)
    tf.margin_right = Inches(0.1)
    tf.margin_top = Inches(0.08)

    # Number
    p0 = tf.paragraphs[0]
    p0.text = number
    p0.font.name = FONT_NAME
    p0.font.size = Pt(28)
    p0.font.bold = True
    p0.font.color.rgb = num_color
    p0.alignment = PP_ALIGN.CENTER

    # Title
    p1 = tf.add_paragraph()
    p1.text = title
    p1.font.name = FONT_NAME
    p1.font.size = Pt(14)
    p1.font.bold = True
    p1.font.color.rgb = txt_color
    p1.alignment = PP_ALIGN.CENTER
    p1.space_before = Pt(4)

    # Subtitle
    p2 = tf.add_paragraph()
    p2.text = subtitle
    p2.font.name = FONT_NAME
    p2.font.size = Pt(10)
    p2.font.color.rgb = txt_color
    p2.alignment = PP_ALIGN.CENTER
    p2.space_before = Pt(2)
    return shape


def _add_kpi(slide, left, top, number, label,
             num_color=ACCENT, label_color=DARK_TEXT):
    """Add a large KPI number with a small label underneath."""
    # Number
    tb = slide.shapes.add_textbox(left, top, Inches(2.2), Inches(0.7))
    p = tb.text_frame.paragraphs[0]
    p.text = number
    p.font.name = FONT_NAME
    p.font.size = Pt(40)
    p.font.bold = True
    p.font.color.rgb = num_color
    p.alignment = PP_ALIGN.CENTER

    # Label
    tb2 = slide.shapes.add_textbox(left, top + Inches(0.65), Inches(2.2), Inches(0.5))
    p2 = tb2.text_frame.paragraphs[0]
    p2.text = label
    p2.font.name = FONT_NAME
    p2.font.size = Pt(12)
    p2.font.color.rgb = label_color
    p2.alignment = PP_ALIGN.CENTER


def _add_table(slide, left, top, rows_data, col_widths,
               header_color=ACCENT, alt_color=LIGHT_BG):
    """Add a styled table."""
    rows = len(rows_data)
    cols = len(rows_data[0])
    table_shape = slide.shapes.add_table(rows, cols, left, top,
                                         sum(col_widths), Inches(0.38 * rows))
    table = table_shape.table

    for ci, cw in enumerate(col_widths):
        table.columns[ci].width = cw

    for ri, row in enumerate(rows_data):
        for ci, cell_text in enumerate(row):
            cell = table.cell(ri, ci)
            cell.text = str(cell_text)
            for para in cell.text_frame.paragraphs:
                para.font.name = FONT_NAME
                para.font.size = Pt(11)
                para.alignment = PP_ALIGN.CENTER
                if ri == 0:
                    para.font.bold = True
                    para.font.color.rgb = WHITE
                    para.font.size = Pt(12)
                else:
                    para.font.color.rgb = DARK_TEXT

            # cell fill
            if ri == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = header_color
            elif ri % 2 == 0:
                cell.fill.solid()
                cell.fill.fore_color.rgb = alt_color
            else:
                cell.fill.solid()
                cell.fill.fore_color.rgb = WHITE

            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    return table_shape


# ════════════════════════════════════════════════════════════════
# BUILD THE PRESENTATION
# ════════════════════════════════════════════════════════════════
def main():
    prs = Presentation("30-year template_Apr 22.pptx")

    # Remove the existing 5 demo slides
    xml_slides = prs.slides._sldIdLst
    slides_to_remove = list(xml_slides)
    for sldId in slides_to_remove:
        rId = sldId.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        if rId:
            prs.part.drop_rel(rId)
        xml_slides.remove(sldId)

    blank = prs.slide_layouts[1]  # 'blank-slide' — has title + underline bar

    # ────────────────────────────────────────────────────────────
    # SLIDE 1: Manual QA Bug Logging Problem
    # ────────────────────────────────────────────────────────────
    s1 = prs.slides.add_slide(blank)
    _set_title(s1, "Manual QA Bug Logging — The Problem")
    _add_underline_bar(s1)

    # Current flow: 6 steps across the top
    flow_steps = [
        ("01", "Find Bug", "During testing"),
        ("02", "Switch App", "Open OpenProject"),
        ("03", "Write Report", "Title, steps, env…"),
        ("04", "Upload Media", "Screenshots / video"),
        ("05", "Set Metadata", "Priority, type, project"),
        ("06", "Submit & Link", "Share link in chat"),
    ]
    step_w = Inches(1.8)
    gap = Inches(0.18)
    start_left = Inches(0.6)
    for i, (num, title, sub) in enumerate(flow_steps):
        left = start_left + i * (step_w + gap)
        _add_flow_step(s1, left, Inches(2.0), step_w, Inches(1.5),
                       num, title, sub, bg_color=DARK_BG)

    # Arrow strip connecting flow
    for i in range(5):
        left = start_left + (i + 1) * (step_w + gap) - gap
        _add_arrow(s1, left, Inches(2.5), gap, Inches(0.4), color=ACCENT)

    # Pain-point KPIs at the bottom
    _add_kpi(s1, Inches(0.8),  Inches(4.2), "5–10 min",  "Per Bug Report",   ACCENT)
    _add_kpi(s1, Inches(3.4),  Inches(4.2), "1,500+",    "Bugs / Month",     ACCENT)
    _add_kpi(s1, Inches(6.0),  Inches(4.2), "125–250 hr","Wasted Monthly",   ACCENT)
    _add_kpi(s1, Inches(8.8),  Inches(4.2), "40%",       "Context Switching", ACCENT)

    # Bottom banner
    banner = s1.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.5), Inches(5.8), Inches(12.3), Inches(0.8))
    banner.fill.solid()
    banner.fill.fore_color.rgb = ACCENT
    banner.line.fill.background()
    p = banner.text_frame.paragraphs[0]
    p.text = "⚠  QA Engineers spend more time documenting bugs than finding them"
    p.font.name = FONT_NAME
    p.font.size = Pt(18)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.CENTER

    # ────────────────────────────────────────────────────────────
    # SLIDE 2: Our Solution — Technical Workflow
    # ────────────────────────────────────────────────────────────
    s2 = prs.slides.add_slide(blank)
    _set_title(s2, "QA Bug Logger Bot — How It Works")
    _add_underline_bar(s2)

    # 4-step flow with arrows
    sol_steps = [
        ("01", "Drop in Chat", "Text, screenshot\nor screen recording"),
        ("02", "Smart Routing", "Regex + NLP picks\ncorrect project"),
        ("03", "AI Analysis", "Gemini 2.5 Flash +\n6.6K RAG Corpus"),
        ("04", "Ticket Created", "OpenProject ticket\n+ media attached"),
    ]
    sol_w = Inches(2.5)
    sol_gap = Inches(0.55)
    sol_start = Inches(0.5)
    sol_top = Inches(2.2)
    sol_h = Inches(1.8)

    for i, (num, title, sub) in enumerate(sol_steps):
        left = sol_start + i * (sol_w + sol_gap)
        _add_flow_step(s2, left, sol_top, sol_w, sol_h,
                       num, title, sub, bg_color=ACCENT)

    # Arrows between boxes
    for i in range(3):
        arr_left = sol_start + (i + 1) * (sol_w + sol_gap) - sol_gap + Inches(0.02)
        arr = s2.shapes.add_shape(
            MSO_SHAPE.RIGHT_ARROW, arr_left, sol_top + Inches(0.6),
            sol_gap - Inches(0.04), Inches(0.5))
        arr.fill.solid()
        arr.fill.fore_color.rgb = DARK_TEXT
        arr.line.fill.background()

    # Time comparison bottom section
    _add_box(s2, Inches(0.5), Inches(4.6), Inches(3.8), Inches(1.8), DARK_BG,
             "⏱  Before (Manual)", [
                 "7 min avg per ticket",
                 "Multiple app switches",
                 "Frequent misrouting"
             ], body_size=Pt(13))

    # Big arrow
    arr2 = s2.shapes.add_shape(
        MSO_SHAPE.RIGHT_ARROW, Inches(4.5), Inches(5.1), Inches(0.8), Inches(0.7))
    arr2.fill.solid()
    arr2.fill.fore_color.rgb = ACCENT
    arr2.line.fill.background()

    _add_box(s2, Inches(5.5), Inches(4.6), Inches(3.8), Inches(1.8), GREEN,
             "⚡ After (Bot)", [
                 "30 sec avg per ticket",
                 "Zero context switching",
                 "99.8% routing accuracy"
             ], body_size=Pt(13))

    # Savings callout
    save_box = s2.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(9.7), Inches(4.6),
        Inches(3.0), Inches(1.8))
    save_box.fill.solid()
    save_box.fill.fore_color.rgb = LIGHT_BG
    save_box.line.fill.background()
    tf = save_box.text_frame
    tf.word_wrap = True
    tf.margin_top = Inches(0.15)
    p = tf.paragraphs[0]
    p.text = "93%"
    p.font.name = FONT_NAME
    p.font.size = Pt(48)
    p.font.bold = True
    p.font.color.rgb = GREEN
    p.alignment = PP_ALIGN.CENTER
    p2 = tf.add_paragraph()
    p2.text = "Time Saved\nPer Ticket"
    p2.font.name = FONT_NAME
    p2.font.size = Pt(16)
    p2.font.color.rgb = DARK_TEXT
    p2.alignment = PP_ALIGN.CENTER

    # ────────────────────────────────────────────────────────────
    # SLIDE 3: Cost Analysis
    # ────────────────────────────────────────────────────────────
    s3 = prs.slides.add_slide(blank)
    _set_title(s3, "Cost Analysis — 1,500 Bugs / Month")
    _add_underline_bar(s3)

    # LEFT: Token Consumption Table
    sub_title1 = s3.shapes.add_textbox(Inches(0.5), Inches(1.8), Inches(5), Inches(0.4))
    p = sub_title1.text_frame.paragraphs[0]
    p.text = "Token Consumption Breakdown"
    p.font.name = FONT_NAME
    p.font.size = Pt(16)
    p.font.bold = True
    p.font.color.rgb = ACCENT

    token_data = [
        ["Component",         "Tokens/Bug", "Monthly Total",  "Cost (USD)"],
        ["Phase 1 (Text)",    "~4,200",     "6,300,000",      "$0.95"],
        ["Phase 2 (Media)",   "~8,500",     "6,375,000",      "$0.96"],
        ["RAG Retrieval",     "~3,000",     "4,500,000",      "$0.68"],
        ["Bucket Picker",     "~800",       "120,000",        "$0.02"],
        ["Smoke Test",        "~200",       "6,000",          "<$0.01"],
        ["Total",             "~16,700",    "17,301,000",     "$2.61"],
    ]
    _add_table(s3, Inches(0.5), Inches(2.3), token_data,
               [Inches(1.6), Inches(1.2), Inches(1.5), Inches(1.2)])

    # RIGHT: Cost Analysis Table
    sub_title2 = s3.shapes.add_textbox(Inches(6.5), Inches(1.8), Inches(6), Inches(0.4))
    p2 = sub_title2.text_frame.paragraphs[0]
    p2.text = "Cost Comparison: Manual vs Bot"
    p2.font.name = FONT_NAME
    p2.font.size = Pt(16)
    p2.font.bold = True
    p2.font.color.rgb = ACCENT

    cost_data = [
        ["Metric",              "Manual QA",       "QA Bot"],
        ["Time per ticket",     "7 min",           "30 sec"],
        ["Monthly hours",       "175 hrs",         "12.5 hrs"],
        ["Engineer cost",       "₹2,62,500",       "₹0 (automated)"],
        ["Cloud Run cost",      "—",               "₹1,250 /mo"],
        ["LLM token cost",      "—",               "₹220 /mo"],
        ["Total monthly cost",  "₹2,62,500",       "₹1,470"],
        ["Monthly savings",     "",                 "₹2,61,030 ✓"],
    ]
    _add_table(s3, Inches(6.5), Inches(2.3), cost_data,
               [Inches(1.8), Inches(1.8), Inches(2.2)])

    # Bottom highlight strip
    hl = s3.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.5), Inches(5.8), Inches(12.3), Inches(0.8))
    hl.fill.solid()
    hl.fill.fore_color.rgb = GREEN
    hl.line.fill.background()
    p = hl.text_frame.paragraphs[0]
    p.text = "💰  Net Savings: ₹2,61,030 / month  |  ROI: 177x  |  Payback: Day 1"
    p.font.name = FONT_NAME
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = WHITE
    p.alignment = PP_ALIGN.CENTER

    # ────────────────────────────────────────────────────────────
    # SLIDE 4: Market Comparison
    # ────────────────────────────────────────────────────────────
    s4 = prs.slides.add_slide(blank)
    _set_title(s4, "Market Comparison — How We Stand Out")
    _add_underline_bar(s4)

    comp_data = [
        ["Feature",             "QA Bug Logger",    "Testim",        "BrowserStack",  "Katalon AI"],
        ["Monthly Cost",        "₹1,470",           "$450+",         "$300+",         "$200+"],
        ["Per-ticket Cost",     "₹0.98",            "~₹25",          "~₹20",          "~₹15"],
        ["Bug Detection",      "Manual (by QA)",    "Automated",     "Automated",     "Automated"],
        ["Bug Reporting",      "Fully Automated",   "Manual",        "Manual",        "Semi-Auto"],
        ["Video to Ticket",    "✓  30 sec",         "✗",             "✗",             "✗"],
        ["RAG Context",        "✓  6.6K corpus",    "✗",             "✗",             "✗"],
        ["Smart Routing",      "✓  34 projects",    "✗",             "✗",             "Basic"],
        ["Chat Integration",   "✓  Google Chat",    "Slack (basic)", "✗",             "✗"],
        ["Self-hosted",        "✓  Cloud Run",      "SaaS only",     "SaaS only",     "SaaS only"],
    ]
    _add_table(s4, Inches(0.5), Inches(2.0), comp_data,
               [Inches(1.8), Inches(2.2), Inches(1.8), Inches(1.8), Inches(1.8)])

    # Key differentiators callout
    diff_box = _add_box(s4, Inches(0.5), Inches(5.6), Inches(12.3), Inches(1.2), ACCENT,
        "Our Edge", [
            "🔒 Zero SaaS vendor lock-in  •  Self-hosted on your own GCP",
            "🧠 RAG-powered context from your own 6,600+ historical bugs  •  Gets smarter over time",
            "💬 Seamless Google Chat integration  •  No extra tool to learn"
        ], title_size=Pt(16), body_size=Pt(13))

    # ── Save ──
    out = "QA_Bug_Logger_Final.pptx"
    prs.save(out)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
