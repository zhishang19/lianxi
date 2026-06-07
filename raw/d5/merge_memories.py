#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D5 记忆抽取、冲突与流转脚本 (升级版)
- 读取 raw/d5/ 下 3 份源数据
- 抽 4 类记忆（preference / knowledge / temporary / forget）
- 应用冲突规则（覆盖 / 保留 / 移除 / 复查）
- 输出 merged_memories.jsonl + conflict_report.md + cleaning_report_d5.json

升级内容:
  - TimePipeline 4层时间解析流水线
  - PrivacyMasker 增强脱敏 (手机前3后4 / 邮箱首尾)
  - SensitiveFilter DFA 敏感词检测 (Aho-Corasick)
  - SimHashDedup 近似去重 (海明距离)
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
    from advanced_cleaning import (
        TimePipeline,
        PrivacyMasker,
        SensitiveFilter,
        SimHashDedup,
        CleaningReport,
        SchemaValidator,
        CleanLogger,
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
                TimePipeline,
                PrivacyMasker,
                SensitiveFilter,
                SimHashDedup,
                CleaningReport,
                SchemaValidator,
                CleanLogger,
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
D5 = ROOT / "raw" / "d5"
OUT = D5

# 初始化 5 大能力
time_pipeline = TimePipeline()
privacy_masker = PrivacyMasker()
sensitive_filter = SensitiveFilter([
    "别记", "别保存", "不要保存", "忘记这个", "不保存",
    "手机号", "邮箱", "身份证",
])
simhash_dedup = SimHashDedup(threshold=3)
report_engine = CleaningReport(stage="D5_memory_extract")

# 校验器与日志
validator = SchemaValidator()
logger = CleanLogger(log_file=str(D5 / "clean.log"))

# ---------- 时间规整 (用 TimePipeline 替代硬编码) ----------
def parse_time(s):
    """使用 TimePipeline 4层流水线解析时间"""
    iso, invalid, method = time_pipeline.parse(s)
    return iso, invalid


def parse_confidence(v):
    if v is None:
        return 0.5
    s = str(v).strip().lower()
    if s == "high":
        return 0.95
    if s == "low":
        return 0.3
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.5


# ---------- 同义 / 错别字归一 ----------
TYPO_FIXES = {
    "祥细": "详细",
    "奇麟": "麒麟",
    "会义": "会议",
    "计忆": "记忆",
    "设制": "设置",
}


def fix_typo(s):
    if not s:
        return s
    for w, r in TYPO_FIXES.items():
        s = s.replace(w, r)
    return s


def normalize_uid(uid):
    return (uid or "").strip().lower()


# ---------- 文本清洗 (去噪+脱敏+DFA) ----------
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
    """增强文本清洗: 去噪 → 口水词 → 隐私脱敏 → DFA敏感词"""
    if not s:
        return "", []

    s = s.strip()

    # 去噪
    for pat, repl in NOISE_RULES:
        s = pat.sub(repl, s)

    # 口水词 (循环清洗直到不再变化)
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

    # 隐私脱敏
    s, priv_details = privacy_masker.mask_all(s)

    # DFA 敏感词检测
    found = []
    if check_sensitive:
        _, found = sensitive_filter.check(s)

    return s, found


# ---------- memory_key 推断 ----------
def infer_memory_key(content, event_type):
    c = (content or "").lower()
    raw = content or ""
    # forget 单独处理
    if event_type == "forget":
        if "@" in raw or "email" in c or "邮箱" in raw:
            return "email"
        if re.search(r"1[3-9]\d{9}", raw):
            return "phone"
        return "private_data"

    if "输出" in raw and ("详细" in raw or "简洁" in raw or "格式" in raw or "风格" in raw):
        return "output_style"
    if "emoji" in c or "表情" in raw:
        return "emoji_policy"
    if "驱动" in raw and ("更新" in raw or "入口" in raw or "管理器" in raw):
        return "driver_update_entry"
    if "会议纪要" in raw or "meeting" in c or "bullet" in c:
        return "meeting_minutes_format"
    if "密码" in raw and ("重置" in raw or "流程" in raw or "账户" in raw):
        return "password_reset_flow"
    if ("回答" in raw or "结论" in raw or "步骤" in raw) and ("长" in raw or "解释" in raw):
        return "answer_style"
    if "离线安装" in raw or "dpkg" in c or "deb" in c:
        return "deb_install"
    if "默认" in raw and "emoji" in c:
        return "emoji_policy"

    return "unknown"


# ---------- 1) 加载事件 ----------
def load_events():
    src = D5 / "memory_events_raw.jsonl"
    rows = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # 精确去重 (event_id)
    seen = set()
    uniq = []
    for r in rows:
        eid = r.get("event_id")
        if eid in seen:
            continue
        seen.add(eid)
        uniq.append(r)
    dup_exact = len(rows) - len(uniq)

    # SimHash 近似去重
    content_for_simhash = []
    for r in uniq:
        c = fix_typo(r.get("content", ""))
        content_for_simhash.append(c)

    simhash_dedup.reset()
    uniq_after_simhash = []
    dup_simhash = 0
    for r, c in zip(uniq, content_for_simhash):
        is_dup, dist, matched = simhash_dedup.check(c)
        if is_dup:
            dup_simhash += 1
        else:
            simhash_dedup.add(c, r.get("event_id"))
            uniq_after_simhash.append(r)

    total_dup = dup_exact + dup_simhash

    parsed = []
    for r in uniq_after_simhash:
        ts, inv = parse_time(r.get("time"))
        cleaned_content, sens_hits = clean_text(r.get("content", ""), check_sensitive=True)
        parsed.append({
            "event_id": r.get("event_id"),
            "uid": normalize_uid(r.get("uid")),
            "raw_uid": r.get("uid"),
            "source": r.get("source"),
            "event_type": r.get("event_type"),
            "content": fix_typo(cleaned_content),
            "content_raw": r.get("content", ""),
            "time": ts,
            "time_invalid": inv,
            "time_method": inv and "failed" or "parsed",
            "confidence": parse_confidence(r.get("confidence")),
            "ttl": r.get("ttl"),
            "_sensitive_hits": sens_hits,
        })
    return parsed, dup_exact, dup_simhash


def load_snapshots():
    src = D5 / "user_memory_snapshots_raw.csv"
    rows = []
    with src.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            ts, inv = parse_time(r.get("last_seen"))
            value = r.get("memory_value", "")
            masked_value, priv_details = privacy_masker.mask_all(value)
            rows.append({
                "uid": normalize_uid(r.get("uid")),
                "raw_uid": r.get("uid"),
                "memory_key": r.get("memory_key"),
                "value": masked_value,
                "scope": r.get("scope"),
                "version": r.get("version"),
                "last_seen": ts,
                "last_seen_invalid": inv,
                "note": r.get("note", ""),
                "_privacy_masked": len(priv_details) > 0,
            })
    return rows


# ---------- 2) 冲突处理核心 ----------
def process(events, snapshots):
    # 按 (uid, memory_key) 分组
    groups = defaultdict(lambda: {"forget": [], "temp": [], "preference": [], "knowledge": []})
    for e in events:
        key = infer_memory_key(e["content"], e["event_type"])
        uid = e["uid"]
        bucket = {
            "forget": "forget",
            "temporary_instruction": "temp",
            "preference": "preference",
            "knowledge": "knowledge",
            "knowledge_update": "knowledge",
        }.get(e["event_type"], "knowledge")
        groups[(uid, key)][bucket].append(e)

    out = []
    conflicts = []
    review = []

    for (uid, key), bucket in groups.items():
        # 1) forget 优先处理
        for f in bucket["forget"]:
            out.append({
                "uid": uid,
                "memory_key": key,
                "action": "remove",
                "value": f["content"],
                "scope": "none",
                "reason": f"forget 指令 (event={f['event_id']}, source={f['source']})",
                "evidence": [f["event_id"]],
                "time": f["time"],
            })

        # 2) 偏好
        prefs = bucket["preference"]
        if prefs:
            valid = [p for p in prefs if not p["time_invalid"]]
            invalid = [p for p in prefs if p["time_invalid"]]
            if valid:
                valid.sort(key=lambda p: (p["time"] or "", p["confidence"]), reverse=True)
                latest = valid[0]
                older = valid[1:]
                history = [{
                    "event_id": p["event_id"],
                    "value": p["content"],
                    "time": p["time"],
                    "confidence": p["confidence"],
                    "source": p["source"],
                } for p in older]
                default_conflict = (key in ("emoji_policy",) and latest["source"] == "config")
                out.append({
                    "uid": uid,
                    "memory_key": key,
                    "action": "override" if older else "keep",
                    "value": latest["content"],
                    "scope": "long",
                    "reason": f"最新明确偏好 (event={latest['event_id']}, time={latest['time']}, conf={latest['confidence']})"
                              + ("，用户明确覆盖默认" if default_conflict else ""),
                    "evidence": [latest["event_id"]],
                    "history": history,
                    "time": latest["time"],
                })
                if older:
                    conflicts.append({
                        "uid": uid,
                        "memory_key": key,
                        "type": "preference_override",
                        "old_value": older[0]["content"],
                        "old_event": older[0]["event_id"],
                        "old_time": older[0]["time"],
                        "new_value": latest["content"],
                        "new_event": latest["event_id"],
                        "new_time": latest["time"],
                        "decision": "最新明确偏好覆盖旧偏好，旧版本进入 history",
                    })
            for p in invalid:
                out.append({
                    "uid": uid,
                    "memory_key": key,
                    "action": "review",
                    "value": p["content"],
                    "scope": "needs_review",
                    "reason": f"时间缺失，无法判断新旧 (event={p['event_id']})",
                    "evidence": [p["event_id"]],
                    "time": None,
                })
                review.append({"uid": uid, "memory_key": key, "reason": "时间缺失", "event": p["event_id"]})

        # 3) 知识
        knows = bucket["knowledge"]
        if knows:
            valid = [k for k in knows if not k["time_invalid"]]
            invalid = [k for k in knows if k["time_invalid"]]
            if valid:
                valid.sort(key=lambda k: (k["time"] or "", k["confidence"]), reverse=True)
                latest = valid[0]
                older = valid[1:]
                history = [{
                    "event_id": k["event_id"],
                    "value": k["content"],
                    "time": k["time"],
                    "confidence": k["confidence"],
                    "source": k["source"],
                } for k in older]
                out.append({
                    "uid": uid,
                    "memory_key": key,
                    "action": "override" if older else "keep",
                    "value": latest["content"],
                    "scope": "long",
                    "reason": f"最新知识 (event={latest['event_id']}, time={latest['time']}, conf={latest['confidence']})",
                    "evidence": [latest["event_id"]],
                    "history": history,
                    "time": latest["time"],
                })
                if older:
                    conflicts.append({
                        "uid": uid,
                        "memory_key": key,
                        "type": "knowledge_override",
                        "old_value": older[0]["content"],
                        "old_event": older[0]["event_id"],
                        "old_time": older[0]["time"],
                        "new_value": latest["content"],
                        "new_event": latest["event_id"],
                        "new_time": latest["time"],
                        "decision": "新知识覆盖旧知识，保留覆盖证据",
                    })
            for k in invalid:
                out.append({
                    "uid": uid,
                    "memory_key": key,
                    "action": "review",
                    "value": k["content"],
                    "scope": "needs_review",
                    "reason": f"时间缺失或无法解析 (event={k['event_id']})",
                    "evidence": [k["event_id"]],
                    "time": None,
                })

        # 4) 临时指令：scope=short，不覆盖长期
        for t in bucket["temp"]:
            out.append({
                "uid": uid,
                "memory_key": key,
                "action": "keep",
                "value": t["content"],
                "scope": "short",
                "reason": f"临时指令，scope=short，不覆盖长期偏好 (event={t['event_id']})",
                "evidence": [t["event_id"]],
                "time": t["time"],
            })

    return out, conflicts, review


# ---------- 3) 报告 ----------
def generate_report(conflicts, review, events, snapshots, dup_exact, dup_simhash, sensitive_hits_all):
    lines = []
    lines.append("# D5 冲突与流转报告\n")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 1. 统计
    lines.append("## 1. 统计")
    lines.append(f"- 事件总数: {len(events)} (精确去重 {dup_exact} 条, SimHash 去重 {dup_simhash} 条)")
    lines.append(f"- 快照总数: {len(snapshots)}")
    lines.append(f"- 冲突项: {len(conflicts)}")
    lines.append(f"- needs_review: {len(review)}\n")

    # 2. 冲突列表
    lines.append("## 2. 冲突项（谁覆盖谁）")
    if conflicts:
        for i, c in enumerate(conflicts, 1):
            lines.append(f"### {i}. [{c['uid']}] {c['memory_key']} - {c['type']}")
            lines.append(f"- 旧值: `{c.get('old_value')}` (event={c.get('old_event')}, time={c.get('old_time')})")
            lines.append(f"- 新值: `{c.get('new_value')}` (event={c.get('new_event')}, time={c.get('new_time')})")
            lines.append(f"- 决策: {c['decision']}\n")
    else:
        lines.append("- 无\n")

    # 3. needs_review
    lines.append("## 3. needs_review 列表")
    if review:
        for r in review:
            lines.append(f"- [{r['uid']}] {r['memory_key']}: {r['reason']} (event={r['event']})")
    else:
        lines.append("- 无")
    lines.append("")

    # 4. 临时指令 vs 长期
    lines.append("## 4. 临时指令未覆盖长期（验证）")
    lines.append("- 已自动保证：所有 temporary_instruction 输出 scope=short，不进入 long-term 检索。\n")

    # 5. forget 移除清单
    lines.append("## 5. forget 移除清单（不应进入长期记忆）")
    forget_count = sum(1 for e in events if any(kw in e.get("content_raw", "") for kw in ("别记", "别保存", "不要保存")))
    lines.append(f"- 共处理 {forget_count} 条 forget 事件，相关 memory_value 已从可检索记忆中移除。\n")

    # 6. 同义 / 错别字
    lines.append("## 6. 同义 / 错别字归一")
    for w, r in TYPO_FIXES.items():
        lines.append(f"- {w} → {r}")
    lines.append("")

    # 7. 快照验证
    lines.append("## 7. 与快照的差异")
    lines.append("| uid | memory_key | snapshot_value | event_value | 状态 |")
    lines.append("|-----|-----------|---------------|-------------|------|")
    seen_rows = set()
    for s in snapshots:
        row_key = (s["uid"], s["memory_key"], s["value"])
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        matching = [e for e in events if e["uid"] == s["uid"] and infer_memory_key(e["content"], e["event_type"]) == s["memory_key"]]
        if not matching:
            status = "snapshot 单独存在"
            ev_str = "—"
        else:
            valid = [m for m in matching if m["time"]]
            latest_ev = sorted(valid, key=lambda m: m["time"], reverse=True)[0] if valid else matching[0]
            ev_str = f"`{latest_ev['content']}`"
            if latest_ev["content"] == s["value"]:
                status = "一致"
            else:
                status = "差异（以最新事件为准）"
        lines.append(f"| {s['uid']} | {s['memory_key']} | `{s['value']}` | {ev_str} | {status} |")

    # 8. DFA 敏感词命中
    if sensitive_hits_all:
        lines.append("\n## 8. DFA 敏感词命中")
        all_words = []
        for h in sensitive_hits_all:
            all_words.extend(h)
        unique_words = list(set(all_words))
        lines.append(f"- 检测到 {len(all_words)} 次敏感词命中: {', '.join(unique_words)}\n")

    return "\n".join(lines)


def main():
    logger.info("D5 记忆抽取脚本启动")
    events, dup_exact, dup_simhash = load_events()
    snapshots = load_snapshots()
    event_count = len(events) + dup_exact + dup_simhash
    snapshot_count = len(snapshots)
    logger.info("输入源文件", events=event_count, snapshots=snapshot_count)
    out, conflicts, review = process(events, snapshots)
    logger.info("完成记忆合并", memories=len(out), conflicts=len(conflicts))

    # SchemaValidator 字段校验
    validation_errors = []
    for o in out:
        is_valid, errors, warnings = validator.validate(o, "d5_memory")
        if not is_valid:
            validation_errors.append({"memory_key": o.get("memory_key"), "errors": errors})
    if validation_errors:
        logger.error("记忆字段校验失败", count=len(validation_errors), details=validation_errors[:3])

    # 收集所有敏感词命中
    sensitive_hits_all = [e.get("_sensitive_hits", []) for e in events if e.get("_sensitive_hits")]

    report_md = generate_report(conflicts, review, events, snapshots, dup_exact, dup_simhash, sensitive_hits_all)

    # 写 merged_memories.jsonl
    out_path = OUT / "merged_memories.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    # 写 conflict_report.md
    (OUT / "conflict_report.md").write_text(report_md, encoding="utf-8")

    # ---- CleaningReport ----
    action_counts = defaultdict(int)
    for o in out:
        action_counts[o["action"]] += 1

    report_engine.set_input_count(len(events) + dup_exact + dup_simhash)
    report_engine.set_output_count(len(out))
    report_engine.add_metric("dedup_exact", dup_exact)
    report_engine.add_metric("dedup_simhash", dup_simhash)
    report_engine.add_metric("dropped_duplicates", dup_exact + dup_simhash)
    report_engine.add_metric("conflicts", len(conflicts))
    report_engine.add_metric("needs_review", len(review))
    report_engine.add_metric("forget_events", sum(1 for e in events if e.get("event_type") == "forget"))
    report_engine.add_metric("action_keep", action_counts.get("keep", 0))
    report_engine.add_metric("action_override", action_counts.get("override", 0))
    report_engine.add_metric("action_remove", action_counts.get("remove", 0))
    report_engine.add_metric("action_review", action_counts.get("review", 0))
    failed_time = sum(1 for e in events if e.get("time_invalid"))
    report_engine.add_metric("failed_time_parsing", failed_time)
    sens_words = []
    for h in sensitive_hits_all:
        sens_words.extend(h)
    report_engine.add_metric("sensitive_hits", len(sens_words))
    report_engine.add_sensitive_words_found(list(set(sens_words)))
    report_engine.add_pipeline_step("加载事件", len(events) + dup_exact + dup_simhash, len(events) + dup_simhash, f"精确去重 {dup_exact}")
    report_engine.add_pipeline_step("SimHash 去重", len(events) + dup_simhash, len(events), f"海明距离去重 {dup_simhash}")
    report_engine.add_pipeline_step("记忆抽取+冲突处理", len(events), len(out), f"冲突 {len(conflicts)}, review {len(review)}")
    report_engine.finish(output_path=str(OUT / "cleaning_report_d5.json"))

    print(f"events:      {len(events) + dup_exact + dup_simhash} total (dedup_exact={dup_exact}, dedup_simhash={dup_simhash})")
    print(f"snapshots:   {len(snapshots)}")
    print(f"memories:    {len(out)}")
    print(f"  by action: {dict(action_counts)}")
    print(f"conflicts:   {len(conflicts)}")
    print(f"review:      {len(review)}")
    print(f"outputs in:  {OUT}")
    print(f"\n{report_engine.to_markdown()}")

    logger.info("D5 记忆抽取脚本完成",
                events=event_count, snapshots=snapshot_count,
                memories=len(out), conflicts=len(conflicts),
                review=len(review), validation_errors=len(validation_errors))
    logger.close()


if __name__ == "__main__":
    main()
