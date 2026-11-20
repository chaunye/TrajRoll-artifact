#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E5：主循环 —— 检查点 + 投机分支 + 失败判定 + world 抽取 + 错题本（B0 vs Ours）

这是把 E1–E3 的"几何验证"变成一个真能跑的系统。第一版只做**只读工具**
（§12.7：只读工具没有世界状态要承载，先把机制前半段验证干净）。

四个模式：
  --mode b0       全量追加（baseline）：assistant + 完整观察 都进上下文
  --mode ours     检查点 + 丢弃分支 + 墓碑：失败回合整条丢弃，只追加一句 [TAG]
  --mode rollback 消融臂 = ours 去掉墓碑那一行：失败回合整条丢弃、**不追加任何东西**
  --mode label    B2（有标签无丢弃）：完整轨迹照进，再把墓碑拼进同一条 user 消息
  --mode truncate 滑窗基线：追加方式与 b0 相同，但**发送前**只保留最近 N 条历史消息
                  （--truncate-n，system + 任务描述永远钉住）——"按新旧丢" vs "按失败丢"

E12 追加（2026-10-03，C 类解禁，判据见 week1/预注册_C类解禁三实验_2026-10-03.md）：
  --mode placebo  worldonly 的 world **内容**换常数空串（结构不变）—— 隔离 world 字段内容
  --mode generic  完全无内容的常数墓碑（更短）—— 隔离「随便一个紧凑尾部标记」
  --temperature   采样温度（E13 采样批 0.7）；--stream 流式测 TTFT（E14）

对照表（对应 error_back.md §7.1 的 2×2 消融）：
  臂         丢弃失败轮   墓碑     隔离出什么
  b0         ✗           ✗        基线
  label(B2)  ✗           ✓        B2 − b0 = 标签单独的效应
  rollback(B3) ✓         ✗        b0 − B3 = 遗忘本身的效应
  ours       ✓           ✓        ours − B3 = 墓碑的效应（论文 Table 1 核心格）
  truncate   ✗           ✗        按新旧丢 vs 按失败丢（A2，滑窗基线）

失败 oracle（规则式，零 LLM 调用）：
  1. 工具报错        —— 文件不存在 / 不是目录 / 调用格式非法
  2. 工具成功但零信息 —— grep 匹配 0 行、list_dir 空目录
  （对应方案 §2.1 的两类"无进展回合"）

用法：
    python e5_loop.py --model Qwen3-4B --mode ours --out e5_ours.csv
    python e5_loop.py --model Qwen3-4B --mode b0   --out e5_b0.csv
    python e5_loop.py --provider script --dry-run            # 不联网自测

A1/A2 消融（与 E6-d 同参数）：
    python e5_loop.py --model Qwen3-4B --mode rollback --scenario longtail \
      --error-padding 3000 --max-turns 20 --seed 1
    python e5_loop.py --model Qwen3-4B --mode truncate --truncate-n 8 --scenario longtail \
      --error-padding 3000 --max-turns 20 --seed 1
"""
import argparse
import csv
import json
import os
import random
import re
import shutil
import sys
import time

import requests

SYS = """你是一个文件检索 agent，工作在一个只读的代码仓库里。
你每次只输出一行，格式必须严格是下面几种之一：

  CALL list_dir <相对路径>
  CALL read_file <相对路径>
  CALL grep <关键词>
  ANSWER <答案>

流程：先 CALL，拿到工具结果后继续 CALL，直到能回答就 ANSWER。
不要输出解释、前言、代码块或任何多余文字。

示例：
用户: 找出定义 foo 函数的位置
你: CALL grep foo
工具结果: 命中 1 处: src/a.py:3
你: CALL read_file src/a.py
工具结果: 文件 src/a.py 共 20 行
你: ANSWER foo 定义在 src/a.py"""

CALL_RE = re.compile(r"^\s*CALL\s+(list_dir|read_file|grep)\s+(.+?)\s*$", re.M)
ANS_RE = re.compile(r"^\s*ANSWER\s+(.+?)\s*$", re.M)
THINK_RE = re.compile(r"<think>.*?</think>", re.S)

PAD_POOL = (
    'Traceback (most recent call last):\n'
    '  File "/opt/app/src/config_loader.py", line 12, in parse_config\n'
    '    with open(path) as fh:\n'
    "FileNotFoundError: [Errno 2] No such file or directory\n"
    "  During handling of the above exception, another exception occurred:\n"
    '  File "/opt/app/src/utils.py", line 4, in load_config\n'
    "KeyError: 'config'\n"
    "  [previous line repeated 3 more times]\n"
)


# 策略级建议表：推断级字段（§4.3），规则表查找，零 LLM 调用。
# 触发条件从"同一个 (act,target,err) 重复"放宽到"同一类失败（tool+code）累计 N 次"，
# 因为真实病理不只是"死磕同一个调用"，更多是"在不存在的路径之间反复游走"——
# 那种情况下 (act,target,err) 每次都不一样，旧条件永远不触发。
ADVICE_TABLE = {
    "NO_SUCH_FILE": "不要继续猜路径，先用 list_dir 看清目录里到底有什么",
    "NOT_A_DIR": "先 list_dir 上一级，确认目录名",
    "NO_MATCH": "换关键词，或先用 list_dir 定位文件再 read_file",
    "EMPTY_DIR": "换一个目录再找",
    "BAD_CALL": "只输出一行 CALL <tool> <arg> 或 ANSWER <答案>，不要任何解释",
}
STRATEGY_N = 3

REJECT_MSG = ("[校验] 答案不满足任务目标：题目要求给出 a 的**具体数值**，"
              "而你的回答没有给出数值（或只是说明文件不存在）。"
              "请用工具去读实际存在的那个文件，然后重新输出 ANSWER。")


def answer_ok(ans, scenario, names):
    """规则式目标校验 —— agent 不应该让模型自己宣布"答完了"就算完。"""
    if scenario == "missing_file":
        return ("1" in ans) and ("无法" not in ans)
    if scenario == "longtail":
        # 必须写 core/loader.py —— 只写 "loader.py" 的话 "config_loader.py" 也含这个子串，
        # 会把"指向一个不存在的文件"的幻觉答案判成通过
        return ("core/loader.py" in ans) and (str(names.get("value")) in ans)
    return True


def pad_text(txt, n_chars):
    if n_chars <= 0 or not txt:
        return ""
    s = ""
    while len(s) < n_chars:
        s += PAD_POOL
    return s[:n_chars]


HEAD_KEEP = 2          # system + 任务描述：任何模式都不丢（丢了就不是 agent，基线会变成稻草人）


def slide_window(msgs, n):
    """truncate 基线：钉住头部，只保留最近 n 条历史消息。

    窗口起点对齐到 assistant：否则窗口可能以 tool 结果开头，prompt 里出现两条连续 user，
    协议层面就错乱了 —— 那会让截断基线**变弱**，而我们要的是一个**强**基线。
    """
    if n <= 0 or len(msgs) <= HEAD_KEEP + n:
        return msgs
    keep = msgs[-n:]
    while keep and keep[0]["role"] != "assistant":
        keep = keep[1:]
    return msgs[:HEAD_KEEP] + keep


def strip_think(s):
    """Qwen3 是思考型模型：先剥掉 <think>...</think>，未闭合的（被 max_tokens 截断）整段丢弃。"""
    s = THINK_RE.sub("", s)
    i = s.find("<think>")
    if i >= 0:
        s = s[:i]
    return s.strip()


# ---------------------------------------------------------------- 沙盒与工具
NAME_POOL = ["config", "settings", "params", "options",
             "prefs", "profile", "manifest", "registry"]


def build_sandbox(root, scenario="easy", seed=0):
    """建一个小仓库。seed>0 时随机化 data/ 下的文件名 —— 用来生成一批**不同**的任务
    （temperature=0 下重复同一任务得到的是同一个样本，不是分布）。"""
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, "src"))
    os.makedirs(os.path.join(root, "data"))
    if seed:
        rng = random.Random(seed)
        real = rng.choice(NAME_POOL)
        want = rng.choice([n for n in NAME_POOL if n != real])
    else:
        real, want = "sample", "config"
    with open(os.path.join(root, "src", "config_loader.py"), "w", encoding="utf-8") as f:
        f.write("# config loading\n"
                "import json\n\n"
                "def parse_config(path):\n"
                "    with open(path) as fh:\n"
                "        return json.load(fh)\n\n"
                "def dump_config(cfg, path):\n"
                "    with open(path, 'w') as fh:\n"
                "        json.dump(cfg, fh)\n")
    with open(os.path.join(root, "src", "utils.py"), "w", encoding="utf-8") as f:
        f.write("def load_config(path):\n"
                "    from config_loader import parse_config\n"
                "    return parse_config(path)\n")
    with open(os.path.join(root, "data", real + ".json"), "w", encoding="utf-8") as f:
        f.write('{"a": 1}\n')
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
        f.write("# demo repo\n入口在 src/ 下。\n")
    if scenario == "longtail":
        # 带陷阱的仓库：文档故意指错文件，另有一个名字极像的函数做干扰项。
        # 目标要求"两件事都要报对"，任缺其一都会被目标校验驳回 → 逼出多次失败—重试。
        value = 100 + (seed or 1)                      # 与行号不冲突，避免校验器误判
        # ★ 必须先删掉 missing_file 场景预写的脚手架文件：
        #   它们里面也有 def parse_config，会造成"两个定义"→ 题目歧义 → correct 恒为 0
        for junk in ("src/config_loader.py", "src/utils.py"):
            jp = os.path.join(root, junk)
            if os.path.exists(jp):
                os.remove(jp)
        for d in ("src/core", "src/adapters", "src/utils", "docs"):
            os.makedirs(os.path.join(root, d), exist_ok=True)

        def w(rel, s):
            with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write(s)

        w("src/core/loader.py",
          '"""core loader"""\nimport json\n\ndef parse_config(path):\n'
          '    with open(path) as fh:\n        return json.load(fh)\n')
        w("src/core/legacy.py", '"""legacy"""\ndef load_config(path):\n    return None\n')
        w("src/adapters/json_adapter.py",
          '"""adapter"""\nfrom core.loader import parse_config\n\ndef dump(cfg):\n    return str(cfg)\n')
        w("src/utils/helpers.py", "def noop():\n    return 0\n")
        w("src/utils/paths.py", "DATA_DIR = 'data'\n")
        w("docs/guide.md",
          "# 配置解析说明\n\n本项目的配置解析入口叫 load_config，定义在 src/core/legacy.py。\n")
        w("data/" + real + ".json", '{"a": %d}\n' % value)
        w("data/" + real + "_bak.json", '{"a": 0}\n')
        return root, {"real": real, "want": want, "def_file": "src/core/loader.py",
                      "def_line": 4, "value": value}

    # missing_file 场景：任务里提到的 data/<want>.json 不存在，实际文件是 data/<real>.json。
    return root, {"real": real, "want": want}


def run_tool(root, tool, arg):
    """返回 (ok, code, world, has_info)。全部是规则式，零 LLM 调用。"""
    if tool == "list_dir":
        p = os.path.join(root, arg)
        if not os.path.isdir(p):
            return False, "NOT_A_DIR", "路径 %s 不是目录" % arg, False
        items = sorted(os.listdir(p))
        if not items:
            return True, "EMPTY_DIR", "目录 %s 为空" % arg, False
        return True, "", "目录 %s 含 %d 项: %s" % (arg, len(items), ", ".join(items[:8])), True

    if tool == "read_file":
        p = os.path.join(root, arg)
        if not os.path.isfile(p):
            near = []
            d = os.path.dirname(p) or root
            if os.path.isdir(d):
                near = sorted(os.listdir(d))[:6]
            return False, "NO_SUCH_FILE", ("文件 %s 不存在；%s 下现有: %s"
                                           % (arg, os.path.dirname(arg) or ".", ", ".join(near))), False
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        # ★ 必须下发内容：只回报"共几行"的话，任何需要读值的任务在工具层面就不可解
        body = "\n".join(lines[:80])
        return True, "", "文件 %s 共 %d 行，内容:\n%s" % (arg, len(lines), body), True

    if tool == "grep":
        hits = []
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, root)
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        for i, ln in enumerate(f, 1):
                            if arg in ln:
                                hits.append("%s:%d" % (rel, i))
                except OSError:
                    pass
        if not hits:
            return True, "NO_MATCH", "全仓库没有匹配 %r 的内容" % arg, False
        return True, "", "命中 %d 处: %s" % (len(hits), ", ".join(hits[:8])), True

    return False, "BAD_CALL", "未知工具 %s" % tool, False


# ---------------------------------------------------------------- 客户端
class LlmClient:
    def __init__(self, base, model, max_new=256, no_think=True, temperature=0.0, stream=False):
        self.base, self.model, self.max_new = base.rstrip("/"), model, max_new
        self.no_think, self.kw_ok = no_think, True
        self.temperature, self.stream = temperature, stream
        self.calls = []
        self.ttfts = []                        # 仅 --stream 时填充（E14）

    def chat(self, msgs):
        if self.stream:
            return self.chat_stream(msgs)
        payload = {"model": self.model, "messages": msgs,
                   "max_tokens": self.max_new, "temperature": self.temperature}
        if self.no_think and self.kw_ok:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        r = requests.post(self.base + "/v1/chat/completions", timeout=600, json=payload)
        if r.status_code != 200 and payload.pop("chat_template_kwargs", None) is not None:
            self.kw_ok = False                      # 旧版 vLLM 不认这个参数 → 退回重试一次
            print("    [!] chat_template_kwargs 不被接受，退回（会带着 <think> 跑）")
            r = requests.post(self.base + "/v1/chat/completions", timeout=600, json=payload)
        if r.status_code != 200:
            raise SystemExit("[x] HTTP %d: %s" % (r.status_code, r.text[:300]))
        j = r.json()
        u = j.get("usage") or {}
        d = u.get("prompt_tokens_details") or {}
        raw = j["choices"][0]["message"].get("content") or ""
        out = strip_think(raw)
        self.calls.append((u.get("prompt_tokens"), d.get("cached_tokens")))
        return out, u.get("prompt_tokens"), d.get("cached_tokens")

    def chat_stream(self, msgs):
        """--stream 路径（E14）：同一 payload 语义，流式收首 token 计 TTFT。
        usage 走最后一个 chunk（stream_options.include_usage）；拿不到就硬报错，
        因为 E14 需要 token×时间配对，静默降级会产出垃圾数据。"""
        payload = {"model": self.model, "messages": msgs,
                   "max_tokens": self.max_new, "temperature": self.temperature,
                   "stream": True, "stream_options": {"include_usage": True}}
        if self.no_think and self.kw_ok:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        t0 = time.time()
        r = requests.post(self.base + "/v1/chat/completions", timeout=600, json=payload, stream=True)
        if r.status_code != 200 and payload.pop("chat_template_kwargs", None) is not None:
            self.kw_ok = False
            r = requests.post(self.base + "/v1/chat/completions", timeout=600, json=payload, stream=True)
        if r.status_code != 200:
            raise SystemExit("[x] HTTP %d: %s" % (r.status_code, r.text[:300]))
        ttft, chunks, usage = None, [], None
        for ln in r.iter_lines(decode_unicode=True):
            if not ln or not ln.startswith("data:"):
                continue
            data = ln[5:].strip()
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
            except ValueError:
                continue
            if j.get("usage"):
                usage = j["usage"]
            ch = j.get("choices") or []
            if not ch:
                continue
            delta = (ch[0].get("delta") or {}).get("content")
            if delta:
                if ttft is None:
                    ttft = time.time() - t0
                chunks.append(delta)
        if usage is None:
            raise SystemExit("[x] 流式响应没有 usage（include_usage 未生效）—— E14 拒绝无 token 的 TTFT")
        d = usage.get("prompt_tokens_details") or {}
        raw = "".join(chunks)
        out = strip_think(raw)
        self.calls.append((usage.get("prompt_tokens"), d.get("cached_tokens")))
        self.ttfts.append(ttft)
        return out, usage.get("prompt_tokens"), d.get("cached_tokens")


class ScriptClient:
    """dry-run：不联网，按预设剧本输出，用来验证循环逻辑。"""
    def __init__(self):
        self.script = [
            'CALL read_file src/config.py',      # 失败：文件不存在
            'CALL read_file src/config.py',      # 再犯一次（验证墓碑能否防重犯）
            'CALL grep parse_config',            # 成功
            'ANSWER src/config_loader.py 第 4 行',
        ]
        self.i = 0
        self.calls = []

    def chat(self, msgs):
        out = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        self.calls.append((None, None))
        return out, None, None


# ------------------------------------------------ 放置位置消融（E11）
# 三个臂的 base（SYS + runtag）**逐字节相同**，唯一变量是「保留信息放在哪里」：
#   ours    —— 追加在消息列表**末尾**（前缀逐字节不变 → 缓存全命中）
#   sysend  —— 写进 system prompt 的**末尾**并整体替换（RIR 的放置方式，且是它的**最优**位置）
#   syshead —— 写进 system prompt 的**开头**并整体替换（最差位置）
# 注意：三个臂都照常 `del msgs[ckpt:]` 丢弃失败分支 —— 只有「放哪儿」在变。
MEM_HEAD = "[错题本·累积保留信息]\n"

# C 类解禁（2026-10-03，预注册 week1/预注册_C类解禁三实验_2026-10-03.md）：
#   placebo —— worldonly 的世界事实**内容**换成常数空串（结构/metadata 不变）：
#              隔离「world 字段的内容」这一层（Persp W4 安慰剂对照）。
#   generic —— 完全无内容的常数墓碑（连 act/target/err 都没有，且更短）：
#              隔离「随便一个紧凑尾部标记（recency/compactness）」这一层。
#   两臂的计数器照常推进、分支照常丢弃 —— 与 ours/worldonly 状态一致，消融才干净。
GENERIC_TAG = "[TAG] The previous turn made no progress and has been discarded."
PLACEBO_WORLD = "(no environment facts recorded)"


def build_sys(base, mem, where):
    """where='end' → 记忆块接在 system prompt 末尾；where='head' → 接在开头。
    mem 为空时返回原 base（保证首次失败前三个臂的 system 完全一致）。"""
    if not mem:
        return base
    block = MEM_HEAD + "\n".join(mem) + "\n\n"
    return (base + "\n\n" + block) if where == "end" else (block + base)


# ---------------------------------------------------------------- 主循环
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:18201")
    ap.add_argument("--model", default="Qwen3-4B")
    ap.add_argument("--mode",
                    choices=["b0", "ours", "rollback", "label", "truncate", "sysend", "syshead",
                             "worldonly", "placebo", "generic"],
                    default="ours",
                    help="b0=全量追加 / ours=丢弃+墓碑 / rollback=B3 丢弃无墓碑（A1 消融） / "
                         "label=B2 有标签无丢弃 / truncate=滑窗基线（A2） / "
                         "sysend=保留信息写进 system prompt 末尾并替换（E11 放置位置，RIR 的最优情形） / "
                         "syshead=同上但写进开头（E11 最差情形） / "
                         "worldonly=L2 消融：丢弃+墓碑，但墓碑里只留 world（关掉 advice/strategy/reset） / "
                         "placebo=E12 安慰剂：同 worldonly 但 world 内容换成常数空串（隔离 world 字段内容） / "
                         "generic=E12 对照：完全无内容的常数墓碑（隔离「随便一个紧凑尾部标记」）")
    ap.add_argument("--truncate-n", type=int, default=8,
                    help="truncate 模式保留的最近历史消息条数（不含被钉住的 system+任务）")
    ap.add_argument("--scenario", default="missing_file",
                    choices=["missing_file", "missing_keyword", "easy", "longtail"],
                    help="missing_file: 任务提到的文件不存在（诱发 NO_SUCH_FILE）；"
                         "missing_keyword: 关键词不存在（诱发 grep 零匹配）")
    ap.add_argument("--task", default="")
    ap.add_argument("--strategy-n", type=int, default=STRATEGY_N,
                    help="同类失败（tool+错误码）累计到几次就给策略级建议")
    ap.add_argument("--no-validate", action="store_true",
                    help="不做目标校验（默认校验：不达标的答案不结束，反馈后继续）")
    ap.add_argument("--no-check", action="store_true",
                    help="不校验答案正确性（默认校验：答案里必须同时出现真文件名与值 1）")
    ap.add_argument("--no-reset-cache", action="store_true",
                    help="开局不清前缀缓存（默认清，保证两种模式从同一状态出发）")
    ap.add_argument("--error-padding", type=int, default=0,
                    help="给工具错误补一段假 traceback（字符数），模拟真实崩溃日志的长度。"
                         "b0 会把它全量放进上下文，ours 只把 world 那一句放进上下文")
    ap.add_argument("--sandbox", default="./e5_sandbox")
    ap.add_argument("--seed", type=int, default=0,
                    help=">0 时随机化沙盒里的文件名，用来生成一批不同的任务（每次重复应该是新种子）")
    ap.add_argument("--notebook", default="./e5_notebook.md")
    ap.add_argument("--max-turns", type=int, default=10)
    ap.add_argument("--provider", choices=["llm", "script"], default="llm")
    ap.add_argument("--think", action="store_true", help="保留 Qwen3 的 thinking（默认关闭）")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="采样温度（E13 采样批用 0.7；正式批保持 0 = 确定性解码）")
    ap.add_argument("--stream", action="store_true",
                    help="流式请求并测每轮 TTFT（E14 专用；SUMMARY 口径不变，TTFT 另起行输出）")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    TASKS = {
        "missing_file": "读取配置文件 data/config.json，并报告其中 a 的值。",
        "missing_keyword": "找出定义 loadConfig 函数的位置，并报告它在第几行。",
        "easy": "找出定义 parse_config 的文件，并报告它在第几行。",
    }
    root, names = build_sandbox(os.path.abspath(a.sandbox), a.scenario, a.seed)
    if a.task:
        task = a.task
    elif a.scenario == "longtail":
        task = ("报告两件事：(1) parse_config 函数定义在哪个文件的第几行；"
                "(2) 读取配置文件 data/%s.json 并报告其中 a 的值。" % names["want"])
    elif a.scenario == "missing_file":
        task = "读取配置文件 data/%s.json，并报告其中 a 的值。" % names["want"]
    else:
        task = TASKS[a.scenario]
    client = (ScriptClient() if a.provider == "script"
              else LlmClient(a.base_url, a.model, no_think=not a.think,
                             temperature=a.temperature, stream=a.stream))
    if a.provider == "llm" and not a.no_reset_cache:
        try:
            rr = requests.post(a.base_url.rstrip("/") + "/reset_prefix_cache", timeout=20)
            rr.raise_for_status()                      # ★ 不校验状态码的话，404 也会"静默成功"
            print("已清空前缀缓存（两种模式从同一状态出发）")
        except Exception as exc:                       # noqa: BLE001
            print("[!] 清缓存失败（不影响本实验，但两种模式的起点可能不同）：%s" % exc)

    # 每次运行的 token 序列必须唯一：否则跨运行的前缀缓存复用会污染 prefill 指标
    # （/reset_prefix_cache 在 vLLM 0.18.1 上默认 404，清不掉）
    runtag = "\n\n[run=%s-%s-%s-%s]" % (a.scenario, a.seed, a.mode, os.urandom(3).hex())
    sysbase = SYS + runtag                      # E11：三个臂共用的冻结 base
    mem = []                                    # E11：累积的保留信息（sysend/syshead 用）
    msgs = [{"role": "system", "content": sysbase},
            {"role": "user", "content": task}]
    nb = ["# 错题本（外部，默认不进上下文）", ""]
    seen = {}                                  # (act,target,err) -> 次数，实现 §4.3 几何阈值
    rows = []
    print("模式 = %s%s   场景 = %s   沙盒 = %s"
          % (a.mode, ("(n=%d)" % a.truncate_n) if a.mode == "truncate" else "", a.scenario, root))
    print("任务: %s" % task)
    print()
    print("  轮  判定      工具/参数                 上下文(msgs)  prompt  cached")
    print("  " + "-" * 76)

    done = None
    rejections = 0
    tool_fails = 0
    fails_total = 0
    dup = 0                                    # 与上一轮**同一个调用**的回合数（A1 的读出量）
    prev_call = None
    for turn in range(1, a.max_turns + 1):
        if a.mode == "truncate":
            # ★ 必须在 chat 之前裁：否则上报的 prompt_tokens 是"裁剪前的足迹"，
            #   Pareto 图的横轴就废了
            msgs = slide_window(msgs, a.truncate_n)
        ckpt = len(msgs)                       # ★ 执行前检查点
        out, ptok, ctok = client.chat(msgs)

        m_ans = ANS_RE.search(out)
        if m_ans:
            ans = m_ans.group(1)
            if not a.no_validate and not answer_ok(ans, a.scenario, names):
                # ★ agent 行为：不达标的答案不算结束，反馈后继续（这才会有失败—重试循环）
                rejections += 1
                msgs.append({"role": "assistant", "content": out})
                msgs.append({"role": "user", "content": REJECT_MSG})
                print("  %2d  未达标  %-26s %6d    %5s  %5s" % (turn, ans[:26], len(msgs), ptok, ctok))
                rows.append((turn, "reject", "-", len(msgs), ptok, ctok, 0))
                continue
            msgs.append({"role": "assistant", "content": out})
            done = ans
            print("  %2d  回答      %-26s %6d    %5s  %5s" % (turn, ans[:26], len(msgs), ptok, ctok))
            rows.append((turn, "answer", "-", len(msgs), ptok, ctok, 0))
            break

        m = CALL_RE.search(out)
        if not m:
            tool, arg = "?", "?"
            ok, code, world, info = False, "BAD_CALL", "模型输出不符合协议: %r" % out[:40], False
        else:
            tool, arg = m.group(1), m.group(2).strip().strip('"')
            ok, code, world, info = run_tool(root, tool, arg)

        if prev_call is not None and (tool, arg) == prev_call:
            dup += 1                               # 字面重复：连着两轮同一个 (工具, 参数)
        prev_call = (tool, arg)
        failed = (not ok) or (not info)
        tool_fails += 1 if failed else 0
        kind = "失败" if failed else "成功"
        print("  %2d  %s    %-12s %-14s %6d    %5s  %5s"
              % (turn, kind, tool, arg[:14], len(msgs), ptok, ctok))

        # 工具结果正文：b0 / truncate / label 三个臂共用（成功轮不受 padding 影响，
        # 所以这一段与原 b0 分支逐字节等价）
        body = "工具结果: " + ("错误 " + code + " " if not ok else "") + world
        if failed and a.error_padding:
            body += "\n" + pad_text(PAD_POOL, a.error_padding)     # 真实崩溃日志是这么长的

        # 墓碑文本：ours 用它**替换**整条分支；label 用它**追加**在完整轨迹之后；
        # rollback 算了但不用 —— 三个臂的计数器状态因此完全一致，消融才干净
            tag = ""
            if failed:
                fkey = (tool, arg, code or "-")        # 精细：同一个调用
                ckey = (tool, code or "-")            # 粗：同一类失败（跨目标）
                seen[fkey] = seen.get(fkey, 0) + 1
                seen[ckey] = seen.get(ckey, 0) + 1
                n, nc = seen[fkey], seen[ckey]
                advice = ""
                # ★ L2 新臂 worldonly：计数器**照常推进**（否则与 ours 的状态就不一致，消融不干净），
                #   但墓碑里一个推理/指令字段都不放 —— 只留 act/target/err/n/world。
                #   它回答的是 F2：「起作用的是关于世界的一行字，还是那句规则注入的停止指令」。
                #   E12 的 placebo/generic 同理：计数器照走、advice 全关。
                quiet = a.mode in ("worldonly", "placebo", "generic")
                if n >= 2 and not quiet:              # 精细级：同一个调用反复失败
                    advice += " advice=同一调用已失败 %d 次，换目标" % n
                if nc >= a.strategy_n and code in ADVICE_TABLE and not quiet:
                    advice += " strategy=%s（同类失败已 %d 次）" % (ADVICE_TABLE[code], nc)
                # ★ 全局失败计数：模型会在 read_file / grep / list_dir 之间换着来，
                #   任何"按 (工具,错误码) 分组"的计数都可能永远到不了阈值。
                #   到 5 的倍数就给一次强制性的"停下来重新规划"提示。
                fails_total += 1
                if fails_total % 5 == 0 and ADVICE_TABLE and not quiet:
                    advice += (" reset=本任务已累计 %d 次无进展。停下来：先用 list_dir 把仓库结构完整列一遍，"
                               "再选最小的可行步骤，不要继续猜路径。" % fails_total)
                # ★ E12 placebo：world 字段的**内容**换成常数空串（nb 里仍记真实 world ——
                #   外部错题本是证据，不受墓碑口径影响）
                world_tag = PLACEBO_WORLD if a.mode == "placebo" else world
                tag = "[TAG] act=%s target=%s err=%s n=%d world=%s%s" % (
                    tool, arg, code or "-", n, world_tag, advice)

        if a.mode in ("b0", "truncate") or not failed:
            msgs.append({"role": "assistant", "content": out})
            msgs.append({"role": "user", "content": body})
            tag_tokens = 0
        elif a.mode == "label":
            # B2（有标签无丢弃）：完整轨迹照进，**再**把墓碑拼进同一条 user 消息。
            #   与 b0 的唯一差别就是多了那一行 → B2 − B0 = 「标签单独的效应」
            #   （回答：轨迹在场时那句话还有用吗？）
            nb.append("- t=%d act=%s target=%s err=%s world=%s" % (turn, tool, arg, code or "-", world))
            msgs.append({"role": "assistant", "content": out})
            msgs.append({"role": "user", "content": body + "\n" + tag})
            tag_tokens = None
        else:
            # ② 完整证据进外部错题本；③ 丢弃整条分支
            nb.append("- t=%d act=%s target=%s err=%s world=%s" % (turn, tool, arg, code or "-", world))
            del msgs[ckpt:]                       # ★ 纯列表操作
            if a.mode == "rollback":
                # B3（有丢弃无标签）：上下文逐字节回到失败前那一次请求。
                #   temperature=0 下模型因此会重发同一个动作（方案 §7.1 的「会字面重复」），
                #   这正是 A1 要验证的：不做墓碑，丢弃本身能不能撑住。
                tag_tokens = 0
                print("       (rollback：丢弃整条，无墓碑，上下文回到 %d 条)" % len(msgs))
            elif a.mode in ("sysend", "syshead"):
                # E11：保留信息写进 system prompt 并**整体替换**（= RIR 的放置方式）。
                #   消息列表照常丢弃失败分支 —— 与 ours 的唯一差别就是「放哪儿」。
                mem.append(tag)
                msgs[0]["content"] = build_sys(sysbase, mem,
                                               "end" if a.mode == "sysend" else "head")
                tag_tokens = 0
                print("       (%s：保留信息进 system prompt 的%s，块 %d 行，system 现 %d 字符)"
                      % (a.mode, "末尾" if a.mode == "sysend" else "开头",
                         len(mem), len(msgs[0]["content"])))
            elif a.mode == "generic":
                # E12 generic 对照：丢弃 + 一句**完全无内容**的常数墓碑（连 act/target/err 都没有，
                # 而且更短）。它隔离的是「随便一个紧凑尾部标记（recency/compactness）」这一层：
                # 若 generic ≈ worldonly，则内容无关、紧凑性就够 —— 论文的机制解释要改写。
                msgs.append({"role": "user", "content": GENERIC_TAG})
                tag_tokens = None
                print("       墓碑(generic): %s" % GENERIC_TAG)
            else:                                  # ours / worldonly / placebo：丢弃 + 墓碑
                msgs.append({"role": "user", "content": tag})
                print("       墓碑: %s" % tag[:240])
                tag_tokens = None
        rows.append((turn, "fail" if failed else "ok", "%s %s" % (tool, arg), len(msgs), ptok, ctok, tag_tokens))
        if a.stream and ptok is not None and getattr(client, "ttfts", None):
            print("       TTFT turn=%d prefill=%d ms=%.1f"
                  % (turn, ptok - (ctok or 0), 1000.0 * client.ttfts[-1]))

    with open(a.notebook, "w", encoding="utf-8") as f:
        f.write("\n".join(nb) + "\n")

    print("  " + "-" * 76)
    print()
    if done:
        print("[完成] 答案: %s" % done)
    else:
        print("[未完成] 达到轮数上限")
    print("错题本 → %s（%d 条）" % (a.notebook, len(nb) - 2))
    print("最终上下文消息数 = %d" % len(msgs))

    # 答案正确性：规则式校验，标准答案在沙盒里（data/<real>.json 是 {"a": 1}）
    correct = 0
    if done and not a.no_check and a.scenario == "longtail":
        correct = 1 if answer_ok(done, a.scenario, names) else 0
    if done and not a.no_check and a.scenario == "missing_file":
        # 判据只留一条：答案里给出了数值 1。
        # 前两版都错过：① 要求出现真文件名 → 把 "a 的值是 1。" 判错；
        #              ② 排除含"不存在"的 → 把 "X 不存在，但 Y 中 a 的值为 1" 判错。
        correct = 1 if ("1" in done) else 0

    # 机器可读汇总行：方便用 shell 循环跑 N 次再统计（E5-b）
    pts = [r[4] for r in rows]
    cts = [r[5] for r in rows]
    integral = sum(p for p in pts if p is not None)
    prefill = sum((p - (c or 0)) for p, c in zip(pts, cts) if p is not None)
    print("SUMMARY mode=%s scenario=%s seed=%d real=%s want=%s padding=%d wn=%d turns=%d msgs=%d "
          "integral=%d prefill=%d answered=%d correct=%d rejects=%d tools_fail=%d dup=%d"
          % (a.mode, a.scenario, a.seed, names["real"], names["want"], a.error_padding,
             a.truncate_n if a.mode == "truncate" else 0,
             len(rows), len(msgs), integral, prefill, 1 if done else 0, correct, rejections,
             tool_fails, dup))
    if done:
        print("ANSWER  %s" % done[:150])
    if a.stream and getattr(client, "ttfts", None):
        tts = client.ttfts
        s = sorted(tts)
        print("TTFT_SUMMARY mode=%s n=%d mean_ms=%.1f p50_ms=%.1f max_ms=%.1f"
              % (a.mode, len(tts), 1000.0 * sum(tts) / len(tts),
                 1000.0 * s[len(s) // 2], 1000.0 * max(tts)))

    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["turn", "kind", "call", "msgs", "prompt_tokens", "cached_tokens", "tag_tokens"])
            w.writerows(rows)
        print("CSV → %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
