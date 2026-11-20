#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E9-d 重标注（2026-10-05）：逐行独立复核 130 条观测，按冻结 rubric 重打标签。

rubric（e9d_sample_meta.txt，预注册）：
  1 = 确实无进展：观测里没有可行动的新信息（纯失败回显、命令本身打错、检索零匹配、
      目标缺失、权限拒绝、usage 报错、成功但零输出的检查类命令）
  0 = 有信息量：给出了定位线索或状态内容（文件内容/diff、堆栈、断言值、目录列表、
      检索命中、命令实际输出、成功 edit 的 "File updated" 状态回执）
  判定口径：一行式否定回显（command not found / No matches / not found / invalid
  option / usage 错误 / EXECUTION TIMED OUT）→ 1；多行任务内容（哪怕它是报错）→ 0。

输出 week1/out/e9d_sample_重标AI_2026-10-05.csv（同 schema，label 列 = 重标值，
notes 列 = 重标理由，保留原标注在 relabel_old 列）。
"""
import csv

# id -> (label, reason)
L = {
 "H001": (0, "edit-lint：E999 行号+diff 预览，定位明确"),
 "H002": (0, "edit-lint：SyntaxError+diff，定位明确"),
 "H003": (0, "edit-lint：F821 undefined name+diff"),
 "H004": (0, "edit-lint：E999 unmatched ')'+diff"),
 "H005": (0, "edit-lint：F821 undefined name+diff"),
 "H006": (0, "edit-lint：E999 IndentationError+diff"),
 "H007": (0, "edit-lint：E999 行号+diff"),
 "H008": (0, "edit-lint：E999 IndentationError+diff"),
 "H009": (0, "edit-lint：F821 undefined name+diff"),
 "H010": (0, "edit-lint：F821 undefined name+diff"),
 "H011": (0, "edit-lint：F821 undefined name+diff"),
 "H012": (0, "edit-lint：E999 行号+diff"),
 "H013": (0, "edit-lint：E999 IndentationError+diff"),
 "H014": (0, "edit-lint：E999 IndentationError+diff"),
 "H015": (0, "edit-lint：F821 undefined name+diff"),
 "H016": (0, "edit-lint：F821 undefined name+diff"),
 "H017": (0, "edit-lint：F821 undefined name+diff"),
 "H018": (0, "edit-lint：E999 IndentationError+diff"),
 "H019": (0, "edit-lint：F821 undefined name+diff"),
 "H020": (0, "edit-lint：F821 undefined name+diff"),
 "H021": (0, "edit-lint：E999 SyntaxError+diff"),
 "H022": (0, "edit-lint：E111×4 行号+diff"),
 "H023": (0, "edit-lint：F821 undefined name+diff"),
 "H024": (0, "edit-lint：F821 undefined name+diff"),
 "H025": (1, "make：No rule to make target，纯缺失回显（原标 2，可判）"),
 "H026": (1, "make：No rule to make target 'all'，纯缺失回显"),
 "H027": (0, "pytest：失败用例名+断言上下文"),
 "H028": (0, "pytest：AssertionError 期望 vs 实际键列表"),
 "H029": (0, "pytest：断言差值 b'o' vs b'fo'"),
 "H030": (1, "bash 语法错：自身乱输入的回显，仅两行"),
 "H031": (1, "bash 语法错：同上"),
 "H032": (1, "bash 语法错：同上"),
 "H033": (0, "复合输出含状态事实：'.dvc' exists 用 -f、bar.txt 不存在（原标 1，改 0）"),
 "H034": (1, "mkdir invalid option：一行乱命令回显"),
 "H035": (1, "ls invalid option：同上"),
 "H036": (1, "javascript: command not found：自造命令"),
 "H037": (1, "whois: command not found：一行否定回显（原标 0，改 1）"),
 "H038": (1, "find.: command not found：缺空格乱命令"),
 "H039": (1, "ls.github: command not found：乱命令"),
 "H040": (1, "cd..: command not found（原标 2，可判）"),
 "H041": (1, "mkdir.git: command not found（原标 2）"),
 "H042": (1, "mkdir.git（原标 2）"),
 "H043": (1, "mkdir.git（原标 2）"),
 "H044": (1, "mkdir.git（原标 2）"),
 "H045": (1, "mkdir.git（原标 2）"),
 "H046": (1, "mkdir.git（原标 2）"),
 "H047": (1, "ls..: command not found（原标 2）"),
 "H048": (1, "open.dvcignore: command not found"),
 "H049": (1, "open.dvcignore: command not found"),
 "H050": (1, "find.: command not found"),
 "H051": (1, "find.: command not found"),
 "H052": (1, "find.: command not found"),
 "H053": (1, "sqlglot: command not found：一行否定回显（原标 0，改 1）"),
 "H054": (1, "search_file usage 错：调用格式错"),
 "H055": (1, "同上"),
 "H056": (1, "同上"),
 "H057": (1, "成功但零输出：测试运行静默，无内容"),
 "H058": (1, "成功但零输出：ls 静默=空目录，与零匹配同类"),
 "H059": (0, "rm -rf 成功：状态变化回执（与 H060-062 同口径）"),
 "H060": (0, "rm 成功：状态变化回执"),
 "H061": (0, "rm 成功：状态变化回执"),
 "H062": (0, "rm 成功：状态变化回执（原标 1，与 059-061 统一为 0）"),
 "H063": (1, "cannot open reproduce_bug.sh：目标缺失"),
 "H064": (1, "File not found：一行否定"),
 "H065": (1, "File not found"),
 "H066": (1, "File not found"),
 "H067": (1, "File not found"),
 "H068": (0, "观测实为 edit 成功回执+全文（权限模板误命中）：状态变化+内容（原标 1，改 0）"),
 "H069": (0, "同上：edit 成功+全文（原标 1，改 0）"),
 "H070": (0, "同上：edit 成功+全文（原标 1，改 0）"),
 "H071": (1, "检索零匹配"),
 "H072": (1, "检索零匹配"),
 "H073": (1, "检索零匹配"),
 "H074": (1, "检索零匹配"),
 "H075": (1, "检索零匹配"),
 "H076": (1, "检索零匹配"),
 "H077": (1, "检索零匹配"),
 "H078": (1, "检索零匹配"),
 "H079": (1, "检索零匹配"),
 "H080": (1, "检索零匹配"),
 "H081": (1, "检索零匹配"),
 "H082": (1, "检索零匹配"),
 "H083": (1, "检索零匹配"),
 "H084": (0, "nose2：Traceback+TypeError 具名"),
 "H085": (0, "nose2：Traceback+打印的 Args/Kwargs"),
 "H086": (0, "unittest：FAIL 用例名+断言行"),
 "H087": (1, "Directory not found：一行否定"),
 "H088": (1, "Directory not found"),
 "H089": (1, "Directory not found"),
 "H090": (1, "Directory not found"),
 "H091": (0, "mypy 语义拒绝：具名指出 iface.py 不是 typeshed（原标 0，保留）"),
 "H092": (0, "多行复合错误：pygit2 import 失败+git 配置错误"),
 "H093": (0, "Traceback：rtbf.py:38 AttributeError 具名"),
 "H094": (1, "grep: bin: No such file：一行否定"),
 "H095": (0, "观测实为 open 成功+文件内容（路径模板误命中）"),
 "H096": (0, "完整测试 Traceback：DockerException 根因具名（原标 1，改 0）"),
 "H097": (1, "cd../: No such file：乱命令回显（原标 0，改 1）"),
 "H098": (1, "ls: cannot access：一行否定"),
 "H099": (1, "mkdir cannot create：父目录缺失，一行否定"),
 "H100": (1, "cd: No such file or directory"),
 "M001": (1, "EXECUTION TIMED OUT：观测零内容"),
 "M002": (0, "edit 成功回执+全文"),
 "M003": (0, "goto 成功+文件内容"),
 "M004": (1, "open 成功但文件为空：与空目录/零匹配同类，无内容"),
 "M005": (0, "edit 成功回执+全文（原标 1，改 0）"),
 "M006": (0, "完整网络 Traceback：gaierror 根因"),
 "M007": (0, "search 命中 4 处"),
 "M008": (0, "cekit 校验错误：具名 key 缺失"),
 "M009": (1, "Usage: edit：调用格式错"),
 "M010": (0, "wget 实际输出（302→200 已保存）"),
 "M011": (0, "ls 目录列表"),
 "M012": (0, "ls 目录列表"),
 "M013": (0, "dvc init 语义拒绝：'.dvc' exists 用 -f，状态+补救"),
 "M014": (0, "错误具名：module ... has no attribute"),
 "M015": (0, "edit 成功回执+全文（原标 1，改 0）"),
 "M016": (0, "命令实际输出（生成的名字）"),
 "M017": (0, "search 命中 7 处"),
 "M018": (0, "Traceback：TypeError 具名"),
 "M019": (0, "edit 成功回执+全文（原标 1，改 0）"),
 "M020": (0, "search 命中 13 处"),
 "M021": (0, "edit 成功回执+全文（原标 1，改 0）"),
 "M022": (0, "edit 成功回执+全文"),
 "M023": (0, "edit 成功回执+全文"),
 "M024": (0, "edit 成功回执+全文"),
 "M025": (0, "search 命中 1 处"),
 "M026": (0, "edit 成功回执+全文"),
 "M027": (0, "Traceback：AttributeError 具名"),
 "M028": (0, "search 命中 36 处"),
 "M029": (0, "edit 成功回执+全文"),
 "M030": (0, "Traceback：KeyError 具名"),
}

src = list(csv.DictReader(open("out/e9d_sample_已标注.csv", encoding="utf-8-sig")))
assert len(src) == 130
missing = [r["id"] for r in src if r["id"] not in L]
assert not missing, missing

out = []
for r in src:
    lab, why = L[r["id"]]
    r["relabel_old"] = r["label_1无进展_0有信息量"]
    r["label_1无进展_0有信息量"] = lab
    r["notes"] = ("重标2026-10-05: " + why
                  + (" | 原标=" + r["relabel_old"] if r["relabel_old"] not in (str(lab),) else " | 与原标一致"))
    out.append(r)

with open("out/e9d_sample_重标AI_2026-10-05.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
    w.writeheader()
    w.writerows(out)

flips = [r["id"] for r in src if r["relabel_old"] not in (str(L[r["id"]][0]),)]
print("wrote out/e9d_sample_重标AI_2026-10-05.csv")
print("与原标不一致:", len(flips), "条:", " ".join(flips))
agree = 130 - len(flips)
print(f"一致率 {agree}/130 = {agree/130:.1%}（原 9 条存疑按已判计）")
