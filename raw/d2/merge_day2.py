#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D2 合并与去噪脚本 (升级版)
- 读取 raw/d2/user_behavior.json + raw/d2/tool_result.json
- 统一字段、时间流水线(4层降级)、SimHash去重、增强脱敏、DFA敏感词
- 字段校验(SchemaValidator)、结构化日志(clean.log)
- 输出 merged.jsonl + cleaning_report.json + clean.log

升级内容:
  1. TimePipeline 替代硬编码 strptime (支持相对时间/时间戳/dateutil)
  2. SimHashDedup 替代 SequenceMatcher (海明距离, 更快更准)
  3. PrivacyMasker 增强脱敏 (手机号保留前3后4, 邮箱保留首尾)
  4. SensitiveFilter DFA 敏感词检测 (forget 指令/隐私关键词)
  5. CleaningReport 自动生成清洗报告
  6. SchemaValidator 字段校验 (必需/可选字段检查)
  7. CleanLogger 结构化日志 (INFO/WARN/ERROR 四级)
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

# 导入高级清洗引擎 (lib/ 或 raw/ 或同目录)
try:
    from advanced_cleaning import (
        TimePipeline, SimHashDedup, PrivacyMasker,
        SensitiveFilter, CleaningReport,
        SchemaValidator, CleanLogger,
    )
except ImportError:
    _found = False
    _script_dir = Path(__file__).resolve().parent
    # 尝试路径: lib/ -> raw/ -> 同目录
    _search_paths = [
        _script_dir.parent / "lib",          # raw/lib/
        _script_dir.parent.parent / "raw" / "lib",  # 从 d2/ 往上找
        _script_dir.parent,                  # raw/ (旧位置)
        _script_dir.parent.parent,           # 项目根
        _script_dir,                         # 同目录
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
        raise ImportError("找不到 advanced_cleaning.py，请确保它在 raw/lib/ 或脚本同目录下")

ROOT = Path(__file__).resolve().parent


def find_project_root(start):
    cur = start
    for _ in range(5):
        if (cur / "raw").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


ROOT = find_project_root(ROOT)
RAW = ROOT / "raw" / "d2"
OUT = RAW / "merged.jsonl"  # BUG-16 修复: 输出到 raw/d2/ 而非项目根
REPORT_PATH = RAW / "cleaning_report_d2.json"

# ---------- 字段归一化 ----------
UID_KEYS = ("uid", "user_id")
TIME_KEYS = ("time", "timestamp")
CONTENT_KEYS = ("content", "text")
TYPE_KEYS = ("action", "type")


def pick(d, keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


# ---------- 全局初始化高级组件 ----------
time_pipeline = TimePipeline(base_time=datetime(2026, 6, 7))   # 以数据集基准日为锚点
privacy_masker = PrivacyMasker()
sensitive_filter = SensitiveFilter([
    "别记", "别保存", "不要保存", "忘记这个", "不保存",
    "测试号", "测试手机",
])
simhash_deduper = SimHashDedup(hash_bits=64, threshold=3)
report = CleaningReport(stage="D2_merge", base_dir=RAW)
validator = SchemaValidator()
logger = CleanLogger(log_file=str(RAW / "clean.log"))


# ---------- 时间解析 (使用 TimePipeline) ----------
def parse_time(raw):
    """使用 4 层流水线解析时间"""
    iso_str, invalid, method = time_pipeline.parse(raw)
    return iso_str, invalid


# ---------- 文本清洗 ----------
NOISE_RULES = [
    (re.compile(r"<!--.*?-->"), ""),
    (re.compile(r"@{2,}"), ""),
    (re.compile(r"!{2,}"), "!"),
    (re.compile(r"！{2,}"), "！"),
    (re.compile(r"\.{3,}"), "…"),
    (re.compile(r"…{2,}"), "…"),
    (re.compile(r"\*{2,}([^*]+?)\*{2,}"), r"\1"),
    (re.compile(r"[😅🙏😊😄🤣😂🤔😢😡🤮🤒🤕]"), ""),
    (re.compile(r"　+"), " "),
    (re.compile(r" {2,}"), " "),
]


def clean_text(s, check_sensitive=False):
    """
    清洗文本: 去噪 → 脱敏 → (可选)敏感词检测
    返回 (cleaned_text, sensitive_words_found)
    """
    if not s:
        return "", []

    # 1) 先 strip 再去噪
    s = s.strip()

    # 2) 去噪
    for pat, repl in NOISE_RULES:
        s = pat.sub(repl, s)

    # 3) 口水词 — strip 后再匹配 (循环清洗直到不再变化)
    s = re.sub(r"(然后){2,}", "然后", s)
    s = re.sub(r"(那个){2,}", "那个", s)
    # 循环移除行首口水词(含中文省略号, 允许口水词之间有省略号/空格分隔)
    for _ in range(5):  # 最多5轮
        new_s = re.sub(r"^(嗯+|呃+|啊+|哦+|那\s*个|就\s*是|就是)[\s\u2026…]*", "", s)
        if new_s == s:
            break
        s = new_s
    s = s.strip()

    # 4) 隐私脱敏 (增强版: 手机保留前3后4, 邮箱保留首尾)
    s, _ = privacy_masker.mask_all(s)

    # 5) DFA 敏感词检测
    found = []
    if check_sensitive:
        _, found = sensitive_filter.check(s)

    return s, found


# ---------- 规范化 ----------
def normalize_user_behavior(records):
    out = []
    for i, r in enumerate(records):
        # 字段校验
        is_valid, errors, warnings = validator.validate(r, "d2")
        if not is_valid:
            logger.error("user_behavior 字段校验失败", idx=i, errors=errors)
        if warnings:
            logger.debug("user_behavior 未知字段", idx=i, warnings=warnings)

        time_iso, time_invalid = parse_time(pick(r, TIME_KEYS))
        cleaned, sens = clean_text(pick(r, CONTENT_KEYS, ""), check_sensitive=True)
        uid_raw = pick(r, UID_KEYS)
        uid = (uid_raw or "").lower() if uid_raw else None
        out.append({
            "source": "user_behavior",
            "uid": uid,
            "time": time_iso,
            "time_invalid": time_invalid,
            "type": pick(r, TYPE_KEYS, "chat"),
            "content": cleaned,
            "_sensitive_hits": sens,
        })
    return out


def normalize_tool_result(doc):
    out = []
    for i, r in enumerate(doc.get("results", [])):
        raw_time = r.get("time") or r.get("timestamp")
        time_iso, time_invalid = parse_time(raw_time)
        # 工具结果如果没有时间字段，不算失败而是标记为 None
        if raw_time is None:
            time_iso, time_invalid = None, True
            logger.warn("tool_result 缺失时间字段", idx=i, uid=r.get("uid"))
        cleaned, sens = clean_text(r.get("output", ""), check_sensitive=True)
        out.append({
            "source": "tool_result",
            "uid": r.get("uid"),
            "time": time_iso,
            "time_invalid": time_invalid,
            "type": r.get("tool", "tool"),
            "content": cleaned,
            "tool_status": r.get("status"),
            "tool_latency_ms": r.get("latency_ms"),
            "trace_id": r.get("trace_id"),
            "_sensitive_hits": sens,
        })
    return out


# ---------- 去重 (SimHash 增强) ----------
def dedup(records):
    """三级去重: 完全相同 → 同uid+同时间 → SimHash近似"""
    total_in = len(records)

    # 第1级: 完全相同
    seen_exact = set()
    stage1 = []
    for r in records:
        key = (r.get("uid"), r.get("time"), r.get("content"), r.get("trace_id"))
        if key in seen_exact:
            continue
        seen_exact.add(key)
        stage1.append(r)

    exact_dup = total_in - len(stage1)

    # 第2级: 同一 uid + 同一时间
    by_ut = {}
    stage2 = []
    for r in stage1:
        ut = (r.get("uid"), r.get("time"))
        if ut in by_ut:
            by_ut[ut]["dup_count"] = by_ut[ut].get("dup_count", 1) + 1
            continue
        r["dup_count"] = 1
        by_ut[ut] = r
        stage2.append(r)

    time_dup = len(stage1) - len(stage2)

    # 第3级: SimHash 近似去重 (同 uid 内)
    final = []
    simhash_dup = 0
    for r in stage2:
        merged = False
        for f in final:
            if r["uid"] and r["uid"] == f["uid"]:
                content_a = r.get("content") or ""
                content_b = f.get("content") or ""
                if content_a and content_b:
                    dist = SimHashDedup.hamming_distance(
                        simhash_deduper.compute_fingerprint(content_a),
                        simhash_deduper.compute_fingerprint(content_b),
                    )
                    if dist <= 3:  # 海明距离 <= 3 视为近似重复
                        f["dup_count"] = f.get("dup_count", 1) + 1
                        f["_simhash_dist"] = dist
                        merged = True
                        simhash_dup += 1
                        break
        if not merged:
            final.append(r)

    report.add_metric("dedup_exact", exact_dup)
    report.add_metric("dedup_same_time", time_dup)
    report.add_metric("dedup_simhash", simhash_dup)
    report.add_metric("dropped_duplicates", exact_dup + time_dup + simhash_dup)

    return final


def sort_key(r):
    return (r.get("time_invalid", False), r.get("time") or "9999", r.get("uid") or "")


def main():
    logger.info("=" * 50)
    logger.info("D2 合并去噪脚本启动")
    logger.info("输入: user_behavior.json + tool_result.json")

    user_path = RAW / "user_behavior.json"
    tool_path = RAW / "tool_result.json"

    try:
        user_raw = json.loads(user_path.read_text(encoding="utf-8"))
        tool_raw = json.loads(tool_path.read_text(encoding="utf-8"))
        logger.info("读取输入文件成功", user=len(user_raw), tool=len(tool_raw.get("results", [])))
    except FileNotFoundError as e:
        logger.error("输入文件不存在", path=str(e))
        raise
    except json.JSONDecodeError as e:
        logger.error("JSON 解析失败", path=str(e))
        raise

    total_input = len(user_raw) + len(tool_raw.get("results", []))
    report.set_input_count(total_input)
    report.add_pipeline_step("字段归一化与合并", total_input, None, f"user={len(user_raw)} tool={len(tool_raw.get('results', []))}")

    records = normalize_user_behavior(user_raw) + normalize_tool_result(tool_raw)
    after_normalize = len(records)
    report.add_pipeline_step("文本清洗(去噪+脱敏+DFA)", total_input, after_normalize)
    logger.info("完成字段归一化和文本清洗", valid=after_normalize, total=total_input)

    records = dedup(records)
    after_dedup = len(records)
    report.add_pipeline_step("三级去重(精确+时间+SimHash)", after_normalize, after_dedup)
    logger.info("完成三级去重", after_dedup=after_dedup, dropped=after_normalize - after_dedup)

    records.sort(key=sort_key)

    # 统计敏感词命中
    all_sens = []
    for r in records:
        val = r.pop("_sensitive_hits", None)
        if isinstance(val, list):
            all_sens.extend(val)
    if all_sens:
        report.add_sensitive_words_found(list(set(all_sens)))
        report.add_metric("sensitive_hits", len(all_sens))
        logger.info("敏感词命中", count=len(all_sens), words=list(set(all_sens)))

    # 统计时间解析失败 (仅统计有时间字符串但解析失败的,不包括缺失时间字段)
    failed_time = sum(1 for r in records if r.get("time_invalid") and r.get("time") is not None)
    missing_time = sum(1 for r in records if r.get("time_invalid") and r.get("time") is None)
    report.add_metric("failed_time_parsing", failed_time)
    report.add_metric("missing_time_field", missing_time)
    logger.info("时间解析统计", failed=failed_time, missing=missing_time)

    # 写输出
    OUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    logger.info("输出写入完成", path=str(OUT), records=len(records))

    # 生成报告
    report.finish(valid_count=len(records), output_path=str(REPORT_PATH))

    # 关闭日志
    logger.info("=" * 50)
    logger.info("D2 合并去噪脚本完成", total_input=total_input, valid_output=len(records))
    logger.close()

    print(f"wrote {len(records)} records -> {OUT}")
    for r in records:
        flag = " [invalid_time]" if r.get("time_invalid") else ""
        dup = f" [dup={r.get('dup_count', 1)}]" if r.get("dup_count", 1) > 1 else ""
        sim = f" [simhash_dist={r.get('_simhash_dist')}]" if r.get("_simhash_dist") is not None else ""
        print(f"  - {r['source']:13s} {str(r.get('uid')):5s} "
              f"{str(r.get('time'))[:19]:19s}{flag}{dup}{sim}"
              f" type={r.get('type')} content={r.get('content')[:60]}")

    # 打印报告摘要
    print(f"\n{report.to_markdown()}")


if __name__ == "__main__":
    main()
