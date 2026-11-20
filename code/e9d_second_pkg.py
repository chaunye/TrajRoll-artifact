"""A5 / E9-d：为第二人类标注者生成独立标注数据包（0 机时，本地）。

产出（week1/out/）：
  e9d_二审_标注页面_2026-10-05.html   自包含网页（嵌入 100 条，乱序 T-key，对池信息盲）
  e9d_二审_标注者说明_2026-10-05.md   给标注者的说明（盲态安全，可直接转发）
  e9d_二审_密钥表_仅自留_2026-10-05.csv  T-key -> 原始行映射（含第一轮标签，勿发标注者）
  e9d_二审_回收与计算说明_仅自留_2026-10-05.md
  e9d_二审_数据包_2026-10-05.zip      发给标注者的 zip（只含网页+说明）

设计约束（预注册口径：同 seed 抽 100 条复标；AI 代标不算）：
  - 只抽命中池 100 行（κ 只需双方同题；未命中池 M 行不进二审包）；
  - 乱序 seed = 20261006，T001–T100 中性键，**不显示 pool/模板/instance**（对 oracle 盲）；
  - rubric 与 10-05 冻结版（e9d_复核指南_2026-10-05.md）逐字一致。

用法：python week1/e9d_second_pkg.py
"""
import csv
import json
import os
import random
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
DATE = "2026-10-05"
SEED = 20261006
FINAL_CSV = os.path.join(OUT, f"e9d_sample_终版_{DATE}.csv")
FIRST_CSV = os.path.join(OUT, "e9d_sample_已标注.csv")
LAB = "label_1无进展_0有信息量"

RUBRIC = """- **1 = 无进展**：一行式否定回显——command not found、No matches、not found、invalid option、
  usage 错、EXECUTION TIMED OUT、乱输入（`mkdir.git` 类）触发的 bash 语法错；以及"成功但零输出"的
  **检查类**命令（静默 ls / 测试运行）。
- **0 = 有信息量**：观测**带内容**——文件内容/diff、堆栈（堆栈=定位线索）、断言期望 vs 实际、
  目录列表、检索命中、命令实际输出、edit 成功回执（"File updated"+全文）。
- 拿不准就选**存疑（2）**，不要硬凑。"""


def read_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p, header, rows):
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>E9-d 第二标注者 · 独立标注（100 条）</title>
<style>
  :root { --ok:#0a7d33; --no:#b3261e; --amb:#8a6d00; }
  * { box-sizing:border-box; }
  body { font-family:"Segoe UI","Microsoft YaHei",sans-serif; margin:0; background:#f5f6f8; color:#1c1c1c; }
  header { position:sticky; top:0; background:#fff; border-bottom:1px solid #ddd; padding:10px 18px; z-index:5; }
  h1 { font-size:17px; margin:0 0 6px; }
  .bar { display:flex; gap:14px; align-items:center; flex-wrap:wrap; font-size:13px; color:#444; }
  .bar .pbar { flex:1 1 260px; height:10px; background:#e4e6ea; border-radius:5px; overflow:hidden; }
  .bar .pbar>i { display:block; height:100%; background:var(--ok); width:0%; transition:width .2s; }
  button { font:inherit; cursor:pointer; border:1px solid #bbb; background:#fff; border-radius:6px; padding:5px 12px; }
  button:hover { background:#eef1f5; }
  main { max-width:1080px; margin:18px auto 90px; padding:0 18px; }
  .meta { display:flex; gap:10px; flex-wrap:wrap; align-items:center; font-size:13px; color:#555; margin-bottom:10px; }
  .tag { background:#e8ecf3; border-radius:4px; padding:2px 8px; }
  .card { background:#fff; border:1px solid #d9dde3; border-radius:10px; padding:16px 18px; box-shadow:0 1px 3px rgba(0,0,0,.05); }
  .fld { margin-bottom:14px; }
  .fld>.lbl { font-size:12px; color:#666; margin-bottom:4px; font-weight:600; }
  pre { white-space:pre-wrap; word-break:break-word; background:#f7f8fa; border:1px solid #e2e5ea;
        border-radius:8px; padding:12px 14px; margin:0; font:13px/1.55 Consolas,"Courier New",monospace; max-height:340px; overflow:auto; }
  pre.obs { max-height:480px; background:#fbfbf6; }
  pre.clamp { max-height:150px; overflow:hidden; }
  .expand { font-size:12.5px; color:#1c5da8; background:none; border:none; padding:2px 0; margin-top:4px; }
  .verdict { display:flex; gap:12px; margin:14px 0 8px; flex-wrap:wrap; }
  .verdict button { font-size:16px; font-weight:700; padding:12px 22px; border-width:2px; }
  .v1 { border-color:var(--no); color:var(--no); } .v0 { border-color:var(--ok); color:var(--ok); } .v2 { border-color:var(--amb); color:var(--amb); }
  .verdict .cur { outline:3px solid #333; outline-offset:2px; }
  .verdict .done1 { background:#fdecea; } .verdict .done0 { background:#e8f5ec; } .verdict .done2 { background:#faf5e0; }
  .note { width:100%; font:inherit; padding:8px 10px; border:1px solid #ccc; border-radius:6px; }
  .nav { display:flex; gap:10px; align-items:center; margin-top:14px; flex-wrap:wrap; font-size:13px; color:#555; }
  #panel { background:#fff8e6; border:1px solid #eadfbb; border-radius:10px; padding:12px 16px; font-size:13.5px; line-height:1.7; margin-bottom:14px; display:none; }
  #panel h3 { margin:2px 0 8px; font-size:14px; }
  #panel ul { margin:4px 0 0 18px; padding:0; }
  #panel li { margin:3px 0; }
  #intro { position:fixed; inset:0; background:#fff; z-index:50; overflow:auto; padding:28px 0 60px; }
  #intro .inner { max-width:820px; margin:0 auto; padding:0 22px; font-size:14.5px; line-height:1.8; }
  #intro h2 { font-size:19px; margin:0 0 14px; }
  #intro h3 { font-size:15px; margin:18px 0 6px; }
  #intro li { margin:4px 0; }
  #intro .warn { background:#fdecea; border:1px solid #f2c6c0; color:var(--no); border-radius:8px; padding:10px 14px; margin:14px 0; }
  #intro .go { display:block; margin:22px auto 0; font-size:17px; font-weight:700; padding:12px 34px; background:var(--ok); border-color:var(--ok); color:#fff; }
  footer { text-align:center; font-size:12px; color:#999; margin:30px 0; }
  kbd { background:#eef1f5; border:1px solid #ccc; border-bottom-width:2px; border-radius:4px; padding:0 5px; font-size:12px; }
</style>
</head>
<body>
<div id="intro">
  <div class="inner">
    <h2>标注任务 · coding agent 观测的信息量判断</h2>
    <p>一共 <b>100 条</b>，每条展示：任务（target）、agent 这一轮的动作（ai_action）、环境返回的观测（observation）。
       你要在三种标签里选一个，可写一句备注。预计 <b>60–90 分钟</b>，可分多次做完（进度自动保存在本浏览器）。</p>
    <div class="warn">⚠ 请先用电脑浏览器打开本文件（Chrome / Edge 均可，<b>不需要联网</b>）。<br>
       ① 如果你现在是在压缩包/微信预览窗口里看到的，请先把文件<b>解压或另存到桌面</b>再双击打开，否则页面会空白、进度无法保存；<br>
       ② 手机上只能浏览、无法导出文件，请在电脑上完成。</div>
    <h3>怎么操作</h3>
    <ul>
      <li>点下方"开始标注"，进入逐条页面：读<b>观测原文</b>（默认折叠，点"展开观测原文"看全），点三个按钮之一；可写备注。</li>
      <li>快捷键：<kbd>1</kbd> / <kbd>0</kbd> / <kbd>2</kbd> 打标签并自动跳下一条；<kbd>←</kbd> <kbd>→</kbd> 翻页。</li>
      <li>全部标完后点右上角 <b>"导出标注 CSV"</b>，把下载到的 CSV 文件发回；若下载被拦截，点旁边的"复制结果"再粘贴到记事本保存。</li>
    </ul>
    <h3>判定 rubric（判断对象 = 这条观测对 agent 的后续行动有没有信息量）</h3>
    <ul>
      <li><b style="color:var(--no)">1 = 无进展</b>：一行式否定回显——command not found、No matches、not found、invalid option、
          usage 错、EXECUTION TIMED OUT、乱输入（如 <code>mkdir.git</code>）触发的 bash 语法错；以及"成功但零输出"的<b>检查类</b>命令（静默 ls / 测试运行）。</li>
      <li><b style="color:var(--ok)">0 = 有信息量</b>：观测<b>带内容</b>——文件内容/diff、堆栈（<b>堆栈=定位线索</b>）、断言期望 vs 实际、
          目录列表、检索命中、命令实际输出、edit 成功回执（"File updated"+全文）。</li>
      <li><b style="color:var(--amb)">2 = 存疑</b>：拿不准就选 2，不要硬凑。</li>
    </ul>
    <h3>三条纪律</h3>
    <ul>
      <li><b>独立标注</b>：请勿与其他标注者讨论条目或参考其结果；拿到任务后一次性独立完成最好。</li>
      <li>按你自己的判断来，不要试图猜"正确答案"。</li>
      <li>观测原文较长时请展开看完再判，尤其堆栈类。</li>
    </ul>
    <button class="go" id="btnStart">开始标注 →</button>
  </div>
</div>
<header>
  <h1>E9-d 第二标注者 · 独立标注（共 %%N%% 条）</h1>
  <div class="bar">
    <span id="pos"></span>
    <div class="pbar"><i id="pfill"></i></div>
    <span id="done"></span>
    <button id="btnRub">rubric ▾</button>
    <button id="btnJump">跳到下一条未标</button>
    <button id="btnExp" style="font-weight:700">导出标注 CSV</button>
    <button id="btnCopy">复制结果</button>
    <button id="btnReset">清空重来</button>
  </div>
</header>
<main>
  <div id="panel">
    <h3>判定 rubric（判断对象 = <b>这条观测对 agent 的后续行动有没有信息量</b>）</h3>
    <ul>
      <li><b style="color:var(--no)">1 = 无进展</b>：一行式否定回显——command not found、No matches、not found、
          invalid option、usage 错、EXECUTION TIMED OUT、乱输入（如 <code>mkdir.git</code>）触发的 bash 语法错；
          以及"成功但零输出"的<b>检查类</b>命令（静默 ls / 测试运行）。</li>
      <li><b style="color:var(--ok)">0 = 有信息量</b>：观测<b>带内容</b>——文件内容/diff、堆栈（<b>堆栈=定位线索</b>）、
          断言期望 vs 实际、目录列表、检索命中、命令实际输出、edit 成功回执（"File updated"+全文）。</li>
      <li><b style="color:var(--amb)">2 = 存疑</b>：拿不准就选 2，不要硬凑。</li>
    </ul>
  </div>
  <div class="card" id="card"></div>
  <div class="nav">
    <button id="btnPrev">← 上一条</button>
    <button id="btnNext">下一条 →</button>
    <span>快捷键：<kbd>1</kbd> <kbd>0</kbd> <kbd>2</kbd> 打标签并跳下一条，<kbd>←</kbd><kbd>→</kbd> 翻页。进度自动保存在本浏览器，关掉不丢。</span>
  </div>
</main>
<footer>独立标注：请勿与其他标注者讨论或参考其结果；全部标完后点"导出标注 CSV"并把文件发回。</footer>
<script>
const ITEMS = %%DATA%%;
const N = ITEMS.length;
const LSKEY = "e9d_second_annotator_v1";
let cur = 0;
let state = { labels: {}, notes: {} };
try { const s = localStorage.getItem(LSKEY); if (s) state = JSON.parse(s); } catch (e) {}
function persist() { try { localStorage.setItem(LSKEY, JSON.stringify(state)); } catch (e) {} }
const $ = id => document.getElementById(id);
function labelOf(k) { return state.labels[k]; }
function doneCount() { return ITEMS.filter(it => labelOf(it.k) !== undefined).length; }
function clampPre() {
  const p = document.querySelector("pre.obs");
  const b = document.getElementById("btnExpPre");
  if (p && b) { p.classList.toggle("clamp", !p.dataset.expanded); b.textContent = p.dataset.expanded ? "收起观测原文" : "展开观测原文"; }
}
function render() {
  const it = ITEMS[cur], lab = labelOf(it.k);
  $("pos").textContent = "第 " + (cur+1) + " / " + N + " 条";
  $("done").textContent = "已标 " + doneCount() + " / " + N;
  $("pfill").style.width = (100*doneCount()/N) + "%";
  const vbtn = (v, cls, txt, desc) =>
    '<button class="' + cls + (lab===v ? ' cur ' : ' ') + (lab===v ? 'done'+v : '') + '" data-v="'+v+'" title="'+desc+'">'+txt+'</button>';
  $("card").innerHTML =
    '<div class="meta"><span class="tag">' + it.k + '</span>' +
    (lab!==undefined ? '<span class="tag">已标：'+lab+'</span>' : '<span class="tag" style="color:#8a6d00">未标</span>') + '</div>' +
    '<div class="fld"><div class="lbl">任务（target）</div><pre>' + esc(it.t) + '</pre></div>' +
    '<div class="fld"><div class="lbl">Agent 这一轮的动作（ai_action）</div><pre class="act">' + esc(it.a) + '</pre></div>' +
    '<div class="fld"><div class="lbl">工具/环境返回的观测（observation）—— 判断对象</div>' +
    '<pre class="obs clamp" id="obsPre">' + esc(it.o) + '</pre>' +
    '<button class="expand" id="btnExpPre">展开观测原文</button></div>' +
    '<div class="verdict">' +
      vbtn("1","v1","1 · 无进展","一行式否定回显 / 成功但零输出（检查类）") +
      vbtn("0","v0","0 · 有信息量","带内容：堆栈/diff/列表/实际输出/成功回执") +
      vbtn("2","v2","2 · 存疑","拿不准") +
    '</div>' +
    '<input class="note" id="note" placeholder="备注（可选，一两句话）" value="' + escAttr(state.notes[it.k]||"") + '">';
  document.querySelectorAll(".verdict button").forEach(b =>
    b.onclick = () => { setLabel(b.dataset.v, true); });
  document.getElementById("btnExpPre").onclick = () => {
    const p = document.getElementById("obsPre");
    p.dataset.expanded = p.dataset.expanded ? "" : "1";
    clampPre();
  };
  document.getElementById("note").oninput = e => { state.notes[it.k] = e.target.value; persist(); };
  clampPre();
}
function esc(s){ return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function escAttr(s){ return esc(s).replace(/"/g,"&quot;"); }
function setLabel(v, advance) {
  state.labels[ITEMS[cur].k] = v; persist(); render();
  if (advance && cur < N-1) { cur++; render(); }
}
function move(d) { cur = Math.min(N-1, Math.max(0, cur+d)); render(); }
function jumpUnlabeled() {
  for (let d=1; d<=N; d++) { const j=(cur+d)%N; if (labelOf(ITEMS[j].k)===undefined) { cur=j; render(); return; } }
  alert("全部已标完，可点\"导出标注 CSV\"。");
}
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (e.key === "1") setLabel("1", true);
  else if (e.key === "0") setLabel("0", true);
  else if (e.key === "2") setLabel("2", true);
  else if (e.key === "ArrowLeft") move(-1);
  else if (e.key === "ArrowRight") move(1);
});
$("btnPrev").onclick = () => move(-1);
$("btnNext").onclick = () => move(1);
$("btnJump").onclick = jumpUnlabeled;
$("btnRub").onclick = () => { const p=$("panel"); p.style.display = p.style.display==="block" ? "none" : "block"; };
$("btnReset").onclick = () => {
  if (confirm("确定清空全部标注？此操作不可撤销。") && confirm("再次确认：清空重来？")) {
    state = { labels:{}, notes:{} }; persist(); cur=0; render();
  }
};
function rowsCsv() {
  let rows = 'tkey,label_1无进展_0有信息量,notes\r\n';
  for (const it of ITEMS) {
    const lab = labelOf(it.k);
    const note = (state.notes[it.k]||"").replace(/"/g,'""');
    rows += it.k + ',' + (lab===undefined?'':lab) + ',"' + note + '"\r\n';
  }
  return "\ufeff" + rows;
}
$("btnExp").onclick = () => {
  const un = N - doneCount();
  if (un > 0 && !confirm("还有 " + un + " 条未标，确定现在导出？")) return;
  const blob = new Blob([rowsCsv()], { type:"text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "e9d_second_annotation.csv";
  a.click(); URL.revokeObjectURL(a.href);
  alert("已下载 e9d_second_annotation.csv。若浏览器拦截了下载，请点\"复制结果\"，粘贴到记事本另存为该文件名。");
};
$("btnCopy").onclick = () => {
  const txt = rowsCsv();
  const fin = () => alert("已复制全部结果到剪贴板：请打开记事本，粘贴并另存为 e9d_second_annotation.csv 发回。");
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(txt).then(fin, () => fallbackCopy(txt, fin));
  } else fallbackCopy(txt, fin);
};
function fallbackCopy(txt, fin) {
  const ta = document.createElement("textarea");
  ta.value = txt; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); fin(); } catch (e) { alert("复制失败，请用\"导出标注 CSV\"。"); }
  document.body.removeChild(ta);
}
$("btnStart").onclick = () => { document.getElementById("intro").style.display = "none"; };
render();
</script>
</body>
</html>
"""

ANNOTATOR_DOC = """# 标注任务说明 · coding agent 观测的信息量判断（约 60–90 分钟）

> 本说明已内嵌进 `annotation_task.html` 的开场页，正常情况下对方只需这一个文件；
> 本 md 是留档副本。注意：数据包 zip 只含一个 ASCII 文件名的网页，发送时整个 zip 转发，
> 或直接发网页文件均可——但必须提醒对方**解压/另存后用电脑浏览器打开**，不要在压缩窗口或
> 微信预览里直接点开（脚本不运行会白屏、进度无法保存）。"""

USER_DOC = """# 二审包 · 回收与计算说明（仅自留，勿发标注者）

## 这个包是什么

- **目的**：第二人类标注者对 E9-d 的 100 条命中池样本独立复标 → 与第一轮人工标注算 Cohen's κ，
  补上论文 §4.10/§6 "single human annotator" 这条方法学弱点（预注册口径：同 seed 抽 100 条；AI 代标不算）。
- **盲态设计**：发给标注者的 100 条已用 seed={seed} 乱序、重编为中性键 T001–T100，
  **不含 pool / stratum_template / instance_id / exit_status**——标注者无法知道哪些是 oracle 命中池，
  也看不到第一轮标签（κ 才有效）。
- **rubric**：与 10-05 冻结版（`e9d_复核指南_2026-10-05.md`）逐字一致（网页内嵌 + 说明文档）。

## 流程（你要做的三步）

1. **发**：把 `e9d_second_annotator_pkg.zip`（或直接把里面的 `annotation_task.html` 单文件）发给标注者
   （微信/邮件均可）。说明与 rubric 已内嵌为网页开场页，**只此一个文件**。
   ⚠️ 提醒对方：**解压/另存后用电脑浏览器双击打开**，别在压缩窗口或微信预览里直接点开。
   ⚠️ **`e9d_二审_密钥表_{date}_仅自留.csv` 千万别发**——里面有第一轮标签与原始行映射。
2. **收**：收回 `e9d_second_annotation.csv`（100 行：tkey + 标签 + 备注；下载失败时对方会用"复制结果"
   粘贴出来的同名内容，一样能用）。
3. **算**：`python week1/e9d_kappa.py --csv <收回的csv路径>`
   → 输出 `week1/out/e9d_kappa_二审.txt`：总体一致率、**Cohen's κ（2×2 决定票 / 3×3 含存疑）**、
   逐模板分歧表、第二标注者单独的原始精度（Wilson CI）。

## 收到 κ 之后

- 论文 **§4.10 / §6** 的 "a second independent human annotator is future work" 段改为实测：
  "a second independent human annotator relabelled the 100 hit-pool turns under the same frozen rubric;
  raw agreement …%, Cohen's κ = …"（具体措辞按脚本输出）；
- supplementary E.7 加一行二审协议；
- 若 κ 与 59.1% 口径有出入，**声称只许收窄**：以两轮+二审的合并披露为准，先改判读档再改论文。

## 可复现性

- 乱序 seed = {seed}；数据源 = `e9d_sample_终版_{date}.csv`（pool=hit 的 100 行）+ 第一轮标签 = `e9d_sample_已标注.csv`；
- 本包由 `week1/e9d_second_pkg.py` 一键重建；
- 第一轮人工标签分布（命中池，供对照）：44×0 / 47×1 / 9×2。
"""


def main():
    final = read_csv(FINAL_CSV)
    first = {r["id"]: r for r in read_csv(FIRST_CSV)}
    hits = [r for r in final if r["pool"] == "hit"]
    assert len(hits) == 100, f"命中池应 100 行，实测 {len(hits)}"

    rng = random.Random(SEED)
    order = list(range(100))
    rng.shuffle(order)
    items, keymap = [], []
    for i, idx in enumerate(order):
        r = hits[idx]
        tkey = f"T{i+1:03d}"
        items.append({"k": tkey, "t": r["target"], "a": r["ai_action"], "o": r["observation"]})
        fr = first.get(r["id"], {})
        keymap.append([tkey, r["id"], r["pool"], r["stratum_template"], r["instance_id"],
                       r["turn_i"], fr.get(LAB, ""), r[LAB]])

    # 1) 网页
    html = HTML.replace("%%N%%", str(len(items))).replace("%%DATA%%", json.dumps(items, ensure_ascii=False))
    html_path = os.path.join(OUT, f"e9d_二审_标注页面_{DATE}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 2) 标注者说明
    doc_path = os.path.join(OUT, f"e9d_二审_标注者说明_{DATE}.md")
    with open(doc_path, "w", encoding="utf-8") as f:
        f.write(ANNOTATOR_DOC)

    # 3) 密钥表（仅自留）
    keymap_path = os.path.join(OUT, f"e9d_二审_密钥表_{DATE}_仅自留.csv")
    write_csv(keymap_path,
              ["tkey", "id", "pool", "stratum_template", "instance_id", "turn_i",
               f"第一轮人工_{LAB}", f"终版_{LAB}"], keymap)

    # 4) 回收说明（仅自留）
    userdoc_path = os.path.join(OUT, f"e9d_二审_回收与计算说明_{DATE}_仅自留.md")
    with open(userdoc_path, "w", encoding="utf-8") as f:
        f.write(USER_DOC.format(seed=SEED, date=DATE))

    # 5) zip：只放一个 ASCII 文件名的网页（说明已内嵌为开场页），
    #    避免 zip 中文文件名乱码 / md 打不开 / 压缩窗口内直接双击白屏三类问题
    zip_path = os.path.join(OUT, "e9d_second_annotator_pkg.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(html_path, "annotation_task.html")

    # 自检：模板与说明里不得出现池/模板/第一轮字样（嵌入的观测原文是自由文本，不查，
    # 否则 "missing"/"hit" 等普通词会误报；ASCII 词带词边界，避免 white-space 误报）
    import re as _re
    for name, blob in (("html", HTML), ("annotator_doc", ANNOTATOR_DOC)):
        for bad in (r"\bhit\b", r"\bmiss\b", r"\bstratum\b", r"\binstance_id\b",
                    "第一轮", r"\boracle\b", "命中池", "e9d_sample", "终版"):
            assert not _re.search(bad, blob, _re.I), f"泄漏风险: {bad} in {name}"
    # JS 语法校验（有 node 时）：<script> 块整体过 node --check，语法错直接构建失败
    import re as _re2, shutil as _sh, subprocess as _sp, tempfile as _tf
    js = _re2.search(r"<script>(.*)</script>", html, _re2.S).group(1)
    if _sh.which("node"):
        with _tf.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
            tf.write(js); tmp = tf.name
        r = _sp.run(["node", "--check", tmp], capture_output=True, text=True)
        os.unlink(tmp)
        assert r.returncode == 0, "HTML JS 语法错误: " + r.stderr[:500]

    print("OK")
    print("zip      :", zip_path)
    print("keymap   :", keymap_path, "（勿发）")
    print("html     :", html_path)
    print("doc      :", doc_path)
    print("user doc :", userdoc_path)


if __name__ == "__main__":
    main()
