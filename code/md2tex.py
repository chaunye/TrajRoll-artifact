#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""md2tex.py -- convert ERROR-BACK_v1_en.md into an IEEEtran .tex for Overleaf.

Usage:  python week1/md2tex.py
Output: paper/ERROR-BACK.tex

Design notes:
  * pdflatex route -> every Unicode char must become a LaTeX macro (see UNI).
  * Citations use \cite{refN} plus a hand-written thebibliography (no .bib needed).
  * Tables use booktabs; figures use figure + includegraphics.
  * WARNING: no LaTeX on this machine, so the output is NOT compile-tested.
    Send me the first compile errors and I will fix them.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER = os.path.join(ROOT, "paper")
SRC = os.path.join(PAPER, "ERROR-BACK_v1_en.md")
DST = os.path.join(PAPER, "ERROR-BACK.tex")

# --ispa: IEEE CS（compsoc）单盲 fork，ISPA 2026 用（截稿 2026-10-15）。
# 不带此参数时主链（CCGRID 双盲版）输出逐字节不变。
# TODO(用户): 作者位三处占位符 <<...>> 拿到真实名单后替换。
ISPA = "--ispa" in sys.argv[1:]
if ISPA:
    SRC = os.path.join(PAPER, "ERROR-BACK_ispa.md")
    DST = os.path.join(PAPER, "ERROR-BACK_ispa.tex")

BT = chr(96)          # backtick, built at runtime so this file has no literal one
NUL = "\x00"

UNI = [
    ("\u2192", r"$\to$"), ("\u2190", r"$\leftarrow$"),
    ("\u00d7", r"$\times$"), ("\u2248", r"$\approx$"),
    ("\u2264", r"$\leq$"), ("\u2265", r"$\geq$"),
    ("\u2212", "-"), ("\u2014", "---"), ("\u2013", "--"),
    ("\u201c", "''"), ("\u201d", "''"), ("\u2018", "'"), ("\u2019", "'"),
    ("\u00a7", r"\S"), ("\u00b7", r"$\cdot$"),
    ("\u2713", r"$\checkmark$"), ("\u2705", r"$\checkmark$"),
    ("\u274c", r"$\times$"), ("\u26a0\ufe0f", r"\textbf{!}"), ("\u26a0", r"\textbf{!}"),
    ("\u2b50", ""), ("\U0001f534", ""), ("\U0001f7e1", ""), ("\U0001f7e2", ""),
    ("\U0001f6ab", ""), ("\u2b1c", ""), ("\u2016", r"$\|$"),
]

VUNI = [("\u2248", "~="), ("\u00d7", "x"), ("\u2212", "-"), ("\u2192", "->"),
        ("\u2190", "<-"), ("\u2264", "<="), ("\u2265", ">="), ("\u2605", "*"),
        ("\u2460", "(1)"), ("\u2461", "(2)"), ("\u2462", "(3)"), ("\u2463", "(4)"),
        ("\u00b7", "."), ("\u2014", "--"), ("\u2013", "-"), ("\u2026", "...")]


def vuni(s):
    """verbatim 里不能出现任何宏，也不能出现非 ASCII -> 一律降级成 ASCII。"""
    for a, b in VUNI:
        s = s.replace(a, b)
    return "".join(c if ord(c) < 128 else "?" for c in s)


def esc(s):
    # 顺序必须是「先逐字符转义、再上 Unicode 宏」：UNI 的替换值本身含 \ 和 $
    # （§ -> \S，-> -> $\to$），若先替换后转义，这些宏会被再次转义成
    # \textbackslash{}S / \$\textbackslash{}to\$ 之类的字面垃圾（v1 PDF 里 33 处 \S 即此因）。
    out = []
    for ch in s:
        if ch in "&%$#_{}":
            out.append("\\" + ch)
        elif ch == "~":
            out.append(r"\textasciitilde{}")
        elif ch == "^":
            out.append(r"\textasciicircum{}")
        elif ch == "\\":
            out.append(r"\textbackslash{}")
        else:
            out.append(ch)
    s = "".join(out)
    for a, b in UNI:
        s = s.replace(a, b)
    # OT1 编码下正文里的 < > 渲染成 ¡ ¿（exclamdown/questiondown）。
    # 转成数学模式即恢复直立字形；<= / >= 顺手升级为 \leq / \geq。
    # verbatim 块走 vuni()，不受影响。
    s = s.replace("<=", r"$\leq$").replace(">=", r"$\geq$")
    s = s.replace("<", "$<$").replace(">", "$>$")
    return s

def inline(s):
    codes = []
    def stash(m):
        codes.append(m.group(1))
        return NUL + str(len(codes) - 1) + NUL
    s = re.sub(BT + "([^" + BT + "]+)" + BT, stash, s)
    s = esc(s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"\\emph{\1}", s)
    for i, c in enumerate(codes):
        s = s.replace(NUL + str(i) + NUL, r"\texttt{%s}" % esc(c))
    def cite(m):
        nums = re.findall(r"\d+", m.group(1))
        return r"\cite{%s}" % ",".join("ref" + n for n in nums) if nums else m.group(0)
    s = re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", cite, s)
    return s

def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, cur, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if line[i] == "|":
            cells.append(cur)
            cur = ""
            i += 1
            continue
        cur += line[i]
        i += 1
    cells.append(cur)
    return [c.strip() for c in cells]

def table(rows, cap=None):
    head = split_row(rows[0])
    body = [split_row(r) for r in rows[2:]]
    ncol = len(head)
    col = " ".join(["l"] * ncol) if ncol <= 2 else " ".join(["l"] + ["r"] * (ncol - 1))
    wide = ncol >= 5
    env = "table*" if wide else "table"
    width = r"\textwidth" if wide else r"\columnwidth"
    fs = r"\footnotesize" if wide else r"\small"
    out = [r"\begin{%s}[!tb]" % env, r"\centering", fs,
           r"\setlength{\tabcolsep}{4pt}"]
    if cap:
        out.append(r"\caption{%s}" % inline(cap))
    out += [r"\resizebox{%s}{!}{%%" % width,
           r"\begin{tabular}{%s}" % col, r"\toprule",
           " & ".join(inline(h) for h in head) + r" \\", r"\midrule"]
    for r in body:
        while len(r) < ncol:
            r.append("")
        out.append(" & ".join(inline(c) for c in r[:ncol]) + r" \\")
    out += [r"\bottomrule", r"\end{tabular}}", r"\end{%s}" % env, ""]
    return out

def convert(md):
    title = "Untitled"
    for ln in md.split("\n"):
        if ln.startswith("# "):
            title = inline(ln[2:].strip())
            break
    m = re.search(r"## Abstract\s*\n(.*?)\n(?:---\n|\n?## )", md, re.S)
    abstract = m.group(1).strip() if m else ""
    b = md.find("## 1. Introduction")
    e = md.find("## References")
    body, refs = md[b:e], md[e:]

    out, i = [], 0
    pending_cap = None
    blines = body.split("\n")

    def is_plain(x):
        # \d+\. 必须后跟空白才是有序列表标记；否则行首的 "47.6%" 会被当成
        # 列表项，把结论段从中间截断
        return x.strip() and not re.match(r"^(#|\||>|-|\d+\.\s|!\[|%|\s{4,})", x)

    while i < len(blines):
        ln = blines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", s):
            # md 水平线：LaTeX 里没有对应物，直译会变成一个只含 em-dash 的段落
            i += 1
            continue
        if s.startswith("%% caption:"):
            pending_cap = s[len("%% caption:"):].strip()
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(blines) and set(blines[i + 1].strip()) <= set("|-: "):
            rows = []
            while i < len(blines) and blines[i].strip().startswith("|"):
                rows.append(blines[i].strip())
                i += 1
            out += table(rows, pending_cap)
            pending_cap = None
            continue
        if s.startswith("!["):
            # 图片 markdown 可能跨行（alt 文本换行）-> 先拼到本轮括号闭合
            blob, k = s, i
            while "](" not in blob and k + 1 < len(blines):
                k += 1
                blob += " " + blines[k].strip()
            m2 = re.match(r"!\[(.*?)\]\((.*?)\)", blob)
            if m2:
                # 图注 "**Figure N.** ..." 也可能跨行 -> 整段收进来
                cap, j = "", k + 1
                while j < len(blines) and not blines[j].strip():
                    j += 1
                if j < len(blines) and blines[j].strip().startswith("**Figure"):
                    capp = []
                    while j < len(blines) and blines[j].strip():
                        capp.append(blines[j].strip())
                        j += 1
                    cap = inline(re.sub(r"\*\*Figure \d+\.\*\*\s*", "", " ".join(capp)))
                    k = j - 1
                    if "WIDE" in m2.group(1).upper():
                        out += [r"\begin{figure*}[!tb]", r"\centering",
                                r"\includegraphics[width=0.88\textwidth]{%s}" % m2.group(2),
                                r"\caption{%s}" % cap, r"\end{figure*}", ""]
                    else:
                        out += [r"\begin{figure}[!tb]", r"\centering",
                                ((r"\includegraphics[width=0.80\linewidth]{%s}" if ISPA
                                  else r"\includegraphics[width=0.84\linewidth]{%s}") % m2.group(2)),
                                r"\caption{%s}" % cap, r"\end{figure}", ""]
                i = k + 1
                continue
            i += 1
            continue
        if s.startswith(">"):
            # 连续的 '>' 行是**一个**段落（markdown 语义）-> 必须先合并再 inline()，
            # 否则跨行的 **bold** 会因为单行内匹配不到而残留字面 '**'。
            blk = []
            while i < len(blines) and blines[i].strip().startswith(">"):
                blk.append(blines[i].strip().lstrip(">").strip())
                i += 1
            out.append(inline(" ".join(x for x in blk if x)))
            out.append("")
            continue
        if s.startswith("### "):
            out.append(r"\subsection{%s}"
                       % inline(re.sub(r"^\d+(\.\d+)?\.?\s*", "", s[4:]).strip()))
            i += 1
            continue
        if s.startswith("## "):
            out.append(r"\section{%s}" % inline(re.sub(r"^\d+\.\s*", "", s[3:]).strip()))
            i += 1
            continue
        if ln.startswith("    ") and not s.startswith("|"):
            blk = []
            while i < len(blines) and (blines[i].startswith("    ") or not blines[i].strip()):
                blk.append(vuni(blines[i][4:] if blines[i].startswith("    ") else ""))
                i += 1
            # 双栏栏宽 ~252pt，10pt 等宽一行约 42 字符 -> 降到 \footnotesize
            out += [r"{\footnotesize\begin{verbatim}"] + blk + [r"\end{verbatim}}", ""]
            continue
        if re.match(r"^[-*]\s", s) or re.match(r"^\d+\.\s", s):
            # 列表项的**续行**（缩进 <4 空格、非新条目）属于同一个 item：
            #   不合并的话，跨行的 **bold** 会残留字面 '**'，而且每行会变成独立段落。
            numbered = bool(re.match(r"^\d+\.\s", s))
            env = "enumerate" if numbered else "itemize"
            pat = r"^\d+\.\s" if numbered else r"^[-*]\s"
            out.append(r"\begin{%s}" % env)
            while i < len(blines):
                cs = blines[i].strip()
                if not re.match(pat, cs):
                    break
                parts = [re.sub(pat, "", cs) if numbered else cs[2:]]
                i += 1
                while (i < len(blines) and blines[i].strip()
                       and blines[i].startswith(" ")
                       and not blines[i].startswith("    ")
                       and not re.match(r"^[-*]\s", blines[i].strip())
                       and not re.match(r"^\d+\.\s", blines[i].strip())):
                    parts.append(blines[i].strip())
                    i += 1
                out.append(r"  \item " + inline(" ".join(parts)))
            out.append(r"\end{%s}" % env)
            continue
        para = [s]
        i += 1
        while i < len(blines) and is_plain(blines[i]):
            para.append(blines[i].strip())
            i += 1
        out.append(inline(" ".join(para)))
        out.append("")

    bib = [r"\begin{thebibliography}{99}", r"\setlength{\itemsep}{0pt plus 0.5pt}"]
    if ISPA:
        # IEEE CS 参考文献为 8pt（\footnotesize，CS 模板口径）；主版保持 IEEEtran 默认
        bib = [r"{\footnotesize", r"\begin{thebibliography}{99}",
               r"\setlength{\itemsep}{0pt}"]
    for ln in refs.split("\n"):
        m3 = re.match(r"^\[(\d+)\]\s+(.*)$", ln.strip())
        if m3:
            bib.append(r"\bibitem{ref%s} %s" % (m3.group(1), inline(m3.group(2))))
    bib += [r"\end{thebibliography}"] + ([r"}"] if ISPA else [])

    head = [
        (r"\documentclass[10pt,conference,compsoc]{IEEEtran}" if ISPA
         else r"\documentclass[conference]{IEEEtran}"),
        r"\usepackage{graphicx}", r"\usepackage{booktabs}", r"\usepackage{amssymb}",
        r"\usepackage{array}", r"\usepackage{url}", r"\usepackage[utf8]{inputenc}",
        r"\usepackage{titlesec}",
        # 列表环境收紧：只进 --ispa fork；CCGRID 主版版面保持导师审阅时的状态
        *((
            r"\usepackage{enumitem}",
            r"\setlist{itemsep=1pt,parsep=0pt,topsep=2.5pt,partopsep=0pt}",
        ) if ISPA else ()),
        # 43 个标题 × 默认间距很吃版面；收紧（只改间距，不改字号）
        r"\titlespacing*{\section}{0pt}{5pt plus 1pt minus 1pt}{2pt}",
        r"\titlespacing*{\subsection}{0pt}{4pt plus 1pt minus 1pt}{1pt}",
        # ISPA 版：节标题间距再收一档（8 页贴边）
        *((
            r"\titlespacing*{\section}{0pt}{4pt plus 1pt minus 1pt}{1.5pt}",
            r"\titlespacing*{\subsection}{0pt}{3pt plus 1pt minus 1pt}{1pt}",
            r"\setlength{\abovecaptionskip}{2pt}",
            r"\setlength{\textfloatsep}{4pt plus 1pt minus 1pt}",
            r"\setlength{\intextsep}{4pt plus 1pt minus 1pt}",
            r"\setlength{\floatsep}{4pt plus 1pt minus 1pt}",
        ) if ISPA else ()),
        r"\setlength{\parskip}{0pt}",
        r"\graphicspath{{figs/}}",
        # 18 个浮动体 × 默认宽松间距会吃掉近半页 -> 收紧
        r"\setlength{\textfloatsep}{5pt plus 1pt minus 1pt}",
        r"\setlength{\floatsep}{5pt plus 1pt minus 1pt}",
        r"\setlength{\intextsep}{5pt plus 1pt minus 1pt}",
        r"\setlength{\abovecaptionskip}{3pt}",
        r"\setlength{\belowcaptionskip}{0pt}",
        r"\renewcommand{\topfraction}{0.92}",
        r"\renewcommand{\bottomfraction}{0.7}",
        r"\renewcommand{\textfraction}{0.08}",
        r"\renewcommand{\floatpagefraction}{0.85}",
        r"\renewcommand{\dbltopfraction}{0.92}",
        r"\begin{document}",
        r"\title{%s}" % title,
        ((r"\author{\IEEEauthorblockN{Anonymous Author(s)}"
          r"\IEEEauthorblockA{Affiliation withheld --- author list to be finalized before submission}}")
         if ISPA else
         r"\author{\IEEEauthorblockN{Anonymous submission}}"),
        r"\maketitle", "",
        r"\begin{abstract}", inline(abstract), r"\end{abstract}", "",
    ]
    return "\n".join(head + out + [""] + bib + [r"\end{document}", ""])

md = open(SRC, encoding="utf-8").read()
tex = convert(md)
open(DST, "w", encoding="utf-8").write(tex)
print("wrote", DST)
for k, pat in (("lines", None), ("cites", r"\\cite\{"), ("bibitems", r"\\bibitem"),
               ("figures", r"\\includegraphics"), ("tables", r"\\begin\{table\}"),
               ("sections", r"\\section\{"), ("subsections", r"\\subsection\{")):
    print("  %-12s %s" % (k, tex.count(chr(10)) if pat is None else len(re.findall(pat, tex))))
