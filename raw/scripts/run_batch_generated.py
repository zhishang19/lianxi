#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量运行脚本 — 适配 generated/ 目录 (5 万条数据)
- 自动转换字段差异
- 依次运行 D2 → D3 → D4 → D5 → D6
- 输出每个目录的清洗报告和最终汇总报告
"""

import csv
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---------- 锚点定位 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
# 搜索 advanced_cleaning.py: lib/ -> raw/lib/ -> scripts/
for _sp in [SCRIPT_DIR.parent / "lib", SCRIPT_DIR.parent.parent / "raw" / "lib", SCRIPT_DIR]:
    if (_sp / "advanced_cleaning.py").exists():
        sys.path.insert(0, str(_sp))
        break
from advanced_cleaning import (
    TimePipeline, PrivacyMasker, SensitiveFilter,
    SimHashDedup, CleaningReport,
)

ROOT = SCRIPT_DIR.parent  # 项目根: d:\藏数据
GENERATED = ROOT / "raw" / "generated"
BASE_TIME = datetime(2026, 6, 7)

# 初始化高级组件
time_pipeline = TimePipeline(base_time=BASE_TIME)
privacy_masker = PrivacyMasker()
sensitive_filter = SensitiveFilter([
    "别记", "别保存", "不要保存", "忘记这个", "不保存",
    "手机号", "邮箱", "身份证", "密码",
])
simhash_dedup = SimHashDedup(threshold=3)


# ========== 通用工具 ==========

def load_jsonl(path, limit=None):
    """加载 JSONL 文件，返回 dict 列表"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pick(d, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def parse_time(raw):
    iso, inv, _ = time_pipeline.parse(raw)
    return iso, inv


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
    (re.compile(r" +"), " "),
]


def clean_text(s, check_sensitive=False):
    if not s:
        return "", []
    s = s.strip()
    for pat, repl in NOISE_RULES:
        s = pat.sub(repl, s)
    s = re.sub(r"(然后){2,}", "然后", s)
    s = re.sub(r"(那个){2,}", "那个", s)
    for _ in range(5):
        new_s = re.sub(r"^(嗯+|呃+|啊+|哦+|那\s*个|就\s*是|就是)[\s\u2026…]*", "", s)
        if new_s == s:
            break
        s = new_s
    s = re.sub(r"啊啊啊+", "", s)
    s = re.sub(r"啊+$", "", s)
    s = s.strip()
    s, _priv = privacy_masker.mask_all(s)
    found = []
    if check_sensitive:
        _, found = sensitive_filter.check(s)
    # _sens 始终是个列表（可能为空）
    return s, found if found else []


TYPO_FIXES = {
    "祥细": "详细", "奇麟": "麒麟", "会义": "会议",
    "计忆": "记忆", "设制": "设置", "其麟": "麒麟",
}


def fix_typo(s):
    if not s:
        return s
    for w, r in TYPO_FIXES.items():
        s = s.replace(w, r)
    return s


def normalize_uid(uid):
    return (uid or "").strip().lower()


def save_json(path, data):
    if isinstance(data, list):
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def save_report(report_obj, path):
    report_obj.finish(output_path=str(path))


# ========== D2: 合并去重 ==========

def run_d2(limit=None):
    print("\n" + "="*60)
    print("D2: 合并去噪 (generated/ 10000 条)")
    print("="*60)
    t0 = time.time()
    out_dir = GENERATED / "d02"

    # 1. 加载 user_behavior (JSONL, 每行一个 dict)
    ub_path = out_dir / "user_behavior.jsonl"
    ub_rows = load_jsonl(ub_path, limit)
    print(f"  加载 user_behavior: {len(ub_rows)} 条")

    # 2. 加载 tool_result (JSONL, 每行一个 dict)
    tr_path = out_dir / "tool_result.jsonl"
    tr_rows = load_jsonl(tr_path, limit)
    print(f"  加载 tool_result: {len(tr_rows)} 条")

    # 3. 归一化 user_behavior
    records = []
    for r in ub_rows:
        time_iso, time_invalid = parse_time(r.get("time"))
        cleaned, sens = clean_text(r.get("content", ""), check_sensitive=True)
        records.append({
            "source": "user_behavior",
            "uid": normalize_uid(r.get("uid")),
            "time": time_iso,
            "time_invalid": time_invalid,
            "type": r.get("action", "chat"),
            "content": cleaned,
            "_sens": sens,
        })

    # 4. 归一化 tool_result (字段适配: output/raw_output, latency_ms/exec_ms)
    for r in tr_rows:
        raw_time = r.get("time") or r.get("timestamp")
        if raw_time is None:
            time_iso, time_invalid = None, True
        else:
            time_iso, time_invalid = parse_time(raw_time)
        output_field = r.get("output") or r.get("raw_output", "")
        cleaned, sens = clean_text(output_field, check_sensitive=True)
        records.append({
            "source": "tool_result",
            "uid": normalize_uid(r.get("uid")),
            "time": time_iso,
            "time_invalid": time_invalid,
            "type": r.get("tool", "tool"),
            "content": cleaned,
            "tool_status": r.get("status"),
            "tool_latency_ms": r.get("latency_ms") or r.get("exec_ms"),
            "trace_id": r.get("trace_id") or r.get("trace"),
            "_sens": sens,
        })

    total_input = len(records)

    # 5. 去重
    seen = set()
    uniq = []
    for r in records:
        key = (r["uid"], r["time"], r["content"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    exact_dup = len(records) - len(uniq)

    # SimHash 去重
    simhash_dedup.reset()
    final = []
    simhash_dup = 0
    for r in uniq:
        content = r.get("content", "")
        if not content:
            final.append(r)
            continue
        is_dup, dist, _ = simhash_dedup.check(content)
        if is_dup:
            simhash_dup += 1
        else:
            simhash_dedup.add(content, r.get("trace_id", ""))
            final.append(r)

    # 统计
    all_sens = []
    for r in final:
        val = r.pop("_sens", None)
        if isinstance(val, list):
            all_sens.extend(val)
        elif val and isinstance(val, str):
            all_sens.append(val)

    failed_time = sum(1 for r in final if r.get("time_invalid") and r.get("time") is not None)

    # 排序
    final.sort(key=lambda r: (r.get("time_invalid", False), r.get("time") or "9999", r.get("uid") or ""))

    # 输出
    out_path = out_dir / "merged.jsonl"
    save_json(out_path, final)

    report = CleaningReport(stage="D2_batch", base_dir=out_dir)
    report.set_input_count(total_input)
    report.add_pipeline_step("字段归一化", total_input, total_input)
    report.add_pipeline_step("文本清洗", total_input, total_input)
    report.add_pipeline_step("去重", total_input, len(final), f"精确 {exact_dup} + SimHash {simhash_dup}")
    report.add_metric("dropped_exact", exact_dup)
    report.add_metric("dropped_simhash", simhash_dup)
    report.add_metric("failed_time_parsing", failed_time)
    report.add_metric("sensitive_hits", len(all_sens))
    report.add_sensitive_words_found(list(set(all_sens)))
    report.finish(valid_count=len(final), output_path=str(out_dir / "cleaning_report_d2.json"))

    elapsed = time.time() - t0
    print(f"  输出: {len(final)} 条 → {out_path}")
    print(f"  去重: 精确 {exact_dup} + SimHash {simhash_dup}")
    print(f"  时间失败: {failed_time} ({failed_time/max(len(final),1):.1%})")
    print(f"  耗时: {elapsed:.2f}s")
    return {"stage": "D2", "input": total_input, "output": len(final), "time": elapsed}


# ========== D3: 基础清洗 ==========

def run_d3(limit=None):
    print("\n" + "="*60)
    print("D3: 基础清洗 (generated/ 10000 条)")
    print("="*60)
    t0 = time.time()
    out_dir = GENERATED / "d03"

    src_path = out_dir / "chat_sessions_dirty.csv"
    rows = load_csv(src_path)
    if limit:
        rows = rows[:limit]
    print(f"  加载: {len(rows)} 行")

    # 精确去重
    seen = set()
    uniq = []
    for r in rows:
        key = (r.get("session_id"), r.get("user_id"), r.get("message"), r.get("created_at"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    exact_dup = len(rows) - len(uniq)

    # 清洗
    cleaned_rows = []
    priv_count = 0
    empty_count = 0
    missing_uid = 0

    for r in uniq:
        session_id = r.get("session_id", "")
        user_id = normalize_uid(r.get("user_id"))
        if not user_id:
            missing_uid += 1
        role = r.get("role", "")
        message = r.get("message", "")

        flags = []
        if not message.strip():
            flags.append("empty_message")
            empty_count += 1
            cleaned_rows.append({
                "session_id": session_id,
                "user_id": user_id,
                "role": role,
                "message": "",
                "created_at": r.get("created_at", ""),
                "flags": "|".join(flags) or "ok",
            })
            continue

        cleaned_msg, sens = clean_text(message, check_sensitive=True)
        if cleaned_msg != message:
            priv_count += 1

        if not user_id:
            flags.append("missing_user_id")

        time_iso, time_invalid = parse_time(r.get("created_at"))
        cleaned_rows.append({
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "message": cleaned_msg,
            "created_at": time_iso or r.get("created_at", ""),
            "flags": "|".join(flags) or "ok",
        })

    # 输出 CSV
    out_path = out_dir / "chat_sessions_clean.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["session_id", "user_id", "role", "message", "created_at", "flags"])
        writer.writeheader()
        writer.writerows(cleaned_rows)

    failed_time = sum(1 for r in cleaned_rows if r.get("created_at") == "Unknown_Time")

    report = CleaningReport(stage="D3_batch", base_dir=out_dir)
    report.set_input_count(len(rows))
    report.add_pipeline_step("精确去重", len(rows), len(uniq), f"去重 {exact_dup}")
    report.add_pipeline_step("清洗(去噪+脱敏+DFA)", len(uniq), len(cleaned_rows))
    report.add_metric("masked_privacy_info", priv_count)
    report.add_metric("empty_message", empty_count)
    report.add_metric("missing_user_id", missing_uid)
    report.add_metric("failed_time_parsing", failed_time)
    report.finish(valid_count=len(cleaned_rows), output_path=str(out_dir / "cleaning_report_d3.json"))

    elapsed = time.time() - t0
    print(f"  输出: {len(cleaned_rows)} 行 → {out_path}")
    print(f"  去重: {exact_dup}")
    print(f"  脱敏: {priv_count} 处")
    print(f"  耗时: {elapsed:.2f}s")
    return {"stage": "D3", "input": len(rows), "output": len(cleaned_rows), "time": elapsed}


# ========== D4: 多源清洗 ==========

def run_d4(limit=None):
    print("\n" + "="*60)
    print("D4: 多源清洗 (generated/ 10000 条)")
    print("="*60)
    t0 = time.time()
    out_dir = GENERATED / "d04"

    # 1. chat_logs_raw.jsonl
    chat_rows = load_jsonl(out_dir / "chat_logs_raw.jsonl", limit)
    print(f"  加载 chat_logs: {len(chat_rows)} 条")

    # 清洗对话
    chats_by_session = defaultdict(list)
    chat_dedup = 0
    priv_count = 0
    for r in chat_rows:
        cleaned, sens = clean_text(r.get("text", ""), check_sensitive=True)
        if cleaned != r.get("text", ""):
            priv_count += 1
        time_iso, _ = parse_time(r.get("ts"))
        session = r.get("session", "")
        key = (session, r.get("role"), cleaned, time_iso)
        if key not in [tuple(c.values()) for c in chats_by_session.get(session, [])]:
            chats_by_session[session].append({
                "session": session,
                "uid": normalize_uid(r.get("uid")),
                "role": r.get("role", ""),
                "text": fix_typo(cleaned),
                "ts": time_iso,
            })
        else:
            chat_dedup += 1

    all_chats = []
    for msgs in chats_by_session.values():
        all_chats.extend(msgs)
    (out_dir / "chats.json").write_text(
        json.dumps({"sessions": list(chats_by_session.values())}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # 2. knowledge_raw.jsonl (适配: JSONL 而非 TXT)
    know_rows = load_jsonl(out_dir / "knowledge_raw.jsonl", limit)
    print(f"  加载 knowledge: {len(know_rows)} 条")

    knowledge = []
    typos_fixed = 0
    for r in know_rows:
        body = r.get("body", "")
        fixed = fix_typo(body)
        if fixed != body:
            typos_fixed += 1
        knowledge.append({
            "item_id": r.get("item_id"),
            "title": r.get("title", ""),
            "tags": r.get("tags", ""),
            "body": fixed,
            "source_time": r.get("source_time", ""),
        })
    (out_dir / "knowledge.json").write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3. preferences_raw.csv
    pref_rows = load_csv(out_dir / "preferences_raw.csv")
    if limit:
        pref_rows = pref_rows[:limit]
    print(f"  加载 preferences: {len(pref_rows)} 条")

    prefs = []
    conflicts = 0
    for r in pref_rows:
        cleaned, _ = clean_text(r.get("pref_value", ""))
        uid = normalize_uid(r.get("uid"))
        key = r.get("pref_key", "")
        # 检测冲突: 同一 uid+key 但不同 value
        existing = [p for p in prefs if p["uid"] == uid and p["pref_key"] == key and p["pref_value"] != cleaned]
        if existing:
            conflicts += 1
        prefs.append({
            "pref_id": r.get("pref_id"),
            "uid": uid,
            "pref_key": key,
            "pref_value": cleaned,
            "version": r.get("version", ""),
            "note": r.get("note", ""),
        })
    (out_dir / "preferences.json").write_text(
        json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")

    # 4. tool_result_raw.jsonl (适配: raw_output→output, exec_ms→latency_ms)
    tool_rows = load_jsonl(out_dir / "tool_result_raw.jsonl", limit)
    print(f"  加载 tools: {len(tool_rows)} 条")

    tools = []
    tool_errors = 0
    tool_dup = 0
    seen_tools = set()
    for r in tool_rows:
        tid = r.get("trace") or r.get("trace_id", "")
        if tid in seen_tools:
            tool_dup += 1
            continue
        seen_tools.add(tid)
        status = r.get("status", "")
        if status in ("fail", "error"):
            tool_errors += 1
        output_field = r.get("raw_output") or r.get("output", "")
        cleaned, _ = clean_text(output_field)
        tools.append({
            "trace_id": tid,
            "tool": r.get("tool", ""),
            "status": status,
            "output": cleaned,
            "latency_ms": r.get("exec_ms") or r.get("latency_ms"),
        })
    (out_dir / "tools.json").write_text(
        json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")

    total_input = len(chat_rows) + len(know_rows) + len(pref_rows) + len(tool_rows)
    total_output = len(all_chats) + len(knowledge) + len(prefs) + len(tools)

    report = CleaningReport(stage="D4_batch", base_dir=out_dir)
    report.set_input_count(total_input)
    report.add_pipeline_step("chat_logs", len(chat_rows), len(all_chats), f"去重 {chat_dedup}")
    report.add_pipeline_step("knowledge_raw", len(know_rows), len(knowledge), f"错字修正 {typos_fixed}")
    report.add_pipeline_step("preferences_raw", len(pref_rows), len(prefs), f"冲突 {conflicts}")
    report.add_pipeline_step("tool_result_raw", len(tool_rows), len(tools), f"错误 {tool_errors}, 去重 {tool_dup}")
    report.add_metric("chats_after_clean", len(all_chats))
    report.add_metric("chats_dedup", chat_dedup)
    report.add_metric("knowledge_cases", len(knowledge))
    report.add_metric("knowledge_typos_fixed", typos_fixed)
    report.add_metric("preferences_entries", len(prefs))
    report.add_metric("preferences_conflicts", conflicts)
    report.add_metric("tools_entries", len(tools))
    report.add_metric("tools_errors", tool_errors)
    report.add_metric("tools_duplicates", tool_dup)
    report.finish(valid_count=total_output, output_path=str(out_dir / "cleaning_report_d4.json"))

    elapsed = time.time() - t0
    print(f"  输出: {total_output} 条 (chats={len(all_chats)}, know={len(knowledge)}, pref={len(prefs)}, tools={len(tools)})")
    print(f"  耗时: {elapsed:.2f}s")
    return {"stage": "D4", "input": total_input, "output": total_output, "time": elapsed}


# ========== D5: 记忆抽取 ==========

def run_d5(limit=None):
    print("\n" + "="*60)
    print("D5: 记忆抽取 (generated/ 9000+ 条)")
    print("="*60)
    t0 = time.time()
    out_dir = GENERATED / "d05"

    # 1. 加载事件
    events = load_jsonl(out_dir / "memory_events_raw.jsonl", limit)
    print(f"  加载 events: {len(events)} 条")

    # 精确去重
    seen = set()
    uniq_events = []
    for r in events:
        eid = r.get("event_id", "")
        if eid in seen:
            continue
        seen.add(eid)
        uniq_events.append(r)
    dup_exact = len(events) - len(uniq_events)

    # 清洗+归一化
    parsed_events = []
    for r in uniq_events:
        time_iso, time_invalid = parse_time(r.get("time"))
        cleaned, sens = clean_text(r.get("content", ""), check_sensitive=True)
        parsed_events.append({
            "event_id": r.get("event_id"),
            "uid": normalize_uid(r.get("uid")),
            "source": r.get("source"),
            "event_type": r.get("event_type"),
            "content": fix_typo(cleaned),
            "time": time_iso,
            "time_invalid": time_invalid,
            "confidence": 0.95 if str(r.get("confidence", "")).lower() == "high" else (
                0.3 if str(r.get("confidence", "")).lower() == "low" else
                float(r.get("confidence", 0.5)) if r.get("confidence") else 0.5
            ),
            "ttl": r.get("ttl"),
        })

    # 2. 加载快照
    snapshots = load_csv(out_dir / "user_memory_snapshots_raw.csv")
    if limit:
        snapshots = snapshots[:limit]
    print(f"  加载 snapshots: {len(snapshots)} 条")

    parsed_snaps = []
    for r in snapshots:
        time_iso, time_invalid = parse_time(r.get("last_seen"))
        value, _ = privacy_masker.mask_all(r.get("memory_value", ""))
        parsed_snaps.append({
            "uid": normalize_uid(r.get("uid")),
            "memory_key": r.get("memory_key", ""),
            "value": value,
            "scope": r.get("scope", ""),
            "version": r.get("version", ""),
            "last_seen": time_iso,
            "last_seen_invalid": time_invalid,
            "note": r.get("note", ""),
        })

    # 3. 简单记忆处理 (按 uid+key 分组, 最新覆盖旧)
    from collections import defaultdict as _dd
    groups = _dd(list)
    for e in parsed_events:
        content = e["content"].lower()
        raw = e["content"]
        if "@" in raw or "邮箱" in raw or "email" in content:
            key = "email"
        elif re.search(r"1[3-9]\d{9}", raw):
            key = "phone"
        elif "输出" in raw and ("详细" in raw or "简洁" in raw):
            key = "output_style"
        elif "emoji" in content or "表情" in raw:
            key = "emoji_policy"
        elif "驱动" in raw:
            key = "driver_update_entry"
        elif "会议纪要" in raw or "bullet" in content:
            key = "meeting_minutes_format"
        elif "密码" in raw:
            key = "password_reset_flow"
        elif "回答" in raw or "结论" in raw:
            key = "answer_style"
        elif "离线" in raw or "dpkg" in content or "deb" in content:
            key = "deb_install"
        else:
            key = "unknown"
        groups[(e["uid"], key)].append(e)

    out_memories = []
    conflicts_count = 0
    review_count = 0

    for (uid, key), evts in groups.items():
        if evts[0]["event_type"] == "forget":
            out_memories.append({
                "uid": uid, "memory_key": key, "action": "remove",
                "value": evts[0]["content"], "scope": "none",
                "reason": f"forget 指令 (event={evts[0]['event_id']})",
                "evidence": [evts[0]["event_id"]], "time": evts[0]["time"],
            })
        elif evts[0]["event_type"] == "temporary_instruction":
            out_memories.append({
                "uid": uid, "memory_key": key, "action": "keep",
                "value": evts[0]["content"], "scope": "short",
                "reason": f"临时指令, scope=short (event={evts[0]['event_id']})",
                "evidence": [evts[0]["event_id"]], "time": evts[0]["time"],
            })
        else:
            valid = [e for e in evts if not e["time_invalid"]]
            invalid = [e for e in evts if e["time_invalid"]]
            if valid:
                valid.sort(key=lambda e: (e["time"] or "", e["confidence"]), reverse=True)
                latest = valid[0]
                older = valid[1:]
                out_memories.append({
                    "uid": uid, "memory_key": key,
                    "action": "override" if older else "keep",
                    "value": latest["content"], "scope": "long",
                    "reason": f"最新记忆 (event={latest['event_id']}, time={latest['time']})",
                    "evidence": [latest["event_id"]],
                    "history": [{"event_id": o["event_id"], "value": o["content"], "time": o["time"]} for o in older[:3]],
                    "time": latest["time"],
                })
                if older:
                    conflicts_count += 1
            for e in invalid:
                out_memories.append({
                    "uid": uid, "memory_key": key, "action": "review",
                    "value": e["content"], "scope": "needs_review",
                    "reason": f"时间缺失 (event={e['event_id']})",
                    "evidence": [e["event_id"]], "time": None,
                })
                review_count += 1

    out_path = out_dir / "merged_memories.jsonl"
    save_json(out_path, out_memories)

    # 写冲突报告
    report_lines = [f"# D5 批量清洗报告\n", f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    report_lines.append(f"## 统计\n- 事件总数: {len(uniq_events)} (精确去重 {dup_exact})")
    report_lines.append(f"- 快照总数: {len(parsed_snaps)}")
    report_lines.append(f"- 最终记忆: {len(out_memories)}")
    report_lines.append(f"- 冲突: {conflicts_count}")
    report_lines.append(f"- needs_review: {review_count}\n")
    (out_dir / "conflict_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    report = CleaningReport(stage="D5_batch", base_dir=out_dir)
    report.set_input_count(len(events))
    report.add_pipeline_step("加载+去重", len(events), len(uniq_events), f"精确去重 {dup_exact}")
    report.add_pipeline_step("记忆抽取", len(uniq_events), len(out_memories), f"冲突 {conflicts_count}, review {review_count}")
    report.add_metric("dedup_exact", dup_exact)
    report.add_metric("conflicts", conflicts_count)
    report.add_metric("needs_review", review_count)
    report.add_metric("action_keep", sum(1 for m in out_memories if m["action"] == "keep"))
    report.add_metric("action_override", sum(1 for m in out_memories if m["action"] == "override"))
    report.add_metric("action_remove", sum(1 for m in out_memories if m["action"] == "remove"))
    report.add_metric("action_review", sum(1 for m in out_memories if m["action"] == "review"))
    report.finish(valid_count=len(out_memories), output_path=str(out_dir / "cleaning_report_d5.json"))

    elapsed = time.time() - t0
    print(f"  输出: {len(out_memories)} 条记忆 → {out_path}")
    print(f"  冲突: {conflicts_count}, review: {review_count}")
    print(f"  耗时: {elapsed:.2f}s")
    return {"stage": "D5", "input": len(events), "output": len(out_memories), "time": elapsed}


# ========== D6: 端到端评测 ==========

def run_d6(limit=None):
    print("\n" + "="*60)
    print("D6: 端到端评测 (generated/ 5000 题)")
    print("="*60)
    t0 = time.time()
    out_dir = GENERATED / "d06"

    # 加载记忆 (从 D5 输出)
    d5_out = GENERATED / "d05" / "merged_memories.jsonl"
    memories = load_jsonl(d5_out) if d5_out.exists() else []
    print(f"  加载记忆: {len(memories)} 条")

    # 加载评测题目
    prompts = load_csv(out_dir / "eval_prompts_dirty.csv")
    if limit:
        prompts = prompts[:limit]
    print(f"  加载题目: {len(prompts)} 条")

    # 加载 trace
    traces_list = load_jsonl(out_dir / "tool_eval_trace_raw.jsonl", limit)
    trace_by_id = {t["case_id"]: t for t in traces_list}
    print(f"  加载 trace: {len(traces_list)} 条")

    # 逐题评估
    results = []
    hit_count = 0
    miss_count = 0
    leak_count = 0
    pv_count = 0
    uc_count = 0

    for prompt in prompts:
        case_id = prompt.get("case_id", "")
        uid = normalize_uid(prompt.get("uid"))
        query = prompt.get("query", "")
        expected = prompt.get("expected_memory_hint", "")

        # 检索
        retrieved = [m for m in memories if m.get("uid") == uid and m.get("action") in ("keep", "override", "remove")]

        # 找 trace 答案
        trace = trace_by_id.get(case_id, {"answer": "未找到相关记忆。", "judge_note": "基于记忆"})

        # 简单评分
        answer = trace.get("answer", "")
        judge = trace.get("judge_note", "")

        label = "hit"
        score = 100
        if "严重" in judge or "泄露" in judge:
            label, score = "leak", 0
        elif "违反" in judge:
            label, score = "preference_violation", 30
        elif "冲突" in judge:
            label, score = "unresolved_conflict", 40
        elif "无效" in judge or "错误" in judge:
            label, score = "miss", 50

        if label == "hit":
            hit_count += 1
        elif label == "miss":
            miss_count += 1
        elif label == "leak":
            leak_count += 1
        elif label == "preference_violation":
            pv_count += 1
        elif label == "unresolved_conflict":
            uc_count += 1

        results.append({
            "case_id": case_id, "uid": uid, "query": query,
            "expected": expected, "answer": answer,
            "retrieved_count": len(retrieved),
            "label": label, "score": score, "reason": judge,
        })

    total = len(results)
    avg_score = sum(r["score"] for r in results) / total if total else 0

    # 输出
    out_path = out_dir / "eval_results.jsonl"
    save_json(out_path, results)

    # 生成报告
    report_lines = [
        f"# D6 批量评测报告\n",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"## 总体结论\n- 命中数: {hit_count}/{total} = {hit_count/total:.1%}" if total else "- 无",
        f"- 平均分: {avg_score:.1f} / 100\n",
        f"## 分类统计\n| 标签 | 个数 |\n|------|------|",
        f"| hit | {hit_count} |", f"| miss | {miss_count} |",
        f"| leak | {leak_count} |", f"| preference_violation | {pv_count} |",
        f"| unresolved_conflict | {uc_count} |\n",
    ]
    (out_dir / "eval_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    report = CleaningReport(stage="D6_batch", base_dir=out_dir)
    report.set_input_count(total)
    report.add_pipeline_step("加载数据", total, total)
    report.add_pipeline_step("检索+评估", total, total, f"命中 {hit_count}/{total}")
    report.add_metric("hit_count", hit_count)
    report.add_metric("miss_count", miss_count)
    report.add_metric("leak_count", leak_count)
    report.add_metric("avg_score", round(avg_score, 1))
    report.finish(valid_count=len(results), output_path=str(out_dir / "cleaning_report_d6.json"))

    elapsed = time.time() - t0
    print(f"  输出: {total} 题 → {out_path}")
    print(f"  命中: {hit_count}/{total} = {hit_count/total:.1%}")
    print(f"  平均分: {avg_score:.1f}")
    print(f"  耗时: {elapsed:.2f}s")
    return {"stage": "D6", "input": total, "output": total, "time": elapsed}


# ========== 主流程 ==========

def main():
    import argparse
    parser = argparse.ArgumentParser(description="批量运行 D2-D6 清洗流水线 (generated/ 5 万条)")
    parser.add_argument("--limit", type=int, default=None, help="限制每个阶段处理的条数 (调试用)")
    parser.add_argument("--stages", type=str, default="all", help="指定运行阶段, 如 D2,D3,D4 (默认 all)")
    args = parser.parse_args()

    limit = args.limit
    stages = args.stages.lower().split(",") if args.stages != "all" else ["d2", "d3", "d4", "d5", "d6"]

    print("="*60)
    print("批量运行 D2-D6 清洗流水线 (generated/ 5 万条)")
    print("="*60)
    print(f"基准时间: {BASE_TIME}")
    print(f"阶段: {stages}")
    if limit:
        print(f"限制: 每个阶段最多 {limit} 条")
    else:
        print("限制: 无 (全量运行)")

    overall_start = time.time()
    results = []

    if "d2" in stages:
        results.append(run_d2(limit))
    if "d3" in stages:
        results.append(run_d3(limit))
    if "d4" in stages:
        results.append(run_d4(limit))
    if "d5" in stages:
        results.append(run_d5(limit))
    if "d6" in stages:
        results.append(run_d6(limit))

    overall_time = time.time() - overall_start

    # 总汇总
    print("\n" + "="*60)
    print("总汇总")
    print("="*60)
    print(f"| 阶段 | 输入 | 输出 | 耗时 |")
    print(f"|------|------|------|------|")
    total_input = 0
    total_output = 0
    for r in results:
        print(f"| {r['stage']} | {r['input']:,} | {r['output']:,} | {r['time']:.2f}s |")
        total_input += r["input"]
        total_output += r["output"]
    print(f"| 合计 | {total_input:,} | {total_output:,} | {overall_time:.2f}s |")

    # 总汇总报告
    summary_path = GENERATED / "batch_summary.json"
    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seed": "20260607",
        "total_input": total_input,
        "total_output": total_output,
        "total_time": round(overall_time, 2),
        "stages": results,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n总汇总报告: {summary_path}")
    print("\n全部完成!")


if __name__ == "__main__":
    main()
