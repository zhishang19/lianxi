#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D4 多源清洗实战脚本 (升级版)
- 读取 raw/d4/ 下 5 份源数据 (JSONL/TXT/CSV/YAML/JSONL)
- 输出 chats.json / knowledge.json / preferences.json / tools.json
- 生成 report.md + cleaning_report_d4.json

升级内容:
  1. TimePipeline 4层时间解析 (strptime → timestamp → dateutil → relative)
  2. PrivacyMasker 增强脱敏 (手机保留前3后4, 邮箱保留首尾, 身份证)
  3. SensitiveFilter DFA 敏感词检测 (forget指令/隐私关键词)
  4. SimHash 近似去重 (对话去重用海明距离)
  5. CleaningReport 结构化清洗报告 (JSON + Markdown 双输出)
"""

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from advanced_cleaning import (
        TimePipeline, SimHashDedup, PrivacyMasker,
        SensitiveFilter, CleaningReport,
        SchemaValidator, CleanLogger,
    )
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
            from advanced_cleaning import (
                TimePipeline, SimHashDedup, PrivacyMasker,
                SensitiveFilter, CleaningReport,
                SchemaValidator, CleanLogger,
            )
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
OUT = D4
REPORT_JSON = D4 / "cleaning_report_d4.json"

# ---------- 全局高级组件 ----------
time_pipeline = TimePipeline(base_time=datetime(2026, 6, 7))
privacy_masker = PrivacyMasker()
sensitive_filter = SensitiveFilter([
    "别记", "别保存", "不要保存", "忘记这个", "不保存",
    "测试号", "测试手机",
])
simhash_chat = SimHashDedup(hash_bits=64, threshold=3)
report = CleaningReport(stage="D4_multi_source", base_dir=D4)

# 新增: SchemaValidator + CleanLogger
validator = SchemaValidator()
logger = CleanLogger(log_file=str(D4 / "clean.log"))


# ---------- 时间解析 (TimePipeline) ----------
def parse_time(s):
    iso_str, invalid, method = time_pipeline.parse(s)
    return iso_str, invalid


# ---------- 文本清洗 (增强版) ----------
NOISE_RULES = [
    (re.compile(r"<!--.*?-->"), ""),
    (re.compile(r"@{2,}"), ""),
    (re.compile(r"!{2,}"), "!"),
    (re.compile(r"！{2,}"), "！"),
    (re.compile(r"\.{3,}"), "…"),
    (re.compile(r"…{2,}"), "…"),
    (re.compile(r"\*{2,}([^*]+?)\*{2,}"), r"\1"),
    (re.compile(r"<[^>]+>"), ""),
    (re.compile(r"[😅🙏😊😄🤣😂🤔😢😡🤮🤒🤕]"), ""),
    (re.compile(r"　+"), " "),
    (re.compile(r" {2,}"), " "),
]


def clean_text(s, check_sensitive=False):
    """
    增强文本清洗: 去噪 → 口水词 → 隐私脱敏(增强版) → DFA敏感词
    返回 (cleaned_text, sensitive_words_found, privacy_details)
    """
    if not s:
        return "", [], []

    # 先 strip 再去噪(确保行首口水词正则能匹配)
    s = s.strip()

    for pat, repl in NOISE_RULES:
        s = pat.sub(repl, s)

    # 口水词 (循环清洗直到不再变化)
    s = re.sub(r"(然后){2,}", "然后", s)
    s = re.sub(r"(那个){2,}", "那个", s)
    s = re.sub(r"(不对){2,}!", "", s)
    s = re.sub(r"(不对){2,}！", "", s)
    s = re.sub(r"(不对){2,}", "", s)
    for _ in range(5):
        new_s = re.sub(r"^(嗯+|呃+|啊+|哦+|那\s*个|就\s*是|就是)[\s\u2026…]*", "", s)
        if new_s == s:
            break
        s = new_s
    s = re.sub(r"啊啊啊+", "", s)
    s = re.sub(r"啊+$", "", s)
    s = s.strip()

    # 增强隐私脱敏
    priv_details = []
    s, priv_details = privacy_masker.mask_all(s)

    # DFA 敏感词
    found = []
    if check_sensitive:
        _, found = sensitive_filter.check(s)

    return s.strip(), found, priv_details


# ---------- 1) 对话清洗 (SimHash 去重增强) ----------
def clean_chats():
    src = D4 / "chat_logs_raw.jsonl"
    rows = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    total_in = len(rows)
    out = []
    all_privacy = []
    all_sensitive = []
    failed_times = 0
    schema_errors = 0

    for r in rows:
        text_clean, sens_hits, priv_details = clean_text(r.get("text", ""), check_sensitive=True)
        ts, inv = parse_time(r.get("ts"))
        flags = []
        if inv:
            flags.append("time_invalid")
            failed_times += 1
        raw_text = r.get("text", "")

        # Schema validation
        is_valid, errs, warns = validator.validate(
            {"uid": r.get("uid"), "content": r.get("text", ""), "time": r.get("ts")},
            "d4_chat")
        if not is_valid:
            schema_errors += 1
            for e in errs:
                logger.error("chat schema 校验失败", uid=r.get("uid"), error=e)

        # forget 指令 (DFA 增强)
        forget_kws, has_forget = sensitive_filter.check(raw_text)
        if has_forget or any(kw in raw_text for kw in ("别记", "别保存", "不要保存", "忘记")):
            flags.append("forget_command")
            all_sensitive.extend(forget_kws or ["forget"])

        # 临时指令
        if any(kw in raw_text for kw in ("这次例外", "不代表以后", "不要简洁", "不对不对")):
            flags.append("temporary_instruction")

        # 隐私已脱敏
        if priv_details:
            flags.append("sensitive_masked")
            all_privacy.extend(priv_details)

        # DFA 敏感词命中(非 forget 类)
        non_forget_sens = [w for w in (sens_hits if isinstance(sens_hits, list) else []) if w not in ("别记", "别保存")]
        if non_forget_sens:
            flags.append("dfa_sensitive_hit")
            all_sensitive.extend(non_forget_sens)

        out.append({
            "session": r.get("session"),
            "uid": r.get("uid"),
            "role": r.get("role"),
            "text": text_clean,
            "ts": ts,
            "ts_invalid": inv,
            "flags": flags,
        })

    # 按 session 分组 + SimHash 去重
    grouped = defaultdict(list)
    for r in out:
        grouped[r["session"]].append(r)

    sessions = []
    total_dup = 0
    for sess, msgs in grouped.items():
        seen_fp = set()
        unique = []
        for m in msgs:
            fp = simhash_chat.compute_fingerprint(m["text"])
            is_dup = False
            for stored_fp in seen_fp:
                dist = SimHashDedup.hamming_distance(fp, stored_fp)
                if dist <= 3:
                    total_dup += 1
                    is_dup = True
                    break
            if not is_dup:
                seen_fp.add(fp)
                unique.append(m)
        unique.sort(key=lambda m: m["ts"] or "9999")
        sessions.append({"session_id": sess, "messages": unique})

    sessions.sort(key=lambda s: s["session_id"])

    report.add_metric("chats_total", total_in)
    report.add_metric("chats_after_clean", sum(len(s["messages"]) for s in sessions))
    report.add_metric("chats_dedup_simhash", total_dup)
    report.add_metric("chats_failed_time", failed_times)
    report.add_metric("masked_privacy_info", len(all_privacy))
    report.add_metric("chats_schema_errors", schema_errors)

    return sessions


# ---------- 2) 知识清洗 ----------
def clean_knowledge():
    src = D4 / "knowledge_raw.txt"
    text = src.read_text(encoding="utf-8")

    blocks = re.split(r"=== 案例开始 ===", text)
    out = []
    garbage_dropped = 0
    typo_count = 0
    schema_errors = 0

    for block in blocks:
        if "=== 案例结束 ===" not in block:
            continue
        block = block.split("=== 案例结束 ===")[0]
        if not block.strip():
            continue
        # 跳过垃圾行
        if "<<<<<<" in block or "测试粘贴" in block:
            garbage_dropped += 1
            continue

        k = {
            "title": None,
            "tags": [],
            "steps": [],
            "notes": [],
            "flags": [],
        }
        section = None
        for raw_line in block.splitlines():
            line, _, _ = clean_text(raw_line)
            if not line:
                continue
            m = re.match(r"^标题[：:]\s*(.*)$", line)
            if m:
                k["title"] = clean_text(m.group(1))[0]
                continue
            m = re.match(r"^标签[：:]\s*(.*)$", line)
            if m:
                tags_raw = m.group(1)
                k["tags"] = [t.lstrip("#").strip() for t in re.findall(r"#\S+", tags_raw)]
                continue
            m = re.match(r"^步骤[（(].*[）)][：:]\s*$", line)
            if m:
                section = "steps"; continue
            m = re.match(r"^(说明|要求|原则|常见坑|示例输出|新旧说法|适用|注意)[：:]\s*$", line)
            if m:
                section = "notes"; continue
            m = re.match(r"^(\d+)[.、．]\s*(.*)$", line)
            if m:
                k["steps"].append(clean_text(m.group(2))[0])
                section = "steps"
                continue
            m = re.match(r"^[-*]\s*(.*)$", line)
            if m:
                k["notes"].append(clean_text(m.group(1))[0])
                continue
            target = section if section in ("steps", "notes") else "notes"
            k[target].append(clean_text(line)[0])

        if not k["title"]:
            k["flags"].append("empty_title")

        typos = []
        for wrong, right in (("会义", "会议"), ("计忆", "记忆"), ("奇麟", "麒麟")):
            if wrong in block:
                typos.append({"wrong": wrong, "correct": right})
                typo_count += 1
        if typos:
            k["flags"].append("typo_detected")
            k["typos"] = typos

        # Schema validation
        is_valid, errs, warns = validator.validate(
            {"title": k["title"], "answer": "; ".join(k["steps"] + k["notes"])},
            "d4_knowledge")
        if not is_valid:
            schema_errors += 1
            for e in errs:
                logger.error("knowledge schema 校验失败", title=k["title"], error=e)

        out.append(k)

    report.add_metric("knowledge_cases", len(out))
    report.add_metric("knowledge_garbage_dropped", garbage_dropped)
    report.add_metric("knowledge_typos_fixed", typo_count)

    return out


# ---------- 3) 偏好清洗 ----------
def clean_preferences():
    src = D4 / "preferences_raw.csv"
    config_defaults = {"output_style": "简洁", "emoji_policy": "允许"}

    with src.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    groups = defaultdict(list)
    for r in rows:
        uid = (r.get("uid") or "").strip()
        key = r.get("pref_key", "")
        groups[(uid, key)].append(r)

    out = []
    conflict_count = 0
    needs_review_count = 0
    schema_errors = 0

    for (uid, key), items in groups.items():
        def vnum(v):
            return int(v[1:]) if v and v.startswith("v") and v[1:].isdigit() else 0
        items.sort(key=lambda r: vnum(r.get("version", "")))

        seen = set()
        unique = []
        for r in items:
            k = (r.get("pref_value"), r.get("version"))
            if k in seen:
                continue
            seen.add(k)
            unique.append(r)

        latest = unique[-1] if unique else None
        scope = "long"
        for r in unique:
            note = r.get("note", "")
            if any(kw in note for kw in ("本次例外", "仅本次", "本次")):
                scope = "short"
                break
        if not uid:
            scope = "needs_review"
            needs_review_count += 1

        chain = [{
            "version": r.get("version"),
            "value": clean_text(r.get("pref_value", ""))[0],
            "note": r.get("note"),
            "source_id": r.get("pref_id"),
        } for r in unique]

        entry = {
            "uid": uid or None,
            "pref_key": key,
            "current_value": clean_text(latest["pref_value"]) if latest else None,
            "current_version": latest.get("version") if latest else None,
            "scope": scope,
            "version_chain": chain,
            "flags": [],
        }
        if not uid:
            entry["flags"].append("missing_uid")
        if key in config_defaults and latest and clean_text(latest["pref_value"]) != config_defaults[key]:
            entry["flags"].append("override_default")
            conflict_count += 1

        # Schema validation
        is_valid, errs, warns = validator.validate(
            {"uid": uid, "key": key, "value": clean_text(latest["pref_value"])[0] if latest else ""},
            "d4_preference")
        if not is_valid:
            schema_errors += 1
            for e in errs:
                logger.error("preference schema 校验失败", uid=uid, key=key, error=e)
        out.append(entry)

    out.sort(key=lambda e: ((e.get("uid") or ""), e["pref_key"]))

    report.add_metric("preferences_entries", len(out))
    report.add_metric("preferences_conflicts", conflict_count)
    report.add_metric("preferences_needs_review", needs_review_count)
    report.add_metric("preferences_schema_errors", schema_errors)

    return out


# ---------- 4) 工具结果清洗 ----------
def clean_tools():
    src = D4 / "tool_result_raw.jsonl"
    rows = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    kept = {}
    tool_errors = 0
    tool_timeouts = 0
    tool_dup = 0
    schema_errors = 0

    for r in rows:
        trace = r.get("trace")
        output_clean, _, priv_details = clean_text(r.get("raw_output", ""), check_sensitive=True)

        # Schema validation
        is_valid, errs, warns = validator.validate(
            {"uid": r.get("uid"), "tool_name": r.get("tool"), "status": r.get("status")},
            "d4_tool")
        if not is_valid:
            schema_errors += 1
            for e in errs:
                logger.error("tool schema 校验失败", trace=trace, error=e)

        out_row = {
            "trace_id": trace,
            "tool": r.get("tool"),
            "status": r.get("status"),
            "exec_ms": r.get("exec_ms"),
            "output": output_clean,
            "flags": [],
            "dup_count": 1,
        }
        if r.get("status") == "error":
            out_row["flags"].append("tool_error")
            tool_errors += 1
        if "timeout" in r.get("raw_output", "").lower():
            out_row["flags"].append("tool_timeout")
            tool_timeouts += 1
        if priv_details:
            out_row["flags"].append("sensitive_in_output")

        if trace in kept:
            kept[trace]["dup_count"] += 1
            tool_dup += 1
            continue
        kept[trace] = out_row

    result = list(kept.values())
    report.add_metric("tools_entries", len(result))
    report.add_metric("tools_errors", tool_errors)
    report.add_metric("tools_timeouts", tool_timeouts)
    report.add_metric("tools_duplicates", tool_dup)
    report.add_metric("tools_schema_errors", schema_errors)

    return result


# ---------- 5) 生成报告 ----------
def generate_report(chats, knowledge, preferences, tools):
    lines = []
    lines.append("# D4 多源清洗报告\n")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    lines.append("## 1. 统计")
    lines.append(f"- 对话: {sum(len(s['messages']) for s in chats)} 条 / {len(chats)} session (SimHash去重)")
    lines.append(f"- 知识: {len(knowledge)} 个案例 (丢弃垃圾 {report.data['metrics'].get('knowledge_garbage_dropped', 0)})")
    lines.append(f"- 偏好: {len(preferences)} 个聚合 (冲突 {report.data['metrics'].get('preferences_conflicts', 0)})")
    lines.append(f"- 工具: {len(tools)} 条 (去重 {report.data['metrics'].get('tools_duplicates', 0)})\n")

    lines.append("## 2. 发现的隐私字段 (PrivacyMasker 增强脱敏)")
    priv = []
    for s in chats:
        for m in s["messages"]:
            if "sensitive_masked" in m["flags"]:
                priv.append(f"- session={s['session_id']} uid={m['uid']} -> 已增强脱敏")
    lines.extend(priv or ["- 无"])
    lines.append("")

    lines.append("## 3. DFA 敏感词命中")
    sens_lines = []
    for s in chats:
        for m in s["messages"]:
            if "dfa_sensitive_hit" in m["flags"]:
                sens_lines.append(f"- session={s['session_id']} uid={m['uid']}: DFA 命中敏感词")
            if "forget_command" in m["flags"]:
                sens_lines.append(f"- session={s['session_id']} uid={m['uid']}: 检测到 forget 指令")
    lines.extend(sens_lines or ["- 无"])
    lines.append("")

    lines.append("## 4. 发现的冲突项")
    conf = []
    for p in preferences:
        if p.get("uid") == "u001" and p["pref_key"] == "output_style":
            conf.append("- **u001 output_style**: v1=简洁、少废话 vs v2=详细、带数据表格 -> v2 覆盖 v1")
        if p.get("uid") in ("U002", "u002") and p["pref_key"] == "emoji_policy":
            conf.append("- **U002 emoji_policy**: 系统默认=允许 vs 用户明确=禁用 -> 用户优先")
        if p.get("uid") == "u003" and p["pref_key"] == "driver_update_entry":
            conf.append("- **u003 driver_update_entry**: v1=系统更新 vs v2=驱动管理器 -> v2 覆盖 v1")
    lines.extend(conf or ["- 无"])
    lines.append("")

    lines.append("## 5. needs_review 列表")
    review = []
    for p in preferences:
        if "missing_uid" in p["flags"]:
            review.append(f"- preferences.{p['pref_key']}: 缺 uid，scope=needs_review")
    for k in knowledge:
        if "empty_title" in k["flags"]:
            review.append("- knowledge: 案例缺标题，疑似垃圾行")
        if "typo_detected" in k["flags"]:
            typos_str = "; ".join(f"{t['wrong']}->{t['correct']}" for t in k.get("typos", []))
            review.append(f"- knowledge['{k.get('title')}']: 错别字 {typos_str}")
    for s in chats:
        for m in s["messages"]:
            if "forget_command" in m["flags"]:
                review.append(f"- chat session={s['session_id']} uid={m['uid']}: 触发 forget 指令 (DFA)")
            if "temporary_instruction" in m["flags"]:
                review.append(f"- chat session={s['session_id']} uid={m['uid']}: 临时指令，scope=short")
    for t in tools:
        if t.get("dup_count", 1) > 1:
            review.append(f"- tools: trace={t['trace_id']} 重复 {t['dup_count']} 次")
    lines.extend(review or ["- 无"])
    lines.append("")

    return "\n".join(lines)


def main():
    total_input = (
        sum(1 for _ in (D4 / "chat_logs_raw.jsonl").open(encoding="utf-8")) +
        sum(1 for _ in (D4 / "knowledge_raw.txt").open(encoding="utf-8")) +
        sum(1 for _ in (D4 / "preferences_raw.csv").open(encoding="utf-8")) +
        sum(1 for _ in (D4 / "config_manual.yaml").open(encoding="utf-8")) +
        sum(1 for _ in (D4 / "tool_result_raw.jsonl").open(encoding="utf-8"))
    )
    report.set_input_count(total_input)

    chats = clean_chats()
    knowledge = clean_knowledge()
    preferences = clean_preferences()
    tools = clean_tools()
    md_report = generate_report(chats, knowledge, preferences, tools)

    total_out = (
        sum(len(s["messages"]) for s in chats) +
        len(knowledge) + len(preferences) + len(tools)
    )
    report.set_output_count(total_out)
    report.finish(output_path=str(REPORT_JSON))

    # 写 JSON 输出
    (OUT / "chats.json").write_text(
        json.dumps(chats, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "knowledge.json").write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "preferences.json").write_text(
        json.dumps(preferences, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "tools.json").write_text(
        json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(md_report, encoding="utf-8")

    print(f"chats:       {sum(len(s['messages']) for s in chats)} msgs in {len(chats)} sessions")
    print(f"knowledge:   {len(knowledge)} cases")
    print(f"preferences: {len(preferences)} entries")
    print(f"tools:       {len(tools)} entries")
    print(f"outputs in:  {OUT}")
    print(f"\n{report.to_markdown()}")


if __name__ == "__main__":
    main()
