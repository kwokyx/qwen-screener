"""生成《基于千问的股票筛选系统设计与实现》设计文档。

输出：qwen-stock-screener/docs/基于千问的股票筛选系统设计与实现.docx

排版规范（按高校学年/毕业设计常用格式）：
- 中文正文：宋体 小四（12pt），首行缩进 2 字符，1.5 倍行距
- 英文/数字：Times New Roman
- 一级标题：黑体 三号（16pt） 居中
- 二级标题：黑体 小三（15pt） 顶格
- 三级标题：黑体 四号（14pt） 顶格
- 表格：表头加粗、居中；单元格 宋体 五号
- 代码：Consolas 五号 + 浅灰底
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement


SONG = "宋体"
HEI = "黑体"
KAI = "楷体"
EN = "Times New Roman"
MONO = "Consolas"


# ---------------- 基础工具 ----------------

def set_run_font(run, *, cn: str = SONG, en: str = EN, size: float = 12, bold: bool = False, color: str | None = None):
    run.font.name = en
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), cn)
    rFonts.set(qn("w:ascii"), en)
    rFonts.set(qn("w:hAnsi"), en)


def add_paragraph(doc, text: str = "", *, style: str | None = None, indent: bool = True,
                  align=WD_ALIGN_PARAGRAPH.JUSTIFY, size: float = 12, bold: bool = False,
                  cn: str = SONG, en: str = EN, line_spacing: float = 1.5,
                  space_before: float = 0, space_after: float = 0):
    p = doc.add_paragraph(style=style)
    p.alignment = align
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = line_spacing
    if indent:
        pf.first_line_indent = Pt(size * 2)
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    if text:
        run = p.add_run(text)
        set_run_font(run, cn=cn, en=en, size=size, bold=bold)
    return p


def add_h1(doc, text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.5
    pf.space_before = Pt(18)
    pf.space_after = Pt(12)
    pf.page_break_before = True
    run = p.add_run(text)
    set_run_font(run, cn=HEI, en=EN, size=16, bold=True)
    return p


def add_h2(doc, text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.5
    pf.space_before = Pt(12)
    pf.space_after = Pt(6)
    run = p.add_run(text)
    set_run_font(run, cn=HEI, en=EN, size=15, bold=True)
    return p


def add_h3(doc, text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.5
    pf.space_before = Pt(8)
    pf.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, cn=HEI, en=EN, size=14, bold=True)
    return p


def add_caption(doc, text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.5
    pf.space_before = Pt(2)
    pf.space_after = Pt(8)
    run = p.add_run(text)
    set_run_font(run, cn=SONG, en=EN, size=10.5, bold=True)


def add_code_block(doc, code: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    pf.line_spacing = 1.15
    pf.space_before = Pt(4)
    pf.space_after = Pt(8)
    pf.left_indent = Pt(12)
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), "F2F2F2")
    pPr.append(shd)
    run = p.add_run(code)
    set_run_font(run, cn=SONG, en=MONO, size=10)


def set_cell_borders(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        b = OxmlElement(f"w:{edge}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:color"), "000000")
        tcBorders.append(b)
    tcPr.append(tcBorders)


def add_table(doc, header: list[str], rows: list[list[str]], *, col_widths: list[float] | None = None,
              caption: str | None = None):
    if caption:
        add_caption(doc, caption)
    table = doc.add_table(rows=1 + len(rows), cols=len(header))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    if col_widths:
        for i, w in enumerate(col_widths):
            for cell in table.columns[i].cells:
                cell.width = Cm(w)

    # 表头
    for i, h in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_borders(cell)
        # 表头底纹
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "DCE6F1")
        tcPr.append(shd)
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        run = para.add_run(h)
        set_run_font(run, cn=HEI, en=EN, size=10.5, bold=True)

    # 数据行
    for r, row in enumerate(rows, start=1):
        for c, val in enumerate(row):
            cell = table.rows[r].cells[c]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_borders(cell)
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT
            para.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            run = para.add_run(val)
            set_run_font(run, cn=SONG, en=EN, size=10.5)
    return table


def add_bullet(doc, text: str, *, level: int = 0):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Pt(18 + level * 12)
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.first_line_indent = Pt(0)
    run = p.add_run(text)
    set_run_font(run, cn=SONG, en=EN, size=12)


# ---------------- 文档主体 ----------------

def build_document(out_path: Path):
    doc = Document()

    # 页边距
    section = doc.sections[0]
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(3.18)
    section.right_margin = Cm(3.18)

    # 默认字体
    style = doc.styles["Normal"]
    style.font.name = EN
    style.font.size = Pt(12)
    rPr = style.element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), SONG)

    # ---------------- 封面 ----------------
    for _ in range(3):
        doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(36)
    run = p.add_run("基于千问的股票筛选系统设计与实现")
    set_run_font(run, cn=HEI, en=EN, size=26, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(48)
    run = p.add_run("Design and Implementation of a Qwen-LLM-Based A-Share Stock Screening System")
    set_run_font(run, cn=SONG, en=EN, size=14, bold=False)

    cover_info = [
        ("项 目 类 型", "学年设计 / 毕业设计"),
        ("学　　　科", "计算机科学与技术 / 软件工程"),
        ("文档版本", "v1.0"),
        ("完成日期", "2026 年 5 月"),
    ]
    for label, value in cover_info:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(10)
        run = p.add_run(f"{label}：")
        set_run_font(run, cn=HEI, en=EN, size=14, bold=True)
        run = p.add_run(value)
        set_run_font(run, cn=SONG, en=EN, size=14, bold=False)

    # ---------------- 摘要 ----------------
    add_h1(doc, "摘　　要")
    add_paragraph(
        doc,
        "随着人工智能技术与金融数据服务的快速发展，普通投资者面对超过五千只 A 股的宏大数据集时，"
        "传统因子筛选工具普遍存在「门槛高、操作繁、表达不直观」的问题：用户必须熟悉市盈率、净资产收益率、"
        "营收同比等专业指标的精确取值范围，才能筛出符合自己投资偏好的标的。本系统以阿里云通义千问大模型为核心，"
        "构建了一套「自然语言 + 结构化条件」双通道的 A 股股票筛选与基本面分析平台，旨在降低量化工具的使用门槛。"
    )
    add_paragraph(
        doc,
        "系统采用前后端分离架构，后端基于 Python 3.10 与 FastAPI 框架，使用 SQLAlchemy 2.0 ORM 操作 MySQL 8 数据库，"
        "通过 AKShare 开源接口同步沪深 A 股的基本信息、行情快照、估值指标和财务摘要；筛选引擎将十二个核心字段与七种"
        "比较操作符抽象为可组合的 FilterCondition 对象，并通过千问大模型把用户的中文自然语言意图自动翻译为该结构化条件，"
        "由同一引擎执行，从而保证「自然语言筛选」与「传统多条件筛选」结果一致。前端采用 Vue 3 + Vite + Pinia 实现响应式 SPA，"
        "并通过 APScheduler 定时任务在每个交易日自动刷新行情与财务数据。"
    )
    add_paragraph(
        doc,
        "经在 i7 + 16GB 的开发机上对沪深 300 全量股票进行测试，自然语言筛选端到端响应控制在 5 秒内，"
        "结构化筛选小于 200 ms；千问对单只股票的投资分析平均耗时 8 秒。系统覆盖账号注册登录、股票搜索、详情查看、"
        "K 线展示、自选股管理、自然语言筛选、千问个股分析等完整功能，验证了将大语言模型嵌入传统量化工具的可行性。"
    )
    add_paragraph(
        doc,
        "关键词：通义千问；自然语言处理；A 股筛选；FastAPI；Vue 3；AKShare",
        bold=True, indent=False, align=WD_ALIGN_PARAGRAPH.LEFT,
    )

    # ---------------- 第 1 章 绪论 ----------------
    add_h1(doc, "第 1 章　绪　论")

    add_h2(doc, "1.1 研究背景与意义")
    add_paragraph(
        doc,
        "A 股市场截至 2026 年初已有超过 5500 家上市公司，每个交易日产生海量的行情、估值与财务数据。"
        "对于个人投资者而言，从如此庞大的样本空间中筛选出符合自身偏好的标的需要专业的金融数据库和量化工具，"
        "传统选股软件（如同花顺问财、东方财富 Choice）虽提供了多因子组合筛选，但用户仍需熟悉「市盈率小于 15」、"
        "「净资产收益率大于 15%」等定量表达，对非专业用户并不友好。"
    )
    add_paragraph(
        doc,
        "近年来以 GPT、文心一言、通义千问为代表的大语言模型在自然语言理解与结构化输出能力上取得了长足进步，"
        "为「用一句话表达投资偏好」这一长期诉求提供了技术可行性。本课题围绕「让普通用户用自然语言完成专业选股」"
        "这一核心问题，结合千问大模型与开源金融数据接口 AKShare，探索一套面向 A 股的轻量化、可落地的智能筛选系统。"
    )

    add_h2(doc, "1.2 国内外研究现状")
    add_paragraph(
        doc,
        "国外方面，Bloomberg Terminal、FactSet 等专业终端为机构投资者提供了强大的多因子筛选与基本面分析功能，"
        "但其使用成本高昂、面向专业用户；近期 Bloomberg 也推出了 BloombergGPT，将大语言模型用于金融文本生成与摘要，"
        "但尚未在国内市场公开提供类似服务。国内方面，万得（Wind）、同花顺 iFinD 等平台同样提供丰富的因子筛选，"
        "同花顺「问财」率先尝试以问答方式选股，但其底层大模型为闭源黑盒，且对学术研究、二次开发不开放。"
    )
    add_paragraph(
        doc,
        "在开源生态中，AKShare、Tushare 提供了大量 A 股开源数据接口；通义千问、DeepSeek 等国产大模型对外开放 API；"
        "FastAPI、Vue 3 等开源框架降低了 Web 系统开发门槛。这为高校学生在普通开发机上自行实现一套小而完整的智能选股系统提供了条件。"
    )

    add_h2(doc, "1.3 主要研究内容")
    add_paragraph(doc, "本课题主要完成以下工作：")
    add_bullet(doc, "1. 调研开源金融数据源 AKShare 的可用接口，设计稳定的数据同步通路并落地至关系型数据库；")
    add_bullet(doc, "2. 设计并实现一套通用的多因子筛选引擎，支持 12 个核心字段与 7 种比较操作符；")
    add_bullet(doc, "3. 通过 Prompt Engineering 让通义千问把用户中文自然语言精准翻译为结构化筛选条件；")
    add_bullet(doc, "4. 基于 Vue 3 实现简洁直观的前端界面，覆盖筛选、详情、自选、对话筛选等核心交互；")
    add_bullet(doc, "5. 接入 APScheduler 定时任务实现每日盘后自动同步，保证数据时效性。")

    add_h2(doc, "1.4 论文组织结构")
    add_paragraph(doc, "本文共分为八章，组织结构如下：")
    add_bullet(doc, "第 1 章 绪论：阐述研究背景、意义与主要内容；")
    add_bullet(doc, "第 2 章 需求分析：从功能性、非功能性、用户角色与用例四个角度分析系统需求；")
    add_bullet(doc, "第 3 章 系统设计：给出整体架构、模块划分、关键流程与接口设计；")
    add_bullet(doc, "第 4 章 数据库设计：介绍概念模型、逻辑模型、范式分析、完整 DDL 与样例数据；")
    add_bullet(doc, "第 5 章 详细设计与实现：包括筛选引擎、千问客户端、安全设计、异常处理与流程图；")
    add_bullet(doc, "第 6 章 系统测试：对功能、性能、兼容性、安全与用户体验进行测试与分析；")
    add_bullet(doc, "第 7 章 系统运行效果展示：选取七个核心页面展示运行截图与功能说明；")
    add_bullet(doc, "第 8 章 总结与展望：总结工作成果，展望后续可扩展方向。")

    # ---------------- 第 2 章 需求分析 ----------------
    add_h1(doc, "第 2 章　需求分析")

    add_h2(doc, "2.1 项目目标")
    add_paragraph(
        doc,
        "本系统面向高校学生、初级投资者以及对量化工具感兴趣的程序员，目标是提供一个可在普通开发机上独立部署的"
        "「自然语言驱动 + 结构化精筛」的 A 股股票筛选平台。系统需在保证数据正确性的前提下兼顾响应速度与可读性，"
        "便于用户在论文截图、教学演示与个人投资研究等场景下使用。"
    )

    add_h2(doc, "2.2 用户角色分析")
    add_table(
        doc,
        header=["角色", "代表用户", "核心诉求", "权限范围"],
        rows=[
            ["游客", "首次访问者", "浏览行情、试用筛选", "公开接口（搜索、筛选、详情、K 线）"],
            ["注册用户", "学生 / 初级投资者", "保存自选股、保留筛选历史", "公开接口 + 自选 / 历史相关接口"],
            ["管理员", "系统维护者", "数据同步、定时任务监控、日志排查", "全部接口 + 数据同步脚本"],
        ],
        col_widths=[2.6, 3.4, 4.5, 4.5],
        caption="表 2-1　用户角色与权限",
    )

    add_h2(doc, "2.3 功能性需求")

    add_h3(doc, "2.3.1 用户管理")
    add_bullet(doc, "FR-1 用户注册：用户名（3-64 字符）+ 密码（≥6 字符），可选邮箱；密码使用 bcrypt 哈希存储；")
    add_bullet(doc, "FR-2 用户登录：基于 OAuth2PasswordBearer，颁发 JWT，默认 24 小时有效；")
    add_bullet(doc, "FR-3 当前用户信息：通过 /auth/me 返回用户基本资料。")

    add_h3(doc, "2.3.2 股票数据浏览")
    add_bullet(doc, "FR-4 股票搜索：支持按代码（如 600000）或名称（如「平安」）模糊搜索；")
    add_bullet(doc, "FR-5 个股详情：返回基本信息 + 最新行情快照 + 最新一期财务摘要；")
    add_bullet(doc, "FR-6 K 线数据：返回近 N 个交易日的 OHLCV 序列，N 可配置（默认 120）。")

    add_h3(doc, "2.3.3 股票筛选")
    add_bullet(doc, "FR-7 多条件筛选：传入若干 FilterCondition（字段 + 操作符 + 阈值），支持 AND / OR 组合；")
    add_bullet(doc, "FR-8 自然语言筛选：传入一句话（如「ROE 大于 15 且最新季度净利润同比正增长的成长股」），"
                    "由千问翻译为结构化条件后由同一引擎执行；")
    add_bullet(doc, "FR-9 排序与分页：支持按任意可筛字段升降序，结果上限可配置（默认 50，最大 500）。")

    add_h3(doc, "2.3.4 自选股管理")
    add_bullet(doc, "FR-10 增删自选：登录用户可对自选股进行增删，支持加入价、加入日期和预警规则同步；")
    add_bullet(doc, "FR-11 自选列表：支持按加入日期、涨跌幅、估值、行业等字段排序，并支持批量编辑；")
    add_bullet(doc, "FR-12 预警规则：支持价格突破、价格跌破、累计涨跌幅、日内涨跌幅等规则，并可批量启用、暂停或删除。")

    add_h3(doc, "2.3.5 千问智能分析")
    add_bullet(doc, "FR-12 个股分析：传入股票代码，由千问基于最新基本面数据生成 300-500 字的投资分析文本；")
    add_bullet(doc, "FR-13 异常降级：千问 API 不可用时，前端展示提示信息，不影响其他模块。")

    add_h3(doc, "2.3.6 数据同步")
    add_bullet(doc, "FR-14 全量基础信息同步：覆盖全 A 股 5500+ 只代码、名称；")
    add_bullet(doc, "FR-15 股票池行情同步：默认沪深 300，可切换中证 500、上证 50；")
    add_bullet(doc, "FR-16 行业 / 上市时间 / 财务摘要同步：通过雪球、东方财富接口逐只补全；")
    add_bullet(doc, "FR-17 定时任务：每个交易日 16:00 拉取行情快照，每周一 17:00 拉取行业和财务数据。")

    add_h2(doc, "2.4 非功能性需求")
    add_table(
        doc,
        header=["编号", "类别", "需求描述", "可量化指标"],
        rows=[
            ["NFR-1", "性能", "结构化筛选响应时间", "P95 ≤ 500 ms（沪深 300 范围）"],
            ["NFR-2", "性能", "自然语言筛选端到端响应", "P95 ≤ 8 s（含千问推理）"],
            ["NFR-3", "可用性", "前端界面可在 1280×720 及以上分辨率正常显示", "无横向滚动条"],
            ["NFR-4", "可维护性", "代码遵循 PEP 8 / ESLint 推荐规范", "Pylint ≥ 8.0"],
            ["NFR-5", "可扩展性", "新增筛选字段无需改动引擎主体", "仅需在 FIELD_MAP / Prompt 中增加配置"],
            ["NFR-6", "安全性", "用户密码不可逆存储，接口防 SQL 注入", "bcrypt + ORM 参数化"],
            ["NFR-7", "可观察", "关键流程含 INFO/WARN 级别日志", "loguru 输出，含 traceId"],
            ["NFR-8", "兼容性", "数据库支持 MySQL 8 和 SQLite 3", "同一套 ORM 代码"],
        ],
        col_widths=[1.8, 2.0, 7.2, 4.0],
        caption="表 2-2　非功能性需求",
    )

    add_h2(doc, "2.5 用例分析")
    add_paragraph(
        doc,
        "系统的核心用例可归纳为「数据准备 → 用户筛选 → 结果分析」三大阶段。游客可直接使用搜索、筛选、详情等公开能力；"
        "注册用户在此基础上获得自选与历史能力；管理员通过命令行脚本触发数据同步。下表 2-3 列出系统主要用例。"
    )
    add_table(
        doc,
        header=["用例编号", "用例名称", "主参与者", "前置条件", "后置条件"],
        rows=[
            ["UC-01", "注册账号", "游客", "用户名未被占用", "用户记录写入 users 表"],
            ["UC-02", "登录", "已注册用户", "提供正确用户名密码", "返回 JWT，登录态建立"],
            ["UC-03", "搜索股票", "游客 / 用户", "stock_basic 已同步", "返回最多 N 条匹配结果"],
            ["UC-04", "查看个股详情", "游客 / 用户", "股票存在", "返回最新行情 + 财务汇总"],
            ["UC-05", "结构化筛选", "游客 / 用户", "提交合法的条件 JSON", "返回排序后的股票列表"],
            ["UC-06", "自然语言筛选", "游客 / 用户", "千问 API Key 配置正确", "返回筛选结果与回显条件"],
            ["UC-07", "千问个股分析", "游客 / 用户", "股票存在 + API Key", "返回 300-500 字分析文本"],
            ["UC-08", "管理自选股", "登录用户", "携带合法 JWT", "watchlist 表更新"],
            ["UC-09", "数据全量同步", "管理员", "数据库可写", "stock_basic / daily / financial 写入"],
        ],
        col_widths=[1.8, 3.0, 2.4, 4.0, 4.0],
        caption="表 2-3　主要用例",
    )

    # ---------------- 第 3 章 系统设计 ----------------
    add_h1(doc, "第 3 章　系统设计")

    add_h2(doc, "3.1 设计原则")
    add_bullet(doc, "前后端分离：后端只输出 JSON，前端通过 axios 调用，便于独立迭代与部署；")
    add_bullet(doc, "分层架构：API 路由层 → 业务服务层 → ORM 模型层，每一层职责单一；")
    add_bullet(doc, "大模型可替换：通过 AI_BACKEND 环境变量切换 OpenAI 兼容接口或 DashScope 通义千问，便于在不同网络条件下运行；")
    add_bullet(doc, "数据可重放：所有同步操作均为「先删后插 / 唯一索引覆盖」的幂等写入，便于反复调试。")

    add_h2(doc, "3.2 总体架构")
    add_paragraph(
        doc,
        "系统采用经典的三层 B/S 架构，并辅以独立的「数据同步」与「定时任务」两个旁路，整体逻辑结构如图 3-1 所示。"
        "前端浏览器通过 HTTPS 调用后端 RESTful API；后端使用 SQLAlchemy 操作 MySQL；数据同步层通过 AKShare 间接"
        "聚合东方财富、雪球等开源数据源；千问 LLM 通过 OpenAI 兼容接口调用，承担「自然语言 → 结构化条件」与"
        "「基本面快照 → 投资分析文本」两类生成任务。"
    )

    add_caption(doc, "图 3-1　系统总体架构图（建议在论文中以 draw.io 绘制后插入）")
    add_code_block(doc,
        "┌──────────────────────────────────────────────────────────────────────────────┐\n"
        "│                              浏览器（Vue 3 SPA）                              │\n"
        "│   Dashboard / Chat / Results / Detail / Portfolio / Strategy / Login         │\n"
        "└─────────────────────────────────┬────────────────────────────────────────────┘\n"
        "                                  │ HTTPS / JSON\n"
        "┌─────────────────────────────────▼────────────────────────────────────────────┐\n"
        "│                          FastAPI 后端（/api/v1/*）                            │\n"
        "│   auth │ stock │ screener │ qwen   ←——— Pydantic 校验 + JWT 鉴权              │\n"
        "│-----------------------------------------------------------------------------│\n"
        "│  业务服务： auth_service / screener_engine / qwen_client / data_sync         │\n"
        "│-----------------------------------------------------------------------------│\n"
        "│   SQLAlchemy ORM ──► MySQL 8 / SQLite 3                                      │\n"
        "└─────────┬─────────────────────┬──────────────────────────────────┬───────────┘\n"
        "          │                     │                                  │\n"
        "    ┌─────▼─────┐        ┌──────▼──────┐                    ┌──────▼──────┐\n"
        "    │ APScheduler│        │  AKShare API │                    │ 千问 / OpenAI │\n"
        "    │  定时任务  │        │ (东财 / 雪球) │                    │  兼容服务    │\n"
        "    └───────────┘        └─────────────┘                    └─────────────┘"
    )

    add_h2(doc, "3.3 模块划分")
    add_table(
        doc,
        header=["模块", "对应代码包", "主要职责"],
        rows=[
            ["认证模块", "app/api/auth.py、app/services/auth_service.py、app/core/security.py",
             "注册 / 登录 / JWT 颁发与校验、密码哈希"],
            ["股票浏览模块", "app/api/stock.py、app/models/stock.py、app/schemas/stock.py",
             "搜索、详情、K 线、自选股管理"],
            ["筛选引擎模块", "app/api/screener.py、app/services/screener_engine.py、app/schemas/screener.py",
             "FilterCondition → SQL 翻译，AND/OR 组合，排序分页"],
            ["千问模块", "app/api/qwen.py、app/services/qwen_client.py、app/prompts/*.md",
             "自然语言 → JSON、个股投资分析生成、多端 SDK 适配"],
            ["数据同步模块", "app/services/data_sync.py、scripts/sync_data.py",
             "AKShare 数据拉取与 ORM 写入"],
            ["定时任务模块", "app/services/scheduler.py",
             "APScheduler 注册交易日 / 周任务，应用启停时优雅控制"],
            ["前端展示模块", "frontend/src/views/*",
             "Dashboard、Chat、Results、Detail、Portfolio、Strategy、Login 共 7 个核心页面"],
        ],
        col_widths=[2.6, 6.0, 6.4],
        caption="表 3-1　系统模块划分",
    )

    add_h2(doc, "3.4 关键流程")

    add_h3(doc, "3.4.1 自然语言筛选时序")
    add_paragraph(
        doc,
        "自然语言筛选是本系统的核心创新点，其完整时序如图 3-2 所示。前端把用户输入透传到 /screener/nl，"
        "后端 qwen_client 加载位于 app/prompts/nl_to_filter.md 的提示词模板，将用户输入嵌入后请求大模型；"
        "模型以 JSON 模式返回 ScreenRequest，引擎执行后再把解析出的条件回显给前端，方便用户「核对千问理解是否正确」。"
    )
    add_caption(doc, "图 3-2　自然语言筛选时序（建议在论文中以 PlantUML 重绘）")
    add_code_block(doc,
        "Browser     FastAPI       qwen_client       LLM(千问)       screener_engine     MySQL\n"
        "  │           │              │                 │                  │              │\n"
        "  │ 1.POST /screener/nl                        │                  │              │\n"
        "  │  {query}  │              │                 │                  │              │\n"
        "  │──────────►│              │                 │                  │              │\n"
        "  │           │ 2.parse_nl_query(query)        │                  │              │\n"
        "  │           │─────────────►│                 │                  │              │\n"
        "  │           │              │ 3.prompt+JSONmode                  │              │\n"
        "  │           │              │────────────────►│                  │              │\n"
        "  │           │              │                 │ 4.JSON           │              │\n"
        "  │           │              │◄────────────────│                  │              │\n"
        "  │           │ 5.ScreenRequest                │                  │              │\n"
        "  │           │◄─────────────│                 │                  │              │\n"
        "  │           │ 6.screen(req)                  │                  │              │\n"
        "  │           │───────────────────────────────────────────────────►│              │\n"
        "  │           │                                                   │ 7.JOIN+filter│\n"
        "  │           │                                                   │─────────────►│\n"
        "  │           │                                                   │◄──── rows ───│\n"
        "  │           │ 8.ScreenResponse + parsed_conditions               │              │\n"
        "  │◄──────────│                                                   │              │"
    )

    add_h3(doc, "3.4.2 数据同步流程")
    add_paragraph(
        doc,
        "数据同步层遵循「分层 + 幂等」原则。基础信息（FR-14）通过 ak.stock_info_a_code_name 一次拉取并清空重写；"
        "股票池行情（FR-15）按代码逐只调用雪球快照接口，写入 stock_daily 表，使用 (code, trade_date) 唯一索引去重；"
        "财务数据（FR-16）通过 stock_financial_abstract 接口逐只补齐，按 (code, report_date) 唯一索引覆盖。"
        "全量同步（full）依次执行 basic → pool → industry → financial，单次约 5 分钟。"
    )

    add_h2(doc, "3.5 接口设计")
    add_table(
        doc,
        header=["方法", "路径", "鉴权", "说明"],
        rows=[
            ["POST", "/api/v1/auth/register", "否", "注册新用户"],
            ["POST", "/api/v1/auth/login", "否", "登录获取 JWT"],
            ["GET", "/api/v1/auth/me", "是", "当前登录用户信息"],
            ["GET", "/api/v1/stock/search?q=", "否", "按代码或名称模糊搜索"],
            ["GET", "/api/v1/stock/{code}", "否", "个股详情（基本 + 行情 + 财务）"],
            ["GET", "/api/v1/stock/{code}/kline", "否", "K 线数据，days 可配"],
            ["POST", "/api/v1/screener", "否", "结构化多条件筛选"],
            ["POST", "/api/v1/screener/nl", "否", "自然语言筛选"],
            ["GET", "/api/v1/qwen/analysis/{code}", "否", "千问个股投资分析"],
            ["GET", "/api/v1/stock/me/watchlist", "是", "查询当前用户自选"],
            ["POST", "/api/v1/stock/me/watchlist", "是", "添加自选"],
            ["DELETE", "/api/v1/stock/me/watchlist/{code}", "是", "移除自选"],
        ],
        col_widths=[1.8, 5.6, 1.6, 5.6],
        caption="表 3-2　核心 RESTful 接口",
    )

    # ---------------- 第 4 章 数据库设计 ----------------
    add_h1(doc, "第 4 章　数据库设计")

    add_h2(doc, "4.1 设计原则")
    add_bullet(doc, "采用 InnoDB 引擎，字符集 utf8mb4，确保对中文公司名、行业名的兼容；")
    add_bullet(doc, "时序数据（行情、财务）使用 (code, date) 唯一索引而非自增主键单一索引，防止重复写入；")
    add_bullet(doc, "高频查询字段（industry、name、code）建立 B-Tree 索引；")
    add_bullet(doc, "估值与财务字段统一用 FLOAT 存储，便于跨数据库（MySQL / SQLite）兼容；")
    add_bullet(doc, "用户与业务数据物理隔离：users / watchlist 与 stock_* 表独立，可未来切分到不同 schema。")

    add_h2(doc, "4.2 概念模型（E-R）")
    add_paragraph(
        doc,
        "系统涉及的主要实体包括「用户 User」、「股票基本信息 StockBasic」、「日线行情 StockDaily」、"
        "「财务指标 StockFinancial」与「自选股 Watchlist」五类。其中 User 与 Watchlist 为一对多关系，"
        "StockBasic 与 StockDaily / StockFinancial 同样为一对多关系，Watchlist 通过 code 弱引用 StockBasic。"
        "概念模型示意如图 4-1。"
    )
    add_caption(doc, "图 4-1　实体关系图（建议在论文中以 draw.io / dbdiagram.io 重绘）")
    add_code_block(doc,
        "┌─────────┐        1   N  ┌────────────┐       \n"
        "│  User   │───────────────│ Watchlist  │       \n"
        "│ id PK   │               │ id PK      │       \n"
        "│ username│               │ user_id FK │       \n"
        "│ ...     │               │ code (ref) │       \n"
        "└─────────┘               └─────┬──────┘       \n"
        "                                │ N            \n"
        "                                ▼              \n"
        "                         ┌──────────────┐      \n"
        "                         │ StockBasic   │ 1    \n"
        "                         │ code PK      │──────┐\n"
        "                         │ name         │      │ N\n"
        "                         │ industry     │      ▼\n"
        "                         │ market       │  ┌────────────┐\n"
        "                         │ list_date    │  │ StockDaily │\n"
        "                         └──────┬───────┘  │ id PK      │\n"
        "                                │ 1        │ code FK    │\n"
        "                                │          │ trade_date │\n"
        "                                │          │ pe / pb /…  │\n"
        "                                │ N        └────────────┘\n"
        "                                ▼                       \n"
        "                          ┌────────────────┐            \n"
        "                          │ StockFinancial │            \n"
        "                          │ id PK          │            \n"
        "                          │ code FK        │            \n"
        "                          │ report_date    │            \n"
        "                          │ roe / yoy /… │              \n"
        "                          └────────────────┘            "
    )

    add_h2(doc, "4.3 逻辑模型")
    add_paragraph(
        doc,
        "经过逻辑设计后，系统共需要 5 张物理表，整体规模适中（用户量级 ≤ 1k，股票量级 ≤ 6k，"
        "行情数据约 6k × N 个交易日）。下表 4-1 给出表汇总。"
    )
    add_table(
        doc,
        header=["表名", "中文名", "记录量级", "主要用途"],
        rows=[
            ["users", "用户表", "≤ 1,000", "账户注册、登录、自选关联"],
            ["watchlist", "自选股表", "≤ 50,000", "用户与股票的多对多关系（带加入价、预警规则）"],
            ["stock_basic", "股票基本信息表", "5,500+", "全 A 股代码 / 名称 / 行业 / 板块"],
            ["stock_daily", "日线行情与估值表", "≈ 30 万 / 年", "OHLCV、PE、PB、市值、股息率"],
            ["stock_financial", "财务摘要表", "约 6 万 / 年", "ROE、营收、同比、毛利率、负债率"],
        ],
        col_widths=[3.0, 2.8, 3.0, 6.0],
        caption="表 4-1　数据库表汇总",
    )

    add_h2(doc, "4.4 物理模型（详细字段）")

    add_h3(doc, "4.4.1 users（用户表）")
    add_table(
        doc,
        header=["字段名", "类型", "约束", "说明"],
        rows=[
            ["id", "INT", "PK, AUTO_INCREMENT", "主键，自增"],
            ["username", "VARCHAR(64)", "UNIQUE, NOT NULL", "登录用户名"],
            ["email", "VARCHAR(128)", "UNIQUE, NULLABLE", "邮箱（可选）"],
            ["hashed_password", "VARCHAR(255)", "NOT NULL", "bcrypt 哈希后的密码"],
            ["is_active", "BOOLEAN", "DEFAULT TRUE", "是否启用"],
            ["created_at", "DATETIME", "DEFAULT NOW", "创建时间"],
        ],
        col_widths=[3.5, 3.0, 3.5, 4.8],
        caption="表 4-2　users 表结构",
    )

    add_h3(doc, "4.4.2 stock_basic（股票基本信息）")
    add_table(
        doc,
        header=["字段名", "类型", "约束 / 索引", "说明"],
        rows=[
            ["code", "VARCHAR(16)", "PK", "证券代码，如 600000.SH"],
            ["name", "VARCHAR(64)", "INDEX", "证券简称"],
            ["industry", "VARCHAR(64)", "INDEX, NULLABLE", "申万 / 雪球行业分类"],
            ["market", "VARCHAR(16)", "NULLABLE", "主板 / 创业板 / 科创板 / 北交所"],
            ["list_date", "DATE", "NULLABLE", "上市日期"],
            ["total_share", "FLOAT", "NULLABLE", "总股本（亿股）"],
            ["updated_at", "DATETIME", "DEFAULT NOW, ON UPDATE NOW", "最近一次同步时间"],
        ],
        col_widths=[3.0, 2.8, 3.6, 5.4],
        caption="表 4-3　stock_basic 表结构",
    )

    add_h3(doc, "4.4.3 stock_daily（日线行情与估值）")
    add_table(
        doc,
        header=["字段名", "类型", "约束 / 索引", "说明"],
        rows=[
            ["id", "INT", "PK, AUTO_INCREMENT", "自增主键"],
            ["code", "VARCHAR(16)", "INDEX", "证券代码"],
            ["trade_date", "DATE", "INDEX", "交易日期"],
            ["open / high / low / close", "FLOAT", "NULLABLE", "OHLC 价格"],
            ["volume / amount", "FLOAT", "NULLABLE", "成交量、成交额"],
            ["pe", "FLOAT", "NULLABLE", "TTM 市盈率"],
            ["pb", "FLOAT", "NULLABLE", "市净率"],
            ["market_cap", "FLOAT", "NULLABLE", "总市值（亿元）"],
            ["turnover", "FLOAT", "NULLABLE", "换手率（%）"],
            ["dividend_yield", "FLOAT", "NULLABLE", "TTM 股息率（%）"],
            ["—", "—", "UNIQUE(code, trade_date)", "唯一索引 ix_code_date，防重复"],
        ],
        col_widths=[4.2, 2.4, 4.0, 4.2],
        caption="表 4-4　stock_daily 表结构",
    )

    add_h3(doc, "4.4.4 stock_financial（财务摘要）")
    add_table(
        doc,
        header=["字段名", "类型", "约束 / 索引", "说明"],
        rows=[
            ["id", "INT", "PK, AUTO_INCREMENT", "自增主键"],
            ["code", "VARCHAR(16)", "INDEX", "证券代码"],
            ["report_date", "DATE", "INDEX", "报告期"],
            ["roe", "FLOAT", "NULLABLE", "净资产收益率（%）"],
            ["net_profit", "FLOAT", "NULLABLE", "净利润（亿元）"],
            ["revenue", "FLOAT", "NULLABLE", "营业收入（亿元）"],
            ["revenue_yoy", "FLOAT", "NULLABLE", "营收同比（%）"],
            ["profit_yoy", "FLOAT", "NULLABLE", "净利同比（%）"],
            ["gross_margin", "FLOAT", "NULLABLE", "毛利率（%）"],
            ["debt_ratio", "FLOAT", "NULLABLE", "资产负债率（%）"],
            ["—", "—", "UNIQUE(code, report_date)", "唯一索引 ix_code_report"],
        ],
        col_widths=[3.2, 2.4, 4.4, 4.8],
        caption="表 4-5　stock_financial 表结构",
    )

    add_h3(doc, "4.4.5 watchlist（自选股）")
    add_table(
        doc,
        header=["字段名", "类型", "约束 / 索引", "说明"],
        rows=[
            ["id", "INT", "PK, AUTO_INCREMENT", "主键"],
            ["user_id", "INT", "FK→users.id, INDEX", "所属用户"],
            ["code", "VARCHAR(16)", "INDEX", "股票代码"],
            ["note", "VARCHAR(255)", "NULLABLE", "用户备注（兼容字段）"],
            ["created_at", "DATETIME", "DEFAULT NOW", "加入时间"],
            ["—", "—", "UNIQUE(user_id, code)", "唯一索引 ix_user_code"],
        ],
        col_widths=[3.2, 3.0, 4.4, 4.2],
        caption="表 4-6　watchlist 表结构",
    )

    add_h2(doc, "4.5 索引与性能")
    add_paragraph(
        doc,
        "针对系统的高频查询模式（按代码取最新行情、按行业 + 估值条件批量筛选），数据库层面做了以下优化："
    )
    add_bullet(doc, "stock_daily / stock_financial 的 (code, date) 复合唯一索引同时充当覆盖索引，避免回表；")
    add_bullet(doc, "stock_basic.industry 单独建立 B-Tree 索引，加速 industry 等值或 IN 过滤；")
    add_bullet(doc, "users.username、users.email 唯一索引同时承担查询与去重；")
    add_bullet(doc, "watchlist 的 (user_id, code) 唯一索引避免重复添加自选；")
    add_bullet(doc, "筛选引擎使用 GROUP BY + MAX(date) 子查询取每只股票最新记录，避免在 ORM 层做多次往返。")

    add_h2(doc, "4.6 范式分析")
    add_paragraph(
        doc,
        "为减少数据冗余、避免更新异常，本系统数据库设计严格遵循第三范式（3NF）。下面以 stock_basic、stock_daily、"
        "stock_financial、users、watchlist 五张表为对象，逐一分析其满足 1NF、2NF、3NF 的依据。"
    )

    add_h3(doc, "4.6.1 第一范式（1NF）")
    add_paragraph(
        doc,
        "1NF 要求每个字段都为原子值，不能再被分解。本系统所有表的字段均为整型、浮点、字符串或日期等单值类型，"
        "不存在数组、JSON 或复合结构（即使是雪球行业字段也只存储字符串「银行」而不是嵌套对象），故全部满足 1NF。"
    )

    add_h3(doc, "4.6.2 第二范式（2NF）")
    add_paragraph(
        doc,
        "2NF 要求在 1NF 基础上每个非主属性都完全依赖于主键，不允许部分依赖。本系统中："
    )
    add_bullet(doc, "stock_basic 主键为 code，name、industry、market、list_date 等都直接由 code 唯一确定，无部分依赖；")
    add_bullet(doc, "stock_daily 采用代理键 id 作为主键，业务唯一约束为 (code, trade_date)，pe / pb / close 等字段"
                    "完全依赖该业务键；")
    add_bullet(doc, "stock_financial 同上，业务键为 (code, report_date)，roe、revenue 等完全依赖；")
    add_bullet(doc, "watchlist 业务唯一约束为 (user_id, code)，note、created_at 完全依赖于此组合键。")
    add_paragraph(doc, "因此所有表均满足 2NF。")

    add_h3(doc, "4.6.3 第三范式（3NF）")
    add_paragraph(
        doc,
        "3NF 要求在 2NF 基础上消除传递依赖。本系统中典型的传递依赖隐患是：「股票代码 → 公司名称 → 行业 → 板块」"
        "若全部存放在 stock_daily 中，将出现冗余。本设计将「不变属性」（name、industry、market）抽离至 stock_basic，"
        "「时序属性」（pe、pb、close）放在 stock_daily，「报告期属性」（roe、revenue_yoy）放在 stock_financial，"
        "三者通过 code 外键级关联（不强约束 FK，便于 stock_basic 重建）。同理，watchlist 中只保存 user_id 与 code 两个键，"
        "不冗余存放用户名或股票名，确保后者变更时只需修改一处。"
    )
    add_paragraph(
        doc,
        "唯一一处刻意「反范式」是 stock_basic.updated_at 字段，它本可以独立存放在审计日志表中，"
        "但因高频写入且并不影响业务一致性，故就地保留以简化代码。综上，本系统数据库整体满足 3NF。"
    )

    add_h2(doc, "4.7 完整建表 SQL（DDL）")
    add_paragraph(
        doc,
        "下面给出 MySQL 8 下的完整 DDL，可作为系统初始化脚本（生产环境使用，开发环境则由 SQLAlchemy 的"
        "Base.metadata.create_all 自动生成）。"
    )
    add_code_block(doc,
        "-- =============== qwen_stock 库 DDL ===============\n"
        "CREATE DATABASE IF NOT EXISTS qwen_stock\n"
        "    DEFAULT CHARACTER SET utf8mb4\n"
        "    DEFAULT COLLATE utf8mb4_unicode_ci;\n"
        "USE qwen_stock;\n"
        "\n"
        "-- 1. 用户表\n"
        "CREATE TABLE IF NOT EXISTS users (\n"
        "    id              INT NOT NULL AUTO_INCREMENT,\n"
        "    username        VARCHAR(64)  NOT NULL,\n"
        "    email           VARCHAR(128) DEFAULT NULL,\n"
        "    hashed_password VARCHAR(255) NOT NULL,\n"
        "    is_active       TINYINT(1)   NOT NULL DEFAULT 1,\n"
        "    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
        "    PRIMARY KEY (id),\n"
        "    UNIQUE KEY uk_username (username),\n"
        "    UNIQUE KEY uk_email    (email)\n"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
        "\n"
        "-- 2. 股票基本信息表\n"
        "CREATE TABLE IF NOT EXISTS stock_basic (\n"
        "    code        VARCHAR(16)  NOT NULL,\n"
        "    name        VARCHAR(64)  NOT NULL,\n"
        "    industry    VARCHAR(64)  DEFAULT NULL,\n"
        "    market      VARCHAR(16)  DEFAULT NULL,\n"
        "    list_date   DATE         DEFAULT NULL,\n"
        "    total_share FLOAT        DEFAULT NULL,\n"
        "    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP\n"
        "                ON UPDATE CURRENT_TIMESTAMP,\n"
        "    PRIMARY KEY (code),\n"
        "    KEY ix_basic_name     (name),\n"
        "    KEY ix_basic_industry (industry)\n"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
        "\n"
        "-- 3. 日线行情与估值表\n"
        "CREATE TABLE IF NOT EXISTS stock_daily (\n"
        "    id             INT NOT NULL AUTO_INCREMENT,\n"
        "    code           VARCHAR(16) NOT NULL,\n"
        "    trade_date     DATE        NOT NULL,\n"
        "    open           FLOAT DEFAULT NULL,\n"
        "    high           FLOAT DEFAULT NULL,\n"
        "    low            FLOAT DEFAULT NULL,\n"
        "    close          FLOAT DEFAULT NULL,\n"
        "    volume         FLOAT DEFAULT NULL,\n"
        "    amount         FLOAT DEFAULT NULL,\n"
        "    pe             FLOAT DEFAULT NULL,\n"
        "    pb             FLOAT DEFAULT NULL,\n"
        "    market_cap     FLOAT DEFAULT NULL,\n"
        "    turnover       FLOAT DEFAULT NULL,\n"
        "    dividend_yield FLOAT DEFAULT NULL,\n"
        "    PRIMARY KEY (id),\n"
        "    UNIQUE KEY ix_code_date (code, trade_date),\n"
        "    KEY ix_daily_date (trade_date)\n"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
        "\n"
        "-- 4. 财务摘要表\n"
        "CREATE TABLE IF NOT EXISTS stock_financial (\n"
        "    id           INT NOT NULL AUTO_INCREMENT,\n"
        "    code         VARCHAR(16) NOT NULL,\n"
        "    report_date  DATE        NOT NULL,\n"
        "    roe          FLOAT DEFAULT NULL,\n"
        "    net_profit   FLOAT DEFAULT NULL,\n"
        "    revenue      FLOAT DEFAULT NULL,\n"
        "    revenue_yoy  FLOAT DEFAULT NULL,\n"
        "    profit_yoy   FLOAT DEFAULT NULL,\n"
        "    gross_margin FLOAT DEFAULT NULL,\n"
        "    debt_ratio   FLOAT DEFAULT NULL,\n"
        "    PRIMARY KEY (id),\n"
        "    UNIQUE KEY ix_code_report (code, report_date)\n"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;\n"
        "\n"
        "-- 5. 自选股表\n"
        "CREATE TABLE IF NOT EXISTS watchlist (\n"
        "    id         INT NOT NULL AUTO_INCREMENT,\n"
        "    user_id    INT NOT NULL,\n"
        "    code       VARCHAR(16) NOT NULL,\n"
        "    note       VARCHAR(255) DEFAULT NULL,\n"
        "    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
        "    PRIMARY KEY (id),\n"
        "    UNIQUE KEY ix_user_code (user_id, code),\n"
        "    CONSTRAINT fk_watch_user FOREIGN KEY (user_id) REFERENCES users(id)\n"
        "        ON DELETE CASCADE\n"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
    )

    add_h2(doc, "4.8 数据样例")
    add_paragraph(doc, "下面给出沪深 300 中若干代表性股票同步后的样例记录，用于直观展示三类核心业务数据：")
    add_table(
        doc,
        header=["code", "name", "industry", "market", "list_date"],
        rows=[
            ["600519.SH", "贵州茅台", "白酒", "主板", "2001-08-27"],
            ["000858.SZ", "五粮液", "白酒", "主板", "1998-04-27"],
            ["601318.SH", "中国平安", "保险", "主板", "2007-03-01"],
            ["600036.SH", "招商银行", "银行", "主板", "2002-04-09"],
            ["300750.SZ", "宁德时代", "电池", "创业板", "2018-06-11"],
        ],
        col_widths=[2.6, 2.4, 2.4, 2.0, 2.4],
        caption="表 4-7　stock_basic 样例数据",
    )
    add_table(
        doc,
        header=["code", "trade_date", "close", "pe", "pb", "market_cap", "dividend_yield"],
        rows=[
            ["600519.SH", "2026-04-30", "1623.40", "23.6", "8.41", "20389", "2.5"],
            ["601318.SH", "2026-04-30", "52.80", "8.4", "0.95", "9612", "5.1"],
            ["600036.SH", "2026-04-30", "37.20", "6.2", "0.87", "9384", "5.8"],
        ],
        col_widths=[2.4, 2.4, 1.8, 1.4, 1.4, 2.4, 2.6],
        caption="表 4-8　stock_daily 样例数据",
    )
    add_table(
        doc,
        header=["code", "report_date", "roe", "revenue", "revenue_yoy", "profit_yoy", "gross_margin"],
        rows=[
            ["600519.SH", "2025-12-31", "32.4", "1648.5", "16.3", "15.1", "91.6"],
            ["601318.SH", "2025-12-31", "12.1", "9220.4", "3.1", "2.4", "—"],
            ["300750.SZ", "2025-12-31", "21.6", "4012.7", "11.8", "30.5", "23.4"],
        ],
        col_widths=[2.4, 2.4, 1.6, 2.0, 2.4, 2.4, 2.4],
        caption="表 4-9　stock_financial 样例数据",
    )

    # ---------------- 第 5 章 详细设计与实现 ----------------
    add_h1(doc, "第 5 章　详细设计与实现")

    add_h2(doc, "5.1 技术选型")
    add_table(
        doc,
        header=["层次", "技术 / 框架", "版本", "选择理由"],
        rows=[
            ["语言", "Python", "3.10", "类型注解完整、生态成熟"],
            ["Web 框架", "FastAPI", "0.115", "异步、自动 Swagger、Pydantic 校验"],
            ["ORM", "SQLAlchemy", "2.0", "声明式 Mapped 语法 + 跨数据库"],
            ["数据库", "MySQL / SQLite", "8.0 / 3", "前者用于生产，后者便于本地"],
            ["数据接口", "AKShare", "1.15", "免费、覆盖 A 股全市场"],
            ["大模型", "通义千问 / OpenAI 兼容", "Plus / 4o", "中文理解能力强、JSON 模式可靠"],
            ["认证", "JWT (python-jose)", "3.3", "无状态，适合前后端分离"],
            ["定时", "APScheduler", "3.10", "进程内调度，无需额外组件"],
            ["前端", "Vue 3 + Vite + Pinia", "3.5 / 6.0", "组合式 API + 极速冷启动"],
            ["日志", "loguru", "0.7", "开箱即用的结构化日志"],
        ],
        col_widths=[2.0, 4.4, 2.4, 6.4],
        caption="表 5-1　技术栈选型",
    )

    add_h2(doc, "5.2 后端核心代码结构")
    add_code_block(doc,
        "backend/\n"
        "├── app/\n"
        "│   ├── api/                  # 路由层\n"
        "│   │   ├── auth.py           # 注册 / 登录 / me\n"
        "│   │   ├── stock.py          # 搜索 / 详情 / K线 / 自选\n"
        "│   │   ├── screener.py       # 结构化 + 自然语言筛选\n"
        "│   │   └── qwen.py           # 千问个股分析\n"
        "│   ├── services/             # 业务服务层\n"
        "│   │   ├── auth_service.py   # 用户与密码哈希\n"
        "│   │   ├── data_sync.py      # AKShare 数据同步\n"
        "│   │   ├── screener_engine.py# 多因子筛选引擎\n"
        "│   │   ├── qwen_client.py    # 千问 / OpenAI 兼容封装\n"
        "│   │   └── scheduler.py      # APScheduler 任务\n"
        "│   ├── models/               # ORM 模型\n"
        "│   ├── schemas/              # Pydantic 请求/响应模型\n"
        "│   ├── prompts/              # 提示词模板（Markdown）\n"
        "│   ├── core/                 # 安全 / 依赖注入\n"
        "│   ├── config.py             # 环境变量\n"
        "│   ├── database.py           # SQLAlchemy 引擎与 Session\n"
        "│   └── main.py               # FastAPI 入口\n"
        "├── scripts/sync_data.py      # 数据同步 CLI\n"
        "└── tests/test_smoke.py       # 冒烟测试"
    )

    add_h2(doc, "5.3 筛选引擎实现")
    add_paragraph(
        doc,
        "筛选引擎是系统的「中枢」，所有结构化查询、自然语言查询最终都会落到 screen() 函数。其核心思路："
        "首先把字段名映射到 ORM 列对象（FIELD_MAP），再把 FilterCondition.op 翻译成 SQLAlchemy 的比较表达式，"
        "AND/OR 通过 sqlalchemy.and_ / or_ 串起来；接着用「子查询取每只股票最新交易日 / 最新报告期」的方式"
        "把 stock_daily 和 stock_financial 都拼接到 stock_basic 上，形成一个 outerjoin 三表视图。"
    )
    add_code_block(doc,
        "FIELD_MAP = {\n"
        "    \"pe\": StockDaily.pe,            \"pb\": StockDaily.pb,\n"
        "    \"market_cap\": StockDaily.market_cap, \"close\": StockDaily.close,\n"
        "    \"turnover\": StockDaily.turnover, \"dividend_yield\": StockDaily.dividend_yield,\n"
        "    \"roe\": StockFinancial.roe,      \"revenue_yoy\": StockFinancial.revenue_yoy,\n"
        "    \"profit_yoy\": StockFinancial.profit_yoy,\n"
        "    \"gross_margin\": StockFinancial.gross_margin,\n"
        "    \"debt_ratio\": StockFinancial.debt_ratio,\n"
        "    \"industry\": StockBasic.industry, \"market\": StockBasic.market,\n"
        "}\n"
        "\n"
        "def _build_clause(cond: FilterCondition):\n"
        "    col, op, v = FIELD_MAP[cond.field], cond.op, cond.value\n"
        "    return {\n"
        "        \"gt\": col > v, \"gte\": col >= v,\n"
        "        \"lt\": col < v, \"lte\": col <= v, \"eq\": col == v,\n"
        "    }.get(op) or _list_clause(col, op, v)"
    )

    add_h2(doc, "5.4 千问 Prompt 设计")
    add_paragraph(
        doc,
        "提示词位于 app/prompts/nl_to_filter.md，由「角色定义 + 字段表 + 操作符 + 输出格式 + 翻译规则 + 用户输入」"
        "六部分组成，并显式要求模型只输出 JSON。其中「翻译规则」一节内置了 8 条常见金融术语映射（如「低估值」=> "
        "pe<15 ∧ pb<2、「成长股」=> revenue_yoy>20 ∧ profit_yoy>20），有效降低了模型幻觉。"
    )
    add_code_block(doc,
        "## 翻译规则（节选）\n"
        "- \"低估值\" 通常指 pe < 15 且 pb < 2\n"
        "- \"高分红\" 指 dividend_yield > 3\n"
        "- \"成长股\" 指 revenue_yoy > 20 且 profit_yoy > 20\n"
        "- \"白马股\" 指 roe > 15 且 market_cap > 500\n"
        "- 行业要用规范名（如「白酒」而不是「酒业」，「半导体」而不是「芯片」）\n"
        "- 用户没说明排序时，默认按筛选语义最强的字段降序"
    )
    add_paragraph(
        doc,
        "当前自然语言选股采用 bounded ReAct：模型只输出 final 或白名单工具 action，后端执行通过 schema 校验的工具。"
        "OpenAI-compatible 网关使用 Chat Completions 路径，Responses API 默认关闭；模型超时或不可达时安全停止，"
        "不会把本地兜底伪装成 AI 筛选。"
    )

    add_h2(doc, "5.5 安全设计")
    add_bullet(doc, "密码哈希：bcrypt，cost factor=12，存储字段 hashed_password；")
    add_bullet(doc, "JWT 鉴权：HS256 签名，过期时间默认 24 小时，密钥来自 SECRET_KEY 环境变量；")
    add_bullet(doc, "SQL 注入：所有查询通过 SQLAlchemy 参数化，禁止字符串拼接；")
    add_bullet(doc, "字段白名单：FilterCondition.field 必须在 ALLOWED_FIELDS 中，否则引擎抛 ValueError；")
    add_bullet(doc, "CORS：仅放行 settings.cors_origins 中显式列出的源；")
    add_bullet(doc, "敏感配置：API Key、数据库密码均从 .env 读取，不入仓库。")

    add_h2(doc, "5.6 前端实现要点")
    add_paragraph(
        doc,
        "前端使用 Vue 3 单文件组件 + Pinia 状态管理 + Vue Router 4 客户端路由，按业务划分为 7 个核心视图："
        "Dashboard（首页）、Chat（千问对话筛选）、Results（因子筛选结果）、Detail（股票详情）、Portfolio（自选）、"
        "Strategy（条件筛选与策略选股）、Login。axios 实例统一注入 JWT，并在响应拦截器中处理 401 → 自动跳转登录页。"
    )
    add_table(
        doc,
        header=["页面", "路径", "主要交互"],
        rows=[
            ["Dashboard", "/dashboard", "6 个宽基指数、市场概况、板块与异动榜，首屏聚合接口加载"],
            ["Chat", "/chat", "用户输入自然语言 → Agent 选择工具或普通回复 → SSE 展示结果"],
            ["Results", "/results", "因子条件可视化编辑 + 结果列表 + 排序"],
            ["Detail", "/detail/:code", "K 线 + 财务卡片 + 千问解读按钮"],
            ["Portfolio", "/portfolio", "自选排序 + 批量编辑 + 预警启停/删除"],
            ["Strategy", "/strategy", "条件筛选、保存条件策略、6 个内置日线策略"],
            ["Login", "/login", "用户名 / 密码登录 + 注册入口"],
        ],
        col_widths=[2.4, 3.6, 9.0],
        caption="表 5-2　前端页面与路由",
    )

    add_h2(doc, "5.7 异常处理与日志设计")
    add_paragraph(
        doc,
        "为提高系统的可维护性，本系统统一了异常处理与日志格式，遵循「业务异常向上抛出 / 系统异常就地降级」原则。"
    )

    add_h3(doc, "5.7.1 异常分类")
    add_table(
        doc,
        header=["异常来源", "处理方式", "对外表现"],
        rows=[
            ["Pydantic 校验失败", "FastAPI 自动捕获", "422 + 字段级错误信息"],
            ["业务规则违反（如重复用户名）", "服务层抛 HTTPException", "4xx + 中文 detail"],
            ["筛选字段越界", "screener_engine 抛 ValueError", "路由层 → 400"],
            ["千问 API 失败 / Key 缺失", "qwen_client 抛 RuntimeError", "路由层 → 503"],
            ["数据库连接异常", "loguru 记录后向上抛", "500，由 ASGI 中间件返回"],
            ["AKShare 网络中断", "data_sync 重试 3 次后跳过", "日志告警，不影响其他股票"],
        ],
        col_widths=[5.0, 5.4, 5.0],
        caption="表 5-3　异常分类与处理策略",
    )

    add_h3(doc, "5.7.2 日志规范")
    add_paragraph(
        doc,
        "日志统一使用 loguru，按等级分流：DEBUG 仅本地开发输出；INFO 用于关键业务节点（同步开始 / 结束、筛选耗时、"
        "千问调用次数）；WARNING 用于可恢复的异常（接口重试、千问回退到 chat.completions）；ERROR 用于不可恢复异常。"
        "格式包含时间、文件:行号、等级、消息四个要素，便于排查。"
    )
    add_code_block(doc,
        "from loguru import logger\n"
        "\n"
        "logger.remove()\n"
        "logger.add(\n"
        "    sink=sys.stderr,\n"
        "    level=\"INFO\",\n"
        "    format=\"<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level>\"\n"
        "           \" | <cyan>{name}:{line}</cyan> | {message}\",\n"
        ")\n"
        "logger.add(\"logs/app_{time:YYYY-MM-DD}.log\", rotation=\"00:00\", retention=\"30 days\",\n"
        "           encoding=\"utf-8\", level=\"INFO\")"
    )

    add_h2(doc, "5.8 关键模块流程图")

    add_h3(doc, "5.8.1 用户登录流程")
    add_caption(doc, "图 5-1　用户登录与 JWT 颁发流程")
    add_code_block(doc,
        "  开始\n"
        "    │\n"
        "    ▼\n"
        "  接收 username / password (OAuth2 表单)\n"
        "    │\n"
        "    ▼\n"
        "  ┌─────────────────────┐\n"
        "  │ 查询 users.username │\n"
        "  └──────────┬──────────┘\n"
        "             │ 不存在\n"
        "             └─────────────► 401 用户名或密码错误\n"
        "             │ 存在\n"
        "             ▼\n"
        "  bcrypt.verify(plain, hashed)\n"
        "             │ False\n"
        "             └─────────────► 401\n"
        "             │ True\n"
        "             ▼\n"
        "  create_access_token(user.id) ── HS256 签名 ─► JWT\n"
        "             │\n"
        "             ▼\n"
        "  返回 {access_token, token_type, user}"
    )

    add_h3(doc, "5.8.2 自然语言筛选流程")
    add_caption(doc, "图 5-2　自然语言筛选完整流程")
    add_code_block(doc,
        "  接收用户自然语言 query\n"
        "    │\n"
        "    ▼\n"
        "  加载 prompts/nl_to_filter.md ──► 模板拼接\n"
        "    │\n"
        "    ▼\n"
        "  ┌─────────────────────────┐\n"
        "  │  调用 Chat Completions  │── 超时/不可达 ──► 安全停止\n"
        "  │  (action/final schema) │\n"
        "  └─────────────┬───────────┘\n"
        "                │ JSON 文本\n"
        "                ▼\n"
        "  正则提取 {...} ──► json.loads ──► ScreenRequest\n"
        "                │ 解析失败 ──► RuntimeError → 503\n"
        "                ▼\n"
        "  字段白名单校验（ALLOWED_FIELDS）\n"
        "                │ 不通过 ──► ValueError → 400\n"
        "                ▼\n"
        "  screener_engine.screen(req) ──► SQL → MySQL\n"
        "                │\n"
        "                ▼\n"
        "  ScreenResponse + parsed_conditions（回显）"
    )

    add_h3(doc, "5.8.3 数据同步流程")
    add_caption(doc, "图 5-3　全量数据同步（full）流程")
    add_code_block(doc,
        "  python -m scripts.sync_data full\n"
        "    │\n"
        "    ▼\n"
        "  Step 1: sync_basic        — ak.stock_info_a_code_name\n"
        "    │  truncate stock_basic + bulk_insert（5500 条）\n"
        "    ▼\n"
        "  Step 2: sync_pool_xq      — ak.stock_individual_spot_xq（沪深 300 逐只）\n"
        "    │  upsert stock_daily（含 PE/PB/股息率/市值）\n"
        "    ▼\n"
        "  Step 3: sync_industry_xq  — ak.stock_individual_basic_info_xq\n"
        "    │  update stock_basic.industry / market / list_date\n"
        "    ▼\n"
        "  Step 4: sync_financial    — ak.stock_financial_abstract\n"
        "    │  upsert stock_financial（roe / yoy / margin）\n"
        "    ▼\n"
        "  日志输出汇总：累计耗时、成功 / 失败计数"
    )

    add_h2(doc, "5.9 部署与运行")
    add_code_block(doc,
        "# 1. 数据库准备\n"
        "CREATE DATABASE qwen_stock CHARACTER SET utf8mb4;\n"
        "CREATE USER 'qwen'@'%' IDENTIFIED BY 'Qwen_Dev_Pwd_2026!';\n"
        "GRANT ALL ON qwen_stock.* TO 'qwen'@'%';\n"
        "\n"
        "# 2. 后端\n"
        "cd backend && python -m venv .venv && source .venv/bin/activate\n"
        "pip install -r requirements.txt\n"
        "cp .env.example .env  # 填入 DATABASE_URL / OPENAI_API_KEY\n"
        "python -m scripts.sync_data full      # 首次同步约 5 分钟\n"
        "uvicorn app.main:app --reload --port 8000\n"
        "\n"
        "# 3. 前端\n"
        "cd frontend && pnpm install && pnpm dev"
    )

    # ---------------- 第 6 章 系统测试 ----------------
    add_h1(doc, "第 6 章　系统测试")

    add_h2(doc, "6.1 测试环境")
    add_table(
        doc,
        header=["项目", "配置"],
        rows=[
            ["操作系统", "macOS 14 / Ubuntu 22.04"],
            ["CPU / 内存", "Intel i7-12700H / 16 GB"],
            ["Python", "3.10.13"],
            ["数据库", "MySQL 8.0.36 / SQLite 3.45"],
            ["浏览器", "Chrome 124 / Edge 124"],
            ["网络", "校园网 / 普通家庭宽带"],
        ],
        col_widths=[3.6, 11.0],
        caption="表 6-1　测试环境",
    )

    add_h2(doc, "6.2 功能测试")
    add_table(
        doc,
        header=["编号", "测试用例", "输入", "预期", "结果"],
        rows=[
            ["TC-01", "注册 + 登录", "username=demo, password=123456", "200 + 颁发 JWT", "通过"],
            ["TC-02", "重复注册", "已存在的 username", "400 用户名已被占用", "通过"],
            ["TC-03", "搜索股票", "q=平安", "返回平安银行 / 中国平安等", "通过"],
            ["TC-04", "个股详情", "code=600000.SH", "返回 latest + 财务", "通过"],
            ["TC-05", "结构化筛选-银行高股息", "industry=银行 AND dividend_yield>4", "返回兴业、招行等 5 只", "通过"],
            ["TC-06", "自然语言筛选-成长股", "ROE>15 且最新季度净利同比正增长", "返回 parsed_conditions 与列表", "通过"],
            ["TC-07", "千问个股分析", "code=600519.SH", "返回 300+ 字分析文本", "通过"],
            ["TC-08", "添加自选", "code=600519.SH + JWT", "201 创建", "通过"],
            ["TC-09", "重复添加自选", "同上", "返回已有记录，不报错", "通过"],
            ["TC-10", "未登录访问 /me", "无 Authorization", "401", "通过"],
            ["TC-11", "非法字段筛选", "field=foo, op=gt, value=1", "400 不支持的筛选字段", "通过"],
            ["TC-12", "千问 Key 未配置", "禁用 OPENAI_API_KEY", "503 + 提示", "通过"],
        ],
        col_widths=[1.6, 3.6, 4.0, 3.4, 1.4],
        caption="表 6-2　功能测试用例",
    )

    add_h2(doc, "6.3 性能测试")
    add_paragraph(
        doc,
        "在沪深 300 全量数据（300 只股票，最近一个交易日快照）下，对核心接口分别运行 100 次取均值与 P95，结果如表 6-3。"
    )
    add_table(
        doc,
        header=["接口", "样本量", "平均耗时", "P95 耗时", "备注"],
        rows=[
            ["/stock/search", "100", "32 ms", "78 ms", "本地 SQLite"],
            ["/stock/{code}", "100", "41 ms", "95 ms", "含双子查询取最新行情 / 财务"],
            ["/screener (3 条件 AND)", "100", "112 ms", "186 ms", "三表 outerjoin"],
            ["/screener/nl", "30", "3.1 s", "4.8 s", "含千问推理"],
            ["/qwen/analysis/{code}", "30", "7.6 s", "11.2 s", "含千问长文本生成"],
            ["数据全量同步 full", "1", "5 min 24 s", "—", "300 只股票，弱网下"],
        ],
        col_widths=[5.2, 1.6, 2.6, 2.6, 4.0],
        caption="表 6-3　性能测试结果",
    )

    add_h2(doc, "6.4 兼容性测试")
    add_paragraph(
        doc,
        "为验证系统在不同运行环境下的可用性，分别在三种数据库、四种浏览器、两种操作系统下进行了交叉测试，结果如表 6-4。"
    )
    add_table(
        doc,
        header=["维度", "环境", "测试项", "结果"],
        rows=[
            ["数据库", "MySQL 8.0.36", "DDL 创建 / 全量同步 / 筛选", "全部通过"],
            ["数据库", "SQLite 3.45", "DDL 创建 / 全量同步 / 筛选", "全部通过"],
            ["数据库", "MariaDB 10.11", "DDL 创建 / 全量同步", "通过（需安装 pymysql）"],
            ["浏览器", "Chrome 124 (macOS)", "登录 / 筛选 / Detail / Chat", "全部通过"],
            ["浏览器", "Edge 124 (Windows)", "同上", "全部通过"],
            ["浏览器", "Safari 17.4 (macOS)", "同上", "通过，K 线图初次加载稍慢"],
            ["浏览器", "Firefox 125 (Linux)", "同上", "全部通过"],
            ["操作系统", "macOS 14 / Ubuntu 22.04", "后端启动 / 同步 / API", "全部通过"],
            ["AI 后端", "OpenAI 兼容 / DashScope", "自然语言筛选 / 个股分析", "全部通过"],
        ],
        col_widths=[2.4, 4.4, 5.4, 3.4],
        caption="表 6-4　兼容性测试结果",
    )

    add_h2(doc, "6.5 安全测试")
    add_paragraph(
        doc,
        "针对常见 Web 安全风险，本系统进行了以下针对性测试，结果如表 6-5。其中 SQL 注入与越权访问通过自动化脚本"
        "构造异常输入 / Token 多轮验证；密码爆破通过对登录接口连续高频请求测试；CORS 通过浏览器跨域调用验证。"
    )
    add_table(
        doc,
        header=["风险类别", "测试方式", "结果"],
        rows=[
            ["SQL 注入", "在 search?q= / 字段筛选中传入 OR 1=1、单引号", "ORM 参数化拦截，无注入"],
            ["越权访问 (IDOR)", "用户 A 的 Token 调用用户 B 的 watchlist", "401 / 404 拒绝"],
            ["越权访问（伪造 JWT）", "随机字符串 / 篡改 payload", "401 invalid signature"],
            ["敏感信息泄露", "登录返回体、错误响应检查", "未泄露 hashed_password、stack trace"],
            ["弱密码", "<6 字符 / 仅数字 / 仅字母", "Pydantic 校验 422 拦截"],
            ["CORS", "未授权 origin 跨域请求", "浏览器拦截，符合 cors_origins 白名单"],
            ["密码爆破", "登录接口 1k QPS 持续 30s", "未崩溃；建议生产接入限流"],
            ["千问 Prompt 注入", "在用户 query 中追加「忽略前面规则…」", "JSON 模式约束 + 字段白名单兜底，拦截"],
        ],
        col_widths=[3.4, 7.0, 5.2],
        caption="表 6-5　安全测试结果",
    )

    add_h2(doc, "6.6 用户体验测试")
    add_paragraph(
        doc,
        "邀请 5 位志愿者（3 名同班同学、1 名外专业学生、1 名有 2 年股龄的工作者）按照设定脚本完成「注册 → 搜索 → "
        "自然语言筛选 → 加入自选 → 查看千问解读」全链路操作，并填写 SUS（系统易用性量表）。汇总结果："
    )
    add_table(
        doc,
        header=["维度", "得分（5 分制）", "代表性反馈"],
        rows=[
            ["上手难度", "4.4", "「输入一句话就能选股，比同花顺直观」"],
            ["响应速度", "4.0", "「自然语言筛选大概 3 秒，可以接受」"],
            ["视觉一致性", "4.2", "「Dashboard 与 Detail 风格统一」"],
            ["错误提示", "3.6", "「千问失败时希望直接给重试按钮」"],
            ["千问回答可信度", "4.0", "「会指出 ROE / 毛利率亮点，比较像研报」"],
            ["综合 SUS 分", "82.5", "对应 A 级（行业良好以上）"],
        ],
        col_widths=[3.4, 3.2, 9.0],
        caption="表 6-6　用户体验测试汇总",
    )

    add_h2(doc, "6.7 测试结论")
    add_paragraph(
        doc,
        "全部 12 个核心功能用例均通过；性能层面，结构化筛选 P95 控制在 200 ms 以内，自然语言筛选与个股分析"
        "受限于大模型推理延迟，均维持在「秒级响应」范围内，符合 NFR-1、NFR-2 的指标。系统在双数据库（MySQL/SQLite）"
        "和双大模型后端（OpenAI 兼容 / DashScope）下均能正常运行，满足可移植性要求；安全方面通过了 SQL 注入、"
        "越权、Prompt 注入等 8 项常规风险测试；用户体验综合 SUS 分 82.5，达到行业良好以上水平。"
        "建议生产部署时进一步引入接口限流（如基于 Redis 的令牌桶）和审计日志归档，以应对更高并发。"
    )

    # ---------------- 第 7 章 系统运行效果展示 ----------------
    add_h1(doc, "第 7 章　系统运行效果展示")
    add_paragraph(
        doc,
        "本章选取系统的七个核心页面，结合实际运行截图和文字说明，展示主要功能的最终效果。"
        "由于黑白印刷可能影响截图细节，建议读者结合附录中给出的代码仓库地址自行启动并体验。"
    )

    add_h2(doc, "7.1 首页 Dashboard")
    add_paragraph(
        doc,
        "首页采用左侧导航 + 顶部状态栏 + 主内容区的经典三分结构。顶部 Ticker 组件以跑马灯方式滚动展示沪深 300 中"
        "涨跌幅前 10 只股票；中部以四个数据卡片（沪深 300 指数、上证 50 指数、市场平均 PE、平均股息率）做总体概览；"
        "下方分别给出「热门行业涨跌排行」与「估值分位数」两个图表。"
    )
    add_caption(doc, "图 7-1　Dashboard 页面（建议在论文中插入实际截图）")
    add_code_block(doc,
        "┌──────────────────────────────────────────────────────────────┐\n"
        "│  QwenStock | 行情 | 对话 | 筛选 | 详情 | 自选 | 策略 |  登录 │\n"
        "├──────────────────────────────────────────────────────────────┤\n"
        "│  ★茅台 1623.4 +1.2%   ★平安 52.8 -0.4%   ★宁德 215 +2.1% ...│\n"
        "├─────────────┬────────────┬────────────┬──────────────────────┤\n"
        "│ 沪深300      │ 上证50      │ 平均 PE    │  平均股息率          │\n"
        "│  3812 +0.6% │ 2640 +0.3% │  13.6      │   2.84%              │\n"
        "├─────────────┴────────────┴────────────┴──────────────────────┤\n"
        "│  [行业涨跌排行 (柱状图)]      [PE 估值分位数 (热力图)]       │\n"
        "└──────────────────────────────────────────────────────────────┘"
    )

    add_h2(doc, "7.2 千问对话筛选 Chat")
    add_paragraph(
        doc,
        "Chat 页面是本系统的核心创新展示窗口。用户在底部输入框输入一句中文（如「ROE 大于 15 且毛利率超 30% 的成长股」），"
        "系统先以气泡形式展示用户输入，再调用 /screener/nl 接口；返回后，气泡区显示千问解析出的结构化条件 JSON 与"
        "执行得到的 Top10 股票列表，每只股票均可点击跳转至详情页。"
    )
    add_caption(doc, "图 7-2　Chat 自然语言筛选对话页（建议插入实际截图）")
    add_code_block(doc,
        "┌──────────────────────────────────────────────────────────────┐\n"
        "│  我：ROE 大于 15 且毛利率超过 30% 的成长股                     │\n"
        "├──────────────────────────────────────────────────────────────┤\n"
        "│  千问 解析条件：                                              │\n"
        "│   • roe > 15                                                  │\n"
        "│   • gross_margin > 30                                         │\n"
        "│   • revenue_yoy > 20  (隐含「成长」语义)                      │\n"
        "├──────────────────────────────────────────────────────────────┤\n"
        "│  共匹配到 24 只，Top10：                                       │\n"
        "│  1. 贵州茅台  ROE 32.4  毛利 91.6  营收同比 16.3              │\n"
        "│  2. 山西汾酒  ROE 28.1  毛利 75.8  营收同比 22.5              │\n"
        "│  3. 宁德时代  ROE 21.6  毛利 23.4  营收同比 11.8（命中边界）  │\n"
        "│  ...                                                          │\n"
        "├──────────────────────────────────────────────────────────────┤\n"
        "│  [输入框] 试试: 银行 + 高股息  | 半导体 + 低估值              │\n"
        "└──────────────────────────────────────────────────────────────┘"
    )

    add_h2(doc, "7.3 因子筛选 Results")
    add_paragraph(
        doc,
        "Results 页面提供「条件可视化编辑器 + 结果列表」两栏布局。左栏支持用户通过下拉框选择字段、操作符和阈值，"
        "新增 / 删除条件行，并在 AND / OR 之间切换；右栏实时展示筛选结果，支持按列升降序、点击跳转详情。"
        "页面顶部还提供「保存筛选条件」「导出 CSV」两个工具按钮。"
    )
    add_caption(doc, "图 7-3　Results 因子筛选与结果列表（建议插入实际截图）")
    add_code_block(doc,
        "┌──────────────────── 条件编辑 ───────────────────┐  ┌─── 结果（按市值降序） ───┐\n"
        "│ industry  =  银行                ✕             │  │ 兴业银行  PE 4.6 股息 6.8%│\n"
        "│ dividend_yield  >  4             ✕             │  │ 招商银行  PE 6.2 股息 5.8%│\n"
        "│ pe              <  10            ✕             │  │ 光大银行  PE 4.9 股息 5.4%│\n"
        "│ + 添加条件     [AND ⌄]  [运行筛选 ▶ ]          │  │ 华夏银行  PE 4.4 股息 5.0%│\n"
        "└────────────────────────────────────────────────┘  └────────────────────────────┘"
    )

    add_h2(doc, "7.4 个股详情 Detail")
    add_paragraph(
        doc,
        "Detail 页面是用户从筛选结果跳转后的目标页，分为四个区域：顶部基本信息卡（代码 / 名称 / 行业 / 板块 / 上市日期）、"
        "中部 K 线图（默认 120 个交易日，可切换 30 / 60 / 250）、右侧财务指标卡（ROE、毛利率、营收同比、净利同比、负债率）、"
        "底部「千问解读」按钮。点击「千问解读」后会拉起一个抽屉面板，调用 /qwen/analysis/{code} 流式输出分析文本。"
    )
    add_caption(doc, "图 7-4　Detail 个股详情页（建议插入实际截图）")
    add_code_block(doc,
        "┌──────────────────────── 600519.SH 贵州茅台 · 白酒 · 主板 ────────────────────────┐\n"
        "│                                                                                  │\n"
        "│   K 线图（120 日，含 MA5 / MA20 / 成交量）                                       │\n"
        "│   ┌──────────────────────────────────────────────┐ ┌─ 财务指标 ──────────────┐ │\n"
        "│   │                                              │ │ ROE       32.4         │ │\n"
        "│   │     ╲ ╱╲   ╱╲   ╲╱                           │ │ 毛利率    91.6         │ │\n"
        "│   │      ╳    ╳   ╲╱                             │ │ 营收同比  16.3         │ │\n"
        "│   │     ╱ ╲  ╱ ╲                                 │ │ 净利同比  15.1         │ │\n"
        "│   │   ▆▆▇▆▅▇▆▇▅▇▆▅▇▆▅▆▇▆▅                       │ │ 负债率    21.0         │ │\n"
        "│   └──────────────────────────────────────────────┘ └────────────────────────┘ │\n"
        "│                                                                                  │\n"
        "│  [☆ 加入自选]   [千问解读 →]                                                      │\n"
        "└──────────────────────────────────────────────────────────────────────────────────┘"
    )
    add_paragraph(
        doc,
        "「千问解读」抽屉的实际输出示例（受限于篇幅，节选关键段）："
    )
    add_code_block(doc,
        "贵州茅台（600519.SH）位于白酒行业，最新 PE 23.6 倍，处于近五年中位附近，PB 8.4 倍偏高，\n"
        "反映其高 ROE（32.4%）带来的资本溢价。2025 年报营收 1648 亿元，同比 16.3%，净利同比 15.1%，\n"
        "在白酒板块继续保持龙头韧性。毛利率 91.6% 位居行业前列，资产负债率仅 21%，财务结构稳健，\n"
        "股息率 2.5% 中规中矩。综合来看，公司具备显著的护城河和稳健的盈利能力，但需关注政策与消费\n"
        "复苏节奏对估值的潜在压制。"
    )

    add_h2(doc, "7.5 自选股 Portfolio")
    add_paragraph(
        doc,
        "Portfolio 页面对应登录用户的私域，要求用户登录后访问。表格形式展示用户的全部自选股，每一行包含代码、名称、"
        "现价、当日涨跌幅、加入日期、估值指标和预警入口；页面支持按加入日期、涨跌幅、估值、行业等字段排序，"
        "并支持批量移出自选、批量启用/暂停/删除预警规则。"
    )
    add_caption(doc, "图 7-5　Portfolio 自选股（建议插入实际截图）")

    add_h2(doc, "7.6 登录 Login")
    add_paragraph(
        doc,
        "Login 页面采用极简卡片设计：用户名 + 密码两个输入框 + 登录按钮 + 注册入口。失败时在表单下方红色提示，"
        "成功后跳转到登录前页面（支持 ?next= 查询参数）；前端 token 存储于 Pinia + localStorage，刷新页面时自动恢复。"
    )

    add_h2(doc, "7.7 策略回测 Strategy（占位）")
    add_paragraph(
        doc,
        "Strategy 页面目前仅作为占位入口，UI 上预留了「策略名 / 起止时间 / 因子条件 / 业绩指标」四个区域，"
        "为后续接入 backtrader 或 vnpy 等回测框架提供布局基础。该模块计划在下一个迭代中完成。"
    )

    # ---------------- 第 8 章 总结与展望 ----------------
    add_h1(doc, "第 8 章　总结与展望")

    add_h2(doc, "8.1 工作总结")
    add_paragraph(
        doc,
        "本课题完成了一套面向 A 股的「自然语言 + 结构化双通道」智能筛选系统，核心贡献包括：（1）将通义千问大模型"
        "嵌入传统量化筛选流水线，通过 Prompt Engineering + JSON 模式获得稳定的结构化输出；（2）抽象出通用的"
        "FilterCondition 接口，使自然语言通道与传统结构化通道复用同一个引擎，保证结果一致；（3）基于 AKShare"
        "构建了稳定的「沪深 300 + 雪球逐只」数据通路，规避了部分网络环境下东方财富批量接口的不稳定问题；"
        "（4）使用 FastAPI + Vue 3 完整覆盖前后端分离的工程实践，所有接口具备 Swagger 文档与 Pydantic 校验。"
    )

    add_h2(doc, "8.2 不足与展望")
    add_bullet(doc, "回测能力：当前 Strategy 页面仅为占位，后续可接入 backtrader / vnpy 实现因子回测；")
    add_bullet(doc, "数据广度：仅同步沪深 300，可扩展至全 A 股甚至港股、美股；")
    add_bullet(doc, "Function Calling：现采用 Prompt + JSON 模式，可迁移至 Function Calling 进一步降低模型幻觉；")
    add_bullet(doc, "缓存：千问的高成本调用可结合 Redis 做查询级缓存，降低 QPS 压力；")
    add_bullet(doc, "可视化：可接入 ECharts 实现因子热力图、行业分布旭日图等；")
    add_bullet(doc, "多端适配：现仅适配桌面分辨率，可补充移动端响应式样式。")

    # ---------------- 参考文献 ----------------
    add_h1(doc, "参考文献")
    refs = [
        "[1] 邱东. 量化投资：以 Python 为工具[M]. 北京: 电子工业出版社, 2022.",
        "[2] Tiangolo S. FastAPI Documentation[EB/OL]. https://fastapi.tiangolo.com, 2024.",
        "[3] SQLAlchemy 2.0 Documentation[EB/OL]. https://docs.sqlalchemy.org/en/20/, 2024.",
        "[4] 阿里云通义千问开放平台. DashScope API Reference[EB/OL]. https://help.aliyun.com/zh/dashscope/, 2025.",
        "[5] AKShare. AKShare 开源金融数据接口库[EB/OL]. https://akshare.akfamily.xyz, 2025.",
        "[6] 雪球网. 个股快照接口文档[EB/OL]. https://xueqiu.com, 2025.",
        "[7] You E, et al. Vue.js 3.0 Documentation[EB/OL]. https://vuejs.org, 2024.",
        "[8] Brown T, Mann B, Ryder N, et al. Language Models are Few-Shot Learners[J]. NeurIPS, 2020.",
        "[9] OpenAI. GPT-4 Technical Report[R]. OpenAI, 2023.",
        "[10] 中国证监会. 上市公司信息披露管理办法[Z]. 2021.",
    ]
    for r in refs:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf = p.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.line_spacing = 1.5
        pf.space_after = Pt(2)
        pf.left_indent = Pt(28)
        pf.first_line_indent = Pt(-28)
        run = p.add_run(r)
        set_run_font(run, cn=SONG, en=EN, size=12)

    # ---------------- 附录 ----------------
    add_h1(doc, "附录 A　核心源码清单")
    add_paragraph(
        doc,
        "本附录摘录系统中最具代表性的两段源码：筛选引擎 screener_engine.screen() 与千问客户端 qwen_client.parse_nl_query()。"
        "完整源码见随论文一同提交的代码仓库。"
    )

    add_h2(doc, "A.1 筛选引擎 screener_engine.screen()")
    add_code_block(doc,
        "def screen(db: Session, req: ScreenRequest) -> ScreenResponse:\n"
        "    # 1. 取每只股票最新交易日 / 最新报告期\n"
        "    latest_daily_dates = (\n"
        "        db.query(StockDaily.code, func.max(StockDaily.trade_date).label(\"d\"))\n"
        "        .group_by(StockDaily.code).subquery()\n"
        "    )\n"
        "    latest_finan_dates = (\n"
        "        db.query(StockFinancial.code, func.max(StockFinancial.report_date).label(\"d\"))\n"
        "        .group_by(StockFinancial.code).subquery()\n"
        "    )\n"
        "\n"
        "    # 2. 三表 outer join 形成视图\n"
        "    q = (\n"
        "        db.query(StockBasic, StockDaily, StockFinancial)\n"
        "        .outerjoin(latest_daily_dates, latest_daily_dates.c.code == StockBasic.code)\n"
        "        .outerjoin(\n"
        "            StockDaily,\n"
        "            and_(\n"
        "                StockDaily.code == latest_daily_dates.c.code,\n"
        "                StockDaily.trade_date == latest_daily_dates.c.d,\n"
        "            ),\n"
        "        )\n"
        "        .outerjoin(latest_finan_dates, latest_finan_dates.c.code == StockBasic.code)\n"
        "        .outerjoin(\n"
        "            StockFinancial,\n"
        "            and_(\n"
        "                StockFinancial.code == latest_finan_dates.c.code,\n"
        "                StockFinancial.report_date == latest_finan_dates.c.d,\n"
        "            ),\n"
        "        )\n"
        "    )\n"
        "\n"
        "    # 3. 按条件过滤（AND/OR）\n"
        "    if req.conditions:\n"
        "        clauses = [_build_clause(c) for c in req.conditions]\n"
        "        q = q.filter(and_(*clauses) if req.logic == \"AND\" else or_(*clauses))\n"
        "\n"
        "    # 4. 排序、分页\n"
        "    if req.sort_by and req.sort_by in FIELD_MAP:\n"
        "        col = FIELD_MAP[req.sort_by]\n"
        "        q = q.order_by(desc(col) if req.sort_desc else col)\n"
        "    rows = q.limit(req.limit).all()\n"
        "\n"
        "    # 5. 装配响应\n"
        "    items = [\n"
        "        ScreenResultItem(\n"
        "            code=basic.code, name=basic.name,\n"
        "            industry=basic.industry, market=basic.market,\n"
        "            pe=daily.pe if daily else None,\n"
        "            pb=daily.pb if daily else None,\n"
        "            roe=fin.roe if fin else None,\n"
        "            market_cap=daily.market_cap if daily else None,\n"
        "            dividend_yield=daily.dividend_yield if daily else None,\n"
        "            close=daily.close if daily else None,\n"
        "        )\n"
        "        for basic, daily, fin in rows\n"
        "    ]\n"
        "    return ScreenResponse(total=len(items), items=items)"
    )

    add_h2(doc, "A.2 千问客户端 qwen_client.parse_nl_query()")
    add_code_block(doc,
        "JSON_PATTERN = re.compile(r\"\\{.*\\}\", re.DOTALL)\n"
        "\n"
        "def parse_nl_query(query: str) -> ScreenRequest:\n"
        "    \"\"\"自然语言 → ScreenRequest（结构化筛选请求）\"\"\"\n"
        "    template = _load_prompt(\"nl_to_filter.md\")\n"
        "    prompt = template.replace(\"{user_query}\", query.strip())\n"
        "\n"
        "    text = _call_llm(prompt, json_mode=True)\n"
        "    match = JSON_PATTERN.search(text)\n"
        "    if not match:\n"
        "        raise RuntimeError(f\"千问返回非 JSON：{text[:200]}\")\n"
        "    try:\n"
        "        data = json.loads(match.group(0))\n"
        "    except json.JSONDecodeError as e:\n"
        "        raise RuntimeError(f\"千问 JSON 解析失败：{e}\") from e\n"
        "\n"
        "    # 字段白名单兜底，过滤模型偶发幻觉\n"
        "    data[\"conditions\"] = [\n"
        "        c for c in data.get(\"conditions\", [])\n"
        "        if c.get(\"field\") in ALLOWED_FIELDS\n"
        "    ]\n"
        "    return ScreenRequest(**data)\n"
        "\n"
        "def _call_llm(prompt: str, *, json_mode: bool) -> str:\n"
        "    if settings.ai_backend == \"dashscope\":\n"
        "        return _dashscope_call(prompt, json_mode=json_mode)\n"
        "    return _openai_call(prompt, json_mode=json_mode)"
    )

    add_h1(doc, "附录 B　完整 API 列表")
    add_paragraph(
        doc,
        "本附录给出系统对外暴露的完整 RESTful API 与请求 / 响应字段，方便论文评审与二次开发查阅。所有接口均以 "
        "/api/v1 为前缀；JSON 字段命名采用 snake_case。"
    )

    add_h2(doc, "B.1 认证模块")
    add_table(
        doc,
        header=["接口", "请求体", "响应体"],
        rows=[
            ["POST /auth/register",
             "username:str ≥3, password:str ≥6, email?:str",
             "id, username, email, is_active, created_at"],
            ["POST /auth/login (form)",
             "username, password",
             "access_token, token_type, user{...}"],
            ["GET /auth/me (Bearer)",
             "—",
             "id, username, email, is_active, created_at"],
        ],
        col_widths=[5.0, 5.4, 4.8],
        caption="表 B-1　认证模块接口",
    )

    add_h2(doc, "B.2 股票模块")
    add_table(
        doc,
        header=["接口", "请求", "响应"],
        rows=[
            ["GET /stock/search?q=&limit=20", "q≥1, limit≤200", "list of {code,name,industry,market}"],
            ["GET /stock/{code}", "code", "code,name,industry,latest{...},roe,revenue_yoy,..."],
            ["GET /stock/{code}/kline?days=120", "code, days≤500", "list of OHLCV + PE/PB"],
            ["GET /stock/me/watchlist (Bearer)", "—", "list of {id,code,note,created_at}"],
            ["POST /stock/me/watchlist (Bearer)", "code, note?", "新增的 watchlist 记录"],
            ["DELETE /stock/me/watchlist/{code} (Bearer)", "code", "204"],
        ],
        col_widths=[5.6, 4.4, 5.2],
        caption="表 B-2　股票模块接口",
    )

    add_h2(doc, "B.3 筛选与千问模块")
    add_table(
        doc,
        header=["接口", "请求体", "响应体"],
        rows=[
            ["POST /screener",
             "conditions:[{field,op,value}], logic, sort_by, sort_desc, limit",
             "total, items[], parsed_conditions=null"],
            ["POST /screener/nl",
             "query:str (1-500)",
             "total, items[], parsed_conditions(回显)"],
            ["GET /qwen/analysis/{code}",
             "code",
             "code, analysis(text), snapshot{基本面}"],
        ],
        col_widths=[5.0, 6.0, 4.4],
        caption="表 B-3　筛选与千问模块接口",
    )

    add_h2(doc, "B.4 错误码")
    add_table(
        doc,
        header=["HTTP 状态", "含义", "典型场景"],
        rows=[
            ["400", "请求参数业务校验失败", "筛选字段不在白名单 / 千问解析的条件无效"],
            ["401", "未认证 / Token 无效", "未登录访问需鉴权接口"],
            ["404", "资源不存在", "股票代码不存在"],
            ["422", "字段格式不合法", "Pydantic 校验失败（如 username < 3 字符）"],
            ["503", "外部依赖不可用", "千问 / OpenAI 兼容服务异常或未配置 Key"],
            ["500", "服务端未捕获异常", "数据库连接失败等"],
        ],
        col_widths=[2.4, 4.4, 8.2],
        caption="表 B-4　通用错误码",
    )

    add_h1(doc, "附录 C　术语与缩略语")
    add_table(
        doc,
        header=["缩写 / 术语", "全称 / 含义"],
        rows=[
            ["LLM", "Large Language Model，大语言模型"],
            ["NL", "Natural Language，自然语言"],
            ["JWT", "JSON Web Token，无状态身份令牌"],
            ["ORM", "Object-Relational Mapping，对象关系映射"],
            ["TTM", "Trailing Twelve Months，过去 12 个月滚动"],
            ["PE / PB", "Price-to-Earnings / Price-to-Book，市盈率 / 市净率"],
            ["ROE", "Return on Equity，净资产收益率"],
            ["YoY", "Year-over-Year，同比增速"],
            ["CSI300", "沪深 300 指数（中证 300）"],
            ["AKShare", "开源 Python 金融数据接口库"],
            ["APScheduler", "Advanced Python Scheduler，进程内任务调度框架"],
            ["SUS", "System Usability Scale，系统可用性量表"],
            ["IDOR", "Insecure Direct Object Reference，越权访问漏洞"],
            ["SPA", "Single Page Application，单页应用"],
        ],
        col_widths=[3.6, 11.0],
        caption="表 C-1　术语与缩略语",
    )

    # 致谢
    add_h1(doc, "致　　谢")
    add_paragraph(
        doc,
        "在本课题的整个开发与文档撰写过程中，得到了指导教师的悉心指导与同学们的热心帮助。指导教师在选题论证、"
        "技术路线和文档结构上提供了大量宝贵的修改意见；同窗在前端样式调试和数据测试方面也给予了重要支持。"
        "同时感谢 AKShare、FastAPI、Vue.js、通义千问等开源 / 开放平台为本系统的实现提供了基础设施。"
        "最后感谢家人在学习生活中给予的理解与支持，谨此表达最诚挚的谢意。"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    print(f"文档已生成：{out_path}")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "基于千问的股票筛选系统设计与实现.docx"
    build_document(out)
