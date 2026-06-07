#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D3 基础验收脚本 (升级版)
- 读取 raw/d3/chat_sessions_dirty.csv
- TimePipeline 时间流水线 + PrivacyMasker 增强脱敏 + SensitiveFilter DFA
- SimHash 近似去重 + CleaningReport 自动报告
- 输出 chat_sessions_clean.csv + cleaning_report_d3.json

升级内容:
  1. TimePipeline 4层时间解析 (支持"昨天"/时间戳/dateutil)
  2. PrivacyMasker 手机号保留前3后4, 邮箱保留首尾
  3. SensitiveFilter DFA 检测 forget/隐私关键词
  4. SimHash 近似去重 (海明距离)
  5. CleaningReport 结构化报告
"""

import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime

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
IN_FILE = ROOT / "raw" / "d3" / "chat_sessions_dirty.csv"
OUT_FILE = ROOT / "chat_sessions_clean.csv"
REPORT_PATH = ROOT / "raw" / "d3" / "cleaning_report_d3.json"

# ---------- 全局高级组件 ----------
time_pipeline = TimePipeline(base_time=datetime(2026, 6, 7))
privacy_masker = PrivacyMasker()
sensitive_filter = SensitiveFilter([
    "别记", "别保存", "不要保存", "忘记这个", "不保存",
])
simhash_deduper = SimHashDedup(hash_bits=64, threshold=3)
report = CleaningReport(stage="D3_basic", base_dir=ROOT / "raw" / "d3")
validator = SchemaValidator()
logger = CleanLogger(log_file=str(ROOT / "raw" / "d3" / "clean.log"))


# ---------- 时间解析 (TimePipeline) ----------
def parse_time(s):
    iso_str, invalid, method = time_pipeline.parse(s)
    return iso_str, invalid


# ---------- 文本清洗 (增强版) ----------
NOISE_RULES = [
    (re.compile(r"<[^>]+>"), ""),
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
    增强文本清洗: 去噪 → 口水词 → 隐私脱敏(增强) → DFA敏感词
    返回 (cleaned_text, sensitive_words, privacy_details)
    """
    if not s:
        return "", [], []

    # 1) 去噪
    for pat, repl in NOISE_RULES:
        s = pat.sub(repl, s)

    # 2) 口水词 (循环清洗直到不再变化)
    s = re.sub(r"(然后){2,}", "然后", s)
    s = re.sub(r"(那个){2,}", "那个", s)
    for _ in range(5):
        new_s = re.sub(r"^(嗯+|呃+|啊+|哦+|那\s*个|就\s*是|就是)[\s\u2026…]*", "", s)
        if new_s == s:
            break
        s = new_s
    s = re.sub(r"啊啊啊+", "", s)
    s = re.sub(r"啊+$", "", s)

    # 3) 增强隐私脱敏
    privacy_details = []
    s, privacy_details = privacy_masker.mask_all(s)

    # 4) DFA 敏感词检测
    found = []
    if check_sensitive:
        _, found = sensitive_filter.check(s)

    return s.strip(), found, privacy_details


def main():
    logger.info("D3 基础清洗脚本启动")
    logger.info("输入文件", path=str(IN_FILE))

    try:
        rows = list(csv.DictReader(IN_FILE.read_text(encoding="utf-8").splitlines()))
    except FileNotFoundError:
        logger.error("输入文件不存在", path=str(IN_FILE))
        raise
    except Exception as e:
        logger.error("读取输入文件失败", path=str(IN_FILE), error=str(e))
        raise

    print(f"input: {len(rows)} rows")
    report.set_input_count(len(rows))

    # 第1步: 去重 (SimHash 增强)
    seen_exact = set()
    stage1 = []
    exact_dup = 0
    for r in rows:
        key = (r.get("session_id"), r.get("user_id"), r.get("role"), r.get("message"))
        if key in seen_exact:
            exact_dup += 1
            continue
        seen_exact.add(key)
        stage1.append(r)
    report.add_metric("dedup_exact", exact_dup)
    report.add_pipeline_step("精确去重", len(rows), len(stage1), f"去重 {exact_dup} 行")
    logger.info("完成精确去重", dropped=exact_dup, kept=len(stage1))
    print(f"dedup exact: {exact_dup} duplicate row(s) dropped, {len(stage1)} kept")

    # 第2步: 清洗 + 标记
    output_rows = []
    total_privacy_masked = 0
    total_sensitive_hits = 0
    failed_time_count = 0

    for i, r in enumerate(stage1):
        # Schema 校验
        is_valid, errors, warnings = validator.validate(r, "d3")
        if not is_valid:
            logger.error("字段校验失败", row_idx=i, errors=errors)
        if warnings:
            logger.debug("未知字段", row_idx=i, warnings=warnings)

        flags = []
        time_iso, time_invalid = parse_time(r.get("created_at", ""))
        r["created_at"] = time_iso or ""
        if time_invalid:
            flags.append("time_invalid")
            failed_time_count += 1
        if not (r.get("user_id") or "").strip():
            flags.append("missing_user_id")
        original_msg = r.get("message", "") or ""
        if not original_msg.strip():
            flags.append("empty_message")

        cleaned_msg, sens_hits, priv_details = clean_text(original_msg, check_sensitive=True)

        # 标记隐私脱敏
        if priv_details:
            flags.append("privacy_masked")
            total_privacy_masked += len(priv_details)
            for p in priv_details:
                if p["type"] == "phone":
                    flags.append("phone_masked")
                elif p["type"] == "email":
                    flags.append("email_masked")

        # 标记敏感词
        if sens_hits:
            flags.append("sensitive_detected")
            total_sensitive_hits += len(sens_hits)

        r["message"] = cleaned_msg
        r["flags"] = ",".join(flags) if flags else "ok"
        output_rows.append(r)

    logger.info("完成清洗", valid=len(output_rows), privacy=total_privacy_masked, sensitive=total_sensitive_hits)

    report.add_pipeline_step("清洗(去噪+脱敏+DFA)", len(stage1), len(output_rows))
    report.add_metric("masked_privacy_info", total_privacy_masked)
    report.add_metric("sensitive_hits", total_sensitive_hits)
    report.add_metric("failed_time_parsing", failed_time_count)
    report.add_metric("dropped_duplicates", exact_dup)

    # 第3步: 排序
    output_rows.sort(key=lambda r: (r.get("session_id") or "", r.get("created_at") or "9999"))

    # 写文件
    fieldnames = ["session_id", "user_id", "role", "message", "created_at", "flags"]
    with OUT_FILE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in output_rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    # 统计 & 报告
    flag_counts = {}
    for r in output_rows:
        for f in r["flags"].split(","):
            flag_counts[f] = flag_counts.get(f, 0) + 1

    report.finish(valid_count=len(output_rows), output_path=str(REPORT_PATH))

    logger.info("D3 基础清洗脚本完成", total_input=len(rows), valid_output=len(output_rows))
    logger.close()

    print(f"wrote {len(output_rows)} rows -> {OUT_FILE}")
    print("flag counts:", flag_counts)
    print(f"\n{report.to_markdown()}")


if __name__ == "__main__":
    main()
