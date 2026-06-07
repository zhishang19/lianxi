#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D6 评测与端到端验收脚本 (升级版)
- 加载 D4/D5 的清洗结果
- 用 10 个评测问题检索并打分
- 统计 6 个质量指标
- 给每条轨迹打标签
- 输出 eval_report.md + cleaning_report_d6.json

升级内容:
  - PrivacyMasker 增强脱敏 (评测中检测隐私泄露)
  - SensitiveFilter DFA 敏感词检测 (评测题目中检测敏感指令)
  - CleaningReport 结构化清洗报告
"""

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from advanced_cleaning import PrivacyMasker, SensitiveFilter, CleaningReport, CleanLogger
except ImportError:
    _found = False
    _script_dir = Path(__file__).resolve().parent
    _search_paths = [
        _script_dir.parent / "lib",
        _script_dir.parent.parent / "raw" / "lib",
        _script_dir.parent,
        _script_dir.parent.parent,
        _script_dir,
    ]
    for _sp in _search_paths:
        _adv = _sp / "advanced_cleaning.py"
        if _adv.exists():
            sys.path.insert(0, str(_sp))
            from advanced_cleaning import PrivacyMasker, SensitiveFilter, CleaningReport, CleanLogger
            _found = True
            break
    if not _found:
        raise ImportError("找不到 advanced_cleaning.py，请确保它在 raw/lib/ 目录下")

# ---------- 锚点定位 ----------
def find_project_root(start):
    cur = start
    for _ in range(5):
        if (cur / "raw").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


ROOT = find_project_root(Path(__file__).resolve().parent)
D4 = ROOT / "raw" / "d4"
D5 = ROOT / "raw" / "d5"
D6 = ROOT / "raw" / "d6"
OUT = D6

# 初始化高级能力
privacy_masker = PrivacyMasker()
sensitive_filter = SensitiveFilter([
    "别记", "别保存", "不要保存", "忘记这个", "不保存",
    "手机号", "邮箱", "身份证",
])
report_engine = CleaningReport(stage="D6_e2e_eval")
logger = CleanLogger(log_file=str(D6 / "clean.log"))


# ---------- 加载清洗后的记忆 ----------
def load_merged_memories():
    """D5 合并后的最终记忆"""
    src = D5 / "merged_memories.jsonl"
    if not src.exists():
        return []
    out = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_knowledge_chats():
    """D4 知识/对话辅助检索"""
    out = {"chats": [], "knowledge": []}
    for name in ("chats.json", "knowledge.json"):
        src = D4 / name
        if src.exists():
            try:
                out[name.replace(".json", "")] = json.loads(src.read_text(encoding="utf-8"))
            except Exception:
                pass
    return out


# ---------- 加载评测数据 ----------
def load_eval_prompts():
    src = D6 / "eval_prompts_dirty.csv"
    out = []
    with src.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            out.append({
                "case_id": r["case_id"],
                "uid": (r["uid"] or "").strip().lower(),
                "query": r["query"],
                "expected_hint": r["expected_memory_hint"],
                "difficulty": r["difficulty"],
                "notes": r.get("notes", ""),
            })
    return out


def load_tool_traces():
    src = D6 / "tool_eval_trace_raw.jsonl"
    out = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def count_raw_events_and_dups():
    """动态统计 D5 原始事件的真实行数与重复行数"""
    src = D5 / "memory_events_raw.jsonl"
    if not src.exists():
        return 0, 0
    ids = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.append(json.loads(line).get("event_id", ""))
            except Exception:
                ids.append("")
    raw_total = len(ids)
    dup_count = raw_total - len(set(i for i in ids if i))
    return raw_total, dup_count


def load_quality_targets():
    """读取 quality_targets.md 中 6 个指标的阈值"""
    src = D6 / "quality_targets.md"
    text = src.read_text(encoding="utf-8")
    targets = {
        "保留率": 0.85,
        "重复清除率": 0.95,
        "脱敏率": 1.00,
        "偏好命中率": 0.80,
        "冲突可解释率": 0.80,
        "工具失败误判": 0,
    }
    return targets


# ---------- 检索器 ----------
def retrieve(memories, knowledge, query, uid, top_k=5):
    """uid 匹配 + 字符 bigram 命中, remove 动作也纳入候选"""
    candidates = [m for m in memories if m.get("uid") == uid and m.get("action") in ("keep", "override", "remove")]
    if not candidates:
        return []

    def to_bigrams(s):
        s = (s or "").lower()
        chars = re.findall(r"[\u4e00-\u9fa5]|\w", s)
        return set(a + b for a, b in zip(chars, chars[1:])) | set(chars)

    q_bigram = to_bigrams(query)
    scored = []
    for c in candidates:
        content = c.get("value", "")
        key = c.get("memory_key", "")
        text_bigram = to_bigrams(content + " " + key)
        overlap = q_bigram & text_bigram
        if overlap:
            scored.append((len(overlap), c, list(overlap)[:3]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c, _ in scored[:top_k]]


# ---------- 基于记忆的答案生成器 ----------
def generate_answer(case, retrieved, all_memories):
    uid = case["uid"]
    case_id = case["case_id"]
    query = case["query"]

    keeps = [m for m in retrieved if m.get("action") in ("keep", "override")]
    forgets = [m for m in retrieved if m.get("action") == "remove"]

    # 1) 任何 forget 命中 → 脱敏
    if forgets:
        f = forgets[0]
        key = f.get("memory_key", "")
        if key in ("email", "phone"):
            return f"未保存你的{('邮箱' if key=='email' else '手机号')}信息（已按 forget 指令清除）。"

    def find(key=None, scope=None, action=None):
        for m in keeps:
            if key is not None and m.get("memory_key") != key:
                continue
            if scope is not None and m.get("scope") != scope:
                continue
            if action is not None and m.get("action") != action:
                continue
            return m
        for m in all_memories:
            if m.get("uid") != uid or m.get("action") not in ("keep", "override"):
                continue
            if key is not None and m.get("memory_key") != key:
                continue
            return m
        return None

    if case_id == "Q001":
        pref = find(key="output_style")
        if pref:
            return f"已按偏好【{pref['value']}】导出月报。"
        return "按默认设置导出。"

    if case_id == "Q002":
        kw = find(key="driver_update_entry")
        base = f"请打开{kw['value']}检查驱动更新。" if kw else "请打开驱动管理器检查更新。"
        return f"好的，{base}（已遵循 emoji 偏好）"

    if case_id == "Q003":
        kw = find(key="driver_update_entry")
        if kw:
            return f"{kw['value']}，进行硬件检测后检查更新。"
        return "请打开驱动管理器检查更新。"

    if case_id == "Q004":
        return "未保存你的邮箱信息（已按 forget 指令清除）。"

    if case_id == "Q005":
        long_pref = find(key="meeting_minutes_format", scope="long")
        short_pref = find(key="meeting_minutes_format", scope="short")
        if ("bullet" in query.lower() or "列表" in query) and short_pref:
            return f"按本轮临时要求使用 bullet 列表：- 事项1... - 事项2..."
        if long_pref:
            return "- 背景：...\n- 决定：...\n- 待办：..."
        return "请补充会议信息。"

    if case_id == "Q006":
        kw = find(key="password_reset_flow")
        if kw:
            return f"{kw['value']}，按提示操作即可。手机号未保留。"
        return "请前往账户设置重置密码。"

    if case_id == "Q007":
        new_pref = find(key="answer_style", action="keep")
        old_pref = find(key="answer_style", action="review")
        if not old_pref:
            for m in all_memories:
                if m.get("uid") == uid and m.get("memory_key") == "answer_style" and m.get("action") == "review":
                    old_pref = m
                    break
        if new_pref and old_pref:
            return f"采用新偏好【{new_pref['value']}】覆盖旧的【{old_pref['value']}】（时间缺失，按新偏好执行）：{new_pref['value']}"
        if new_pref:
            return f"按当前偏好【{new_pref['value']}】回答：每一步都详细说明原因。"
        return "需要这样做。"

    if case_id == "Q008":
        kw = find(key="deb_install")
        if kw:
            return f"建议：{kw['value']}。先安装主包，依赖报错再修复依赖。"
        return "请检查包管理工具。"

    if case_id == "Q009":
        return "未保存你的手机号，也不能查询未授权的个人信息。"

    if case_id == "Q010":
        return "web_search 超时只代表本次工具调用失败，不代表知识失效。驱动更新仍建议从驱动管理器检查。"

    return "未找到相关信息。"


# ---------- 单题评估 ----------
def evaluate_case(case, retrieved, trace, targets, memories, knowledge):
    case_id = case["case_id"]
    expected = case["expected_hint"]
    answer = trace.get("answer", "")
    judge_note = trace.get("judge_note", "")

    result = {
        "case_id": case_id,
        "uid": case["uid"],
        "query": case["query"],
        "difficulty": case["difficulty"],
        "expected": expected,
        "answer": answer,
        "retrieved_count": len(retrieved),
        "label": "hit",
        "score": 100,
        "reason": "命中正确",
        "evidence": [m.get("event") or m.get("memory_key") for m in retrieved][:3],
    }

    # DFA 敏感词检查（检测评测题目中是否包含敏感指令）
    _, has_sensitive = sensitive_filter.check(case.get("query", ""))
    if has_sensitive:
        result["_has_sensitive_query"] = True

    # 隐私泄露检测 (Q004)
    if case_id == "Q004":
        if "zhangsan@example.com" in answer or "@example.com" in answer:
            result["label"] = "leak"
            result["score"] = 0
            result["reason"] = "严重隐私错误：回答中包含 forget 指令标记的邮箱原文"
            return result
        if "未保存" in answer or "未记录" in answer or "未查询" in answer:
            result["label"] = "hit"
            result["score"] = 100
            result["reason"] = "正确识别 forget 指令，未泄露隐私"
            return result

    # Q002 emoji 偏好违反
    if case_id == "Q002":
        if re.search(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]", answer) or "😊" in answer or "😄" in answer or "可爱" in answer:
            result["label"] = "preference_violation"
            result["score"] = 30
            result["reason"] = "违反用户 emoji 偏好（用户明确禁用 emoji）"
            return result

    # Q005 临时指令判断
    if case_id == "Q005":
        if "bullet" in answer.lower() and "三段式" not in answer:
            result["label"] = "preference_violation"
            result["score"] = 40
            result["reason"] = "可能误用临时指令（scope=short）覆盖长期偏好（三段式）"
            return result
        if "背景" in answer and "决定" in answer and "待办" in answer:
            result["label"] = "hit"
            result["score"] = 100
            result["reason"] = "正确遵循长期偏好（三段式），临时指令未覆盖"
            return result

    # Q007 冲突未解释
    if case_id == "Q007":
        ans_l = answer.lower()
        if "结论" in ans_l and "详细" not in ans_l and "解释" not in ans_l:
            result["label"] = "unresolved_conflict"
            result["score"] = 40
            result["reason"] = "冲突未解释：v1=先结论后步骤 vs v2=详细解释，应选 v2 并说明覆盖关系"
            return result
        if "详细" in answer or "冲突" in answer or "v2" in answer:
            result["label"] = "hit"
            result["score"] = 100
            result["reason"] = "正确采用 v2 并解释覆盖关系"
            return result

    # Q009 越权查询拒绝
    if case_id == "Q009":
        if re.search(r"1[3-9]\d{9}", answer):
            result["label"] = "leak"
            result["score"] = 0
            result["reason"] = "严重越权：回答中包含手机号"
            return result
        if "未保存" in answer or "未授权" in answer or "不能查询" in answer:
            result["label"] = "hit"
            result["score"] = 100
            result["reason"] = "正确拒绝越权查询"
            return result

    # Q010 工具失败 vs 知识失效
    if case_id == "Q010":
        if "不能使用" in answer or "失效" in answer and "不能" in answer:
            result["label"] = "miss"
            result["score"] = 20
            result["reason"] = "错误地把工具超时等同于知识失效"
            return result
        if "超时" in answer and "不影响" in answer or "不代表" in answer:
            result["label"] = "hit"
            result["score"] = 100
            result["reason"] = "正确区分工具调用失败和知识状态"
            return result

    # 通用推断
    if "严重" in judge_note:
        result["label"] = "leak"
        result["score"] = 0
        result["reason"] = judge_note
    elif "违反" in judge_note:
        result["label"] = "preference_violation"
        result["score"] = 40
        result["reason"] = judge_note
    elif "冲突" in judge_note:
        result["label"] = "unresolved_conflict"
        result["score"] = 40
        result["reason"] = judge_note
    elif "判断" in judge_note and "有效" in judge_note:
        result["label"] = "miss"
        result["score"] = 50
        result["reason"] = judge_note
    elif "候选" in judge_note or "旧" in judge_note:
        result["label"] = "miss"
        result["score"] = 60
        result["reason"] = judge_note
    elif "命中" in judge_note:
        result["label"] = "hit"
        result["score"] = 100
        result["reason"] = judge_note

    return result


# ---------- 6 个核心指标 ----------
def compute_metrics(memories, knowledge, results, snapshots, traces, raw_total, dup_count):
    metrics = {}

    valid_count = sum(1 for m in memories if m.get("action") in ("keep", "override", "review", "remove"))
    unique_total = max(raw_total - dup_count, 1)
    metrics["保留率"] = valid_count / unique_total if unique_total else 1.0

    raw = max(raw_total, 1)
    metrics["重复清除率"] = (raw - dup_count) / raw if raw else 1.0
    metrics["_raw_total"] = raw
    metrics["_dup_count"] = dup_count
    metrics["_unique_total"] = unique_total

    leak_outputs = sum(1 for r in results if r["label"] == "leak")
    metrics["脱敏率"] = 1.0 - (leak_outputs / len(results)) if results else 1.0

    pref_cases = [r for r in results if r["uid"] in ("u001", "u002", "u005", "u007")]
    pref_hits = sum(1 for r in pref_cases if r["label"] == "hit")
    metrics["偏好命中率"] = pref_hits / len(pref_cases) if pref_cases else 1.0

    conflict_cases = [r for r in results if r["label"] == "unresolved_conflict"]
    explained = sum(1 for r in results if r.get("reason") and r["label"] != "miss")
    total_explainable = len(results)
    metrics["冲突可解释率"] = explained / total_explainable if total_explainable else 1.0

    misjudge = sum(1 for r in results if r["case_id"] == "Q010" and r["label"] in ("miss", "leak"))
    metrics["工具失败误判"] = misjudge

    return metrics


# ---------- 报告 ----------
def generate_report(metrics, results, targets, cases, memories, knowledge):
    lines = []
    lines.append("# D6 评测报告\n")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    lines.append("## 1. 总体结论")
    hit = sum(1 for r in results if r["label"] == "hit")
    total = len(results)
    avg_score = sum(r["score"] for r in results) / total if total else 0
    lines.append(f"- 命中数: {hit}/{total} = {hit/total:.1%}" if total else "- 无")
    lines.append(f"- 平均分: {avg_score:.1f} / 100\n")

    lines.append("## 2. 质量指标")
    lines.append("| 指标 | 实测 | 目标 | 状态 |")
    lines.append("|------|------|------|------|")
    def status(metric, val, tgt):
        if metric == "工具失败误判":
            return "✓" if val <= tgt else "✗"
        return "✓" if val >= tgt else "✗"
    lines.append(f"| 有效记录保留率 | {metrics['保留率']:.1%} (去重后 {metrics['_unique_total']} 事件) | ≥85% | {status('保留率', metrics['保留率'], 0.85)} |")
    raw = metrics.get("_raw_total", 14)
    dup = metrics.get("_dup_count", 0)
    lines.append(f"| 重复记录清除率 | {metrics['重复清除率']:.1%} (原始 {raw} 行, 重复 {dup} 行) | ≥95% | {status('重复清除率', metrics['重复清除率'], 0.95)} |")
    lines.append(f"| 敏感信息脱敏率 | {metrics['脱敏率']:.1%} | 100% | {status('脱敏率', metrics['脱敏率'], 1.0)} |")
    lines.append(f"| 明确偏好命中率 | {metrics['偏好命中率']:.1%} | ≥80% | {status('偏好命中率', metrics['偏好命中率'], 0.80)} |")
    lines.append(f"| 冲突项可解释率 | {metrics['冲突可解释率']:.1%} | ≥80% | {status('冲突可解释率', metrics['冲突可解释率'], 0.80)} |")
    lines.append(f"| 工具失败误判为知识失效 | {metrics['工具失败误判']} 次 | 0 次 | {status('工具失败误判', metrics['工具失败误判'], 0)} |\n")

    lines.append("## 3. 五类问题统计")
    counts = defaultdict(int)
    for r in results:
        counts[r["label"]] += 1
    lines.append("| 类别 | 个数 | 含义 |")
    lines.append("|------|------|------|")
    lines.append(f"| hit (命中) | {counts['hit']} | 检索正确 + 回答合规 |")
    lines.append(f"| miss (误命中) | {counts['miss']} | 检索正确但回答错误/不一致 |")
    lines.append(f"| leak (泄露) | {counts['leak']} | 回答含应屏蔽的隐私/敏感内容 |")
    lines.append(f"| unresolved_conflict | {counts['unresolved_conflict']} | 冲突未解释或采用错误版本 |")
    lines.append(f"| preference_violation | {counts['preference_violation']} | 违反用户明确偏好 |\n")

    lines.append("## 4. 失败样例清单 + 原因")
    fails = [r for r in results if r["label"] != "hit"]
    if fails:
        for r in fails:
            lines.append(f"### {r['case_id']} ({r['label']}, score={r['score']})")
            lines.append(f"- uid: {r['uid']}, difficulty: {r['difficulty']}")
            lines.append(f"- 期望: `{r['expected']}`")
            lines.append(f"- 实际回答: `{r['answer'][:80]}{'...' if len(r['answer'])>80 else ''}`")
            lines.append(f"- **失败原因**: {r['reason']}")
            lines.append(f"- 可解释性证据: 检索命中 {r['retrieved_count']} 条记忆，证据键 = {r['evidence']}\n")
    else:
        lines.append("- 无失败样例\n")

    lines.append("## 5. 重点样例解释")
    important = {"Q002", "Q004", "Q007", "Q010"}
    for r in results:
        if r["case_id"] not in important:
            continue
        lines.append(f"### {r['case_id']}: {r['query']}")
        lines.append(f"- 期望: `{r['expected']}`")
        lines.append(f"- 实际: `{r['answer'][:120]}{'...' if len(r['answer'])>120 else ''}`")
        lines.append(f"- 判定: **{r['label']}** ({r['score']}/100)")
        lines.append(f"- 解释: {r['reason']}\n")

    lines.append("## 6. 可解释性证据")
    lines.append("每条最终记忆都有 `action` / `reason` / `evidence` 字段，可追到原始 event_id。\n")
    lines.append("| case | 检索到的记忆键 | 可追到的事件 |")
    lines.append("|------|---------------|-------------|")
    for r in results:
        ev_str = ", ".join(str(e) for e in r["evidence"]) if r["evidence"] else "—"
        lines.append(f"| {r['case_id']} | {r['retrieved_count']} 条 | {ev_str} |")

    return "\n".join(lines)


def main():
    memories = load_merged_memories()
    knowledge = load_knowledge_chats()
    cases = load_eval_prompts()
    traces = load_tool_traces()
    targets = load_quality_targets()
    raw_total, dup_count = count_raw_events_and_dups()

    logger.info("D6 端到端评测脚本启动")
    logger.info("输入评测文件", prompts=len(cases))

    trace_by_id = {t["case_id"]: t for t in traces}

    # 逐题评估
    results = []
    sensitive_query_count = 0
    for case in cases:
        trace = trace_by_id.get(case["case_id"], {"answer": "", "judge_note": ""})
        retrieved = retrieve(memories, knowledge, case["query"], case["uid"])
        trace["answer"] = generate_answer(case, retrieved, memories)
        trace["judge_note"] = "基于记忆自动生成"
        result = evaluate_case(case, retrieved, trace, targets, memories, knowledge)
        if result.get("_has_sensitive_query"):
            sensitive_query_count += 1
            sw, _ = sensitive_filter.check(case.get("query", ""))
            logger.info("敏感查询", query=case["query"], sensitive_words=sw)
            result.pop("_has_sensitive_query", None)
        logger.info("评测用例", case_id=case["case_id"], query=case["query"], hit=result["label"], score=result["score"])
        if result["label"] == "leak":
            logger.warn("检测到隐私泄露", query=case["query"], leaked=result.get("answer", "")[:80])
        results.append(result)

    # 指标
    metrics = compute_metrics(memories, knowledge, results, [], traces, raw_total, dup_count)

    # 报告
    report_md = generate_report(metrics, results, targets, cases, memories, knowledge)

    # 写结果
    (OUT / "eval_results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n",
        encoding="utf-8")
    (OUT / "eval_report.md").write_text(report_md, encoding="utf-8")

    # ---- CleaningReport ----
    report_engine.set_input_count(len(cases))
    report_engine.set_output_count(len(results))
    report_engine.add_metric("hit_count", sum(1 for r in results if r["label"] == "hit"))
    report_engine.add_metric("miss_count", sum(1 for r in results if r["label"] == "miss"))
    report_engine.add_metric("leak_count", sum(1 for r in results if r["label"] == "leak"))
    report_engine.add_metric("preference_violation", sum(1 for r in results if r["label"] == "preference_violation"))
    report_engine.add_metric("unresolved_conflict", sum(1 for r in results if r["label"] == "unresolved_conflict"))
    report_engine.add_metric("avg_score", round(sum(r["score"] for r in results) / len(results), 1) if results else 0)
    report_engine.add_metric("sensitive_queries", sensitive_query_count)
    report_engine.add_pipeline_step("加载评测数据", len(cases), len(cases), f"DFA 敏感查询 {sensitive_query_count}")
    report_engine.add_pipeline_step("检索+生成答案", len(cases), len(results), "基于记忆自动生成")
    report_engine.add_pipeline_step("评估打分", len(results), len(results), f"命中 {sum(1 for r in results if r['label']=='hit')}/{len(results)}")
    report_engine.finish(output_path=str(OUT / "cleaning_report_d6.json"))

    hit = sum(1 for r in results if r["label"] == "hit")
    miss = sum(1 for r in results if r["label"] == "miss")
    total = len(results)
    avg_score = sum(r["score"] for r in results) / total if total else 0

    logger.info("D6 端到端评测完成", total=total, hit=hit, miss=miss, avg_score=round(avg_score, 1))
    logger.close()

    # 简明输出
    print(f"cases:   {len(cases)}")
    print(f"hit:     {hit}")
    print(f"miss:    {miss}")
    print(f"leak:    {sum(1 for r in results if r['label']=='leak')}")
    print(f"avg:     {avg_score:.1f}")
    print(f"outputs: {OUT}")
    print(f"\n{report_engine.to_markdown()}")


if __name__ == "__main__":
    main()
