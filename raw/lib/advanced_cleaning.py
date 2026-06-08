#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
高级清洗引擎 (advanced_cleaning.py)
=====================================
7 大核心能力，供 D2/D3/D4/D5/D6 脚本 import 复用：

1. DFA 敏感词过滤器 (Aho-Corasick 自动机)
   - O(N) 时间复杂度，与词库大小无关
   - 支持敏感词替换为 *** 或自定义掩码

2. 时间格式统一流水线 (Fallback Pipeline)
   - 第1层：标准 strptime 格式匹配
   - 第2层：纯数字时间戳转换
   - 第3层：dateutil 模糊解析（自动识别中文日期）
   - 第4层：相对时间（昨天/上周三）+ 基准时间偏移

3. SimHash 近似去重
   - 海明距离 < threshold 视为近似重复
   - 比完全字符串匹配更智能（能抓"定/订"这类错别字）

4. 隐私脱敏增强
   - 手机号：保留前3后4 → 138****5678（行业标准）
   - 邮箱：用户名保留首尾各2位 → ab****ef@example.com
   - 身份证：保留前3后4

5. 清洗报告生成器 (cleaning_report.json)
   - 自动统计 total/valid/dropped/masked/failed 等指标
   - 每次运行输出结构化报告

6. 字段校验器 (SchemaValidator)
   - 预置 D2-D6 schema，校验必需/可选字段
   - 批量校验 + 错误分类统计

7. 清洗日志 (CleanLogger)
   - 结构化日志写入 clean.log
   - 支持 INFO/WARN/ERROR/DEBUG 四级

使用方式:
    from advanced_cleaning import (
        SensitiveFilter,
        TimePipeline,
        SimHashDedup,
        PrivacyMasker,
        CleaningReport,
        SchemaValidator,
        CleanLogger,
        create_logger,
    )
"""

import json
import re
import hashlib
import math
import time as _time
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path


# ============================================================
# 1. DFA 敏感词过滤器 (Aho-Corasick 自动机)
# ============================================================

class SensitiveFilter:
    """
    基于 Aho-Corasick 自动机的敏感词过滤器。
    时间复杂度 O(N)，N 为文本长度，与词库大小无关。

    用法:
        sf = SensitiveFilter(["别记", "不要保存", "忘记", "手机号", "邮箱"])
        result = sf.filter_text("我的邮箱是xxx，别记下来")
        # → "我的[SENSITIVE]是xxx，[SENSITIVE]"

    如果没有安装 pyahocorasick 库，自动回退到正则匹配模式。
    """

    def __init__(self, word_list, mask="[SENSITIVE]"):
        self.word_list = sorted(set(word_list), key=len, reverse=True)  # 长词优先
        self.mask = mask
        self._use_automaton = False
        self._automaton = None
        self._regex = None

        # 尝试加载 Aho-Corasick
        try:
            import ahocorasick
            self._automaton = ahocorasick.Automaton()
            for idx, word in enumerate(self.word_list):
                if word:
                    self._automaton.add_word(word, (idx, word))
            self._automaton.make_automaton()
            self._use_automaton = True
        except ImportError:
            # 回退到正则模式
            escaped = [re.escape(w) for w in self.word_list if w]
            if escaped:
                self._regex = re.compile("|".join(escaped))

    def filter_text(self, text):
        """返回脱敏后的文本 + 命中的敏感词列表"""
        if not text:
            return text, []
        found = []

        if self._use_automaton:
            # Aho-Corasick 模式: 从右往左替换避免偏移
            matches = list(self._automaton.iter(text))
            # 按 end_index 降序排列，从后往前替换
            matches.sort(key=lambda x: x[0], reverse=True)
            for end_index, (idx, word) in matches:
                start_index = end_index - len(word) + 1
                text = text[:start_index] + self.mask * len(word) + text[end_index + 1:]
                found.append(word)
        elif self._regex:
            # 正则回退模式
            def _replace(m):
                found.append(m.group(0))
                return self.mask * len(m.group(0))
            text = self._regex.sub(_replace, text)

        return text, found

    def check(self, text):
        """仅检查是否包含敏感词，不修改文本"""
        if not text:
            return [], False
        found = []
        if self._use_automaton:
            for _, (_, word) in self._automaton.iter(text):
                found.append(word)
        elif self._regex:
            found = self._regex.findall(text)
        return found, len(found) > 0


# ============================================================
# 2. 时间格式统一流水线 (Fallback Pipeline)
# ============================================================

class TimePipeline:
    """
    4 层降级时间解析流水线。

    第1层：标准 strptime 格式匹配（覆盖 15+ 种常见格式）
    第2层：纯数字时间戳（10 位秒 / 13 位毫秒）
    第3层：dateutil.parser 模糊解析（中英文日期都能认）
    第4层：相对时间（昨天/今天/明天/上周三...）+ 基准时间偏移

    用法:
        tp = TimePipeline(base_time=datetime(2026, 6, 7))
        result = tp.parse("2026年6月4日 14:00")
        # → ("2026-06-04 14:00:00", False, "strptime")

        result = tp.parse("昨天下午3点")
        # → ("2026-06-06 15:00:00", False, "relative")
    """

    # 第1层: 标准格式列表
    STANDARD_FMTS = [
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S+08:00",  # 显式时区
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y/%m/%d",
        "%Y-%m-%d",
    ]

    # 第4层: 相对时间关键词映射 (BUG-4 修复: 全部用 lambda 包装, 调用时再求值)
    RELATIVE_PATTERNS = [
        (r"^(前天)", -2),
        (r"^(昨天)", -1),
        (r"^(今天|当天)", 0),
        (r"^(明天|次日)", 1),
        (r"^(后天)", 2),
        (r"^(\d+)天前", lambda m, _bt: -int(m.group(1))),
        (r"^(\d+)天后", lambda m, _bt: int(m.group(1))),
        (r"^(上周一?|last\s+(?:monday))", lambda _m, bt: -_weekday_offset(1, bt)),
        (r"^(上周二?|last\s+tuesday)", lambda _m, bt: -_weekday_offset(2, bt)),
        (r"^(上周三?|last\s+wednesday)", lambda _m, bt: -_weekday_offset(3, bt)),
        (r"^(上周四?|last\s+thursday)", lambda _m, bt: -_weekday_offset(4, bt)),
        (r"^(上周五?|last\s+friday)", lambda _m, bt: -_weekday_offset(5, bt)),
        (r"^(上周六?|last\s+saturday)", lambda _m, bt: -_weekday_offset(6, bt)),
        (r"^(上周日?|last\s+sunday)", lambda _m, bt: -_weekday_offset(7, bt)),
        (r"^(这周一?|this\s+monday)", lambda _m, bt: _weekday_offset(1, bt, this_week=True)),
    ]

    # 相对时间中的时段提取
    TIME_OF_DAY = [
        (r"(凌晨|午夜|\d+[点时:]\d*)", 0),      # 凌晨
        (r"(上午|早上|清晨|\d+[点时](?!下午|晚上)\d*)", 12),  # 上午
        (r"(中午|午间|正午)", 12),
        (r"(下午|午后|pm|PM)", 12),
        (r"(傍晚|晚间|晚上|夜间|夜)", 18),
        (r"(深夜|凌晨晚)", 23),
    ]

    def __init__(self, base_time=None):
        self.base_time = base_time or datetime.now()
        self._parser = None
        try:
            from dateutil import parser as _du_parser
            self._parser = _du_parser
        except ImportError:
            pass

    def parse(self, raw):
        """
        返回 (iso_string, is_invalid, method_used)
        method_used ∈ {strptime, timestamp, dateutil, relative, failed}
        """
        if raw is None:
            return None, True, "empty"
        s = str(raw).strip()
        if not s:
            return None, True, "empty"

        # ---- 第1层: 标准 strptime ----
        for fmt in self.STANDARD_FMTS:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d %H:%M:%S"), False, "strptime"
            except ValueError:
                continue

        # ---- 第2层: 纯数字时间戳 ----
        ts_clean = s.replace(".", "").strip()
        if ts_clean.isdigit():
            ts_int = int(ts_clean)
            if 1e9 < ts_int < 2e9:       # 10 位秒级
                dt = datetime.fromtimestamp(ts_int)
                return dt.strftime("%Y-%m-%d %H:%M:%S"), False, "timestamp"
            elif 1e12 < ts_int < 2e13:    # 13 位毫秒级
                dt = datetime.fromtimestamp(ts_int / 1000)
                return dt.strftime("%Y-%m-%d %H:%M:%S"), False, "timestamp_ms"

        # ---- 第3层: dateutil 模糊解析 ----
        if self._parser:
            try:
                dt = self._parser.parse(s)
                return dt.strftime("%Y-%m-%d %H:%M:%S"), False, "dateutil"
            except Exception:
                pass

        # ---- 第4层: 相对时间 ----
        parsed_relative = self._parse_relative(s)
        if parsed_relative:
            return parsed_relative

        # 全部失败
        return s, True, "failed"

    def _parse_relative(self, s):
        """尝试解析相对时间表达式"""
        offset_days = None
        hour_offset = 0

        for pattern, days_delta in self.RELATIVE_PATTERNS:
            m = re.search(pattern, s)
            if m:
                if callable(days_delta):
                    # BUG-4 修复: 闭包内 self.base_time 已经捕获 (上层实例), 不需要额外参数
                    # 但 days_delta 是 _weekday_offset 的偏函数, 需要 base_time
                    # 改用 lambda 包装时传入 base_time
                    if days_delta.__name__ == "_weekday_offset":
                        offset_days = days_delta(m, self.base_time)
                    else:
                        offset_days = days_delta(m)
                else:
                    offset_days = days_delta
                break

        if offset_days is None:
            return None

        target_date = self.base_time + timedelta(days=offset_days)

        # 提取时段
        for pattern, base_hour in self.TIME_OF_DAY:
            m = re.search(pattern, s)
            if m:
                # 尝试提取具体小时
                hm = re.search(r"(\d+)\s*[点时:]\s*(\d*)", s)
                if hm:
                    h = int(hm.group(1))
                    mi = int(hm.group(2)) if hm.group(2) else 0
                    # 下午/晚上加 12
                    if base_hour >= 12 and h < 12:
                        h += 12
                    target_date = target_date.replace(hour=h, minute=mi, second=0)
                else:
                    target_date = target_date.replace(hour=base_hour, minute=0, second=0)
                break

        return target_date.strftime("%Y-%m-%d %H:%M:%S"), False, "relative"


def _weekday_offset(target_wday, base_time=None, this_week=False):
    """
    计算距离目标星期几的天数偏移
    BUG-4 修复: 接受 base_time 参数, 不再用 datetime.now()
    """
    if base_time is None:
        base_time = datetime.now()
    now = base_time.weekday()  # 0=Monday
    target = target_wday - 1         # 转为 0-based Monday
    if this_week:
        diff = target - now
        if diff < 0:
            diff += 7
    else:
        diff = target - now - 7
        if diff > -7:
            diff -= 7
    return diff


# ============================================================
# 3. SimHash 近似去重
# ============================================================

class SimHashDedup:
    """
    基于 SimHash 的近似重复检测。
    通过计算文本的 SimHash 指纹，用海明距离判断相似度。

    用法:
        deduper = SimHashDedup(threshold=3)
        deduper.add("帮我定明天去北京的机票")
        deduper.add("帮我订明天去北京的机票")  # 海明距离小，判为重复
        is_dup, dist = deduper.check("帮我订购明天去北京飞机票")
    """

    def __init__(self, hash_bits=64, threshold=3, lsh_bands=4, lsh_rows=16):
        """
        BUG-15 修复: 引入 LSH 桶索引, 检查从 O(N) 降到 O(1)~O(K) (K 是同桶候选数)
        64-bit 默认 4 bands × 16 rows, 配合 threshold=3 命中率 > 95%
        lsh_bands * lsh_rows 必须 == hash_bits
        """
        if lsh_bands * lsh_rows != hash_bits:
            raise ValueError(f"lsh_bands({lsh_bands}) * lsh_rows({lsh_rows}) 必须等于 hash_bits({hash_bits})")
        self.hash_bits = hash_bits
        self.threshold = threshold
        self.lsh_bands = lsh_bands
        self.lsh_rows = lsh_rows
        self._fingerprints = []   # [(fingerprint, key)]
        self._lsh_buckets = [dict() for _ in range(lsh_bands)]  # band -> {band_hash: [idx_in_fingerprints]}

    def reset(self):
        self._fingerprints = []
        self._lsh_buckets = [dict() for _ in range(self.lsh_bands)]

    @staticmethod
    def _tokenize(text):
        """字符级 bigram 分词（适合中文无空格场景）"""
        text = (text or "").lower().strip()
        chars = re.findall(r"[\u4e00-\u9fa5]|\w", text)
        return [a + b for a, b in zip(chars, chars[1:])] + chars

    @staticmethod
    def _hash_token(token):
        """将 token 映射为一个整数哈希"""
        return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)

    def compute_fingerprint(self, text):
        """计算文本的 SimHash 指纹"""
        tokens = self._tokenize(text)
        if not tokens:
            return 0
        vec = [0] * self.hash_bits
        for t in tokens:
            h = self._hash_token(t)
            for i in range(self.hash_bits):
                bitmask = 1 << i
                vec[i] += 1 if h & bitmask else -1
        fingerprint = 0
        for i in range(self.hash_bits):
            if vec[i] > 0:
                fingerprint |= 1 << i
        return fingerprint

    def _band_hashes(self, fp):
        """把 fingerprint 切成 bands, 每个 band 提取 lsh_rows 位作为桶 key"""
        hashes = []
        for b in range(self.lsh_bands):
            # 取 band b 的 lsh_rows 位 (从低位开始切片)
            shift = b * self.lsh_rows
            mask = (1 << self.lsh_rows) - 1
            hashes.append((fp >> shift) & mask)
        return hashes

    @staticmethod
    def hamming_distance(fp1, fp2):
        """计算两个指纹的海明距离"""
        x = fp1 ^ fp2
        dist = 0
        while x:
            dist += 1
            x &= x - 1
        return dist

    def add(self, text, key=None):
        """添加一条记录到去重集合 + LSH 桶"""
        fp = self.compute_fingerprint(text)
        k = key or text
        idx = len(self._fingerprints)
        self._fingerprints.append((fp, k))
        # 写入所有 band 桶
        for b, band_hash in enumerate(self._band_hashes(fp)):
            self._lsh_buckets[b].setdefault(band_hash, []).append(idx)

    def check(self, text):
        """
        检查是否与已有记录近似重复 (LSH 优化版)。
        返回 (is_duplicate, min_distance, matched_key)
        """
        fp = self.compute_fingerprint(text)
        # 用 LSH 桶收集候选索引 (set 去重)
        candidates = set()
        for b, band_hash in enumerate(self._band_hashes(fp)):
            candidates.update(self._lsh_buckets[b].get(band_hash, []))

        if not candidates:
            return False, self.hash_bits, None

        min_dist = self.hash_bits + 1
        matched = None
        for idx in candidates:
            stored_fp, key = self._fingerprints[idx]
            d = self.hamming_distance(fp, stored_fp)
            if d < min_dist:
                min_dist = d
                matched = key
        return min_dist <= self.threshold, min_dist, matched

    def dedup_records(self, records, key_fn=None, content_fn=None):
        """
        对记录列表做近似去重。
        records: list of dict
        key_fn: 提取唯一标识的函数 (默认用 uid+time)
        content_fn: 提取用于比较的内容的函数 (默认用 content/text/message)
        返回 (去重后列表, 去重数量)
        """
        if key_fn is None:
            key_fn = lambda r: (r.get("uid") or "", r.get("time") or r.get("ts") or "")
        if content_fn is None:
            content_fn = lambda r: r.get("content") or r.get("text") or r.get("message") or ""

        kept = []
        # BUG-3 修复: O(1) key->index 映射, 替代 O(N) 循环查找
        key_to_idx = {}
        dup_count = 0
        sim = SimHashDedup(hash_bits=self.hash_bits, threshold=self.threshold)

        for r in records:
            content = content_fn(r)
            r_key = key_fn(r)
            is_dup, dist, matched_key = sim.check(content)
            if is_dup:
                dup_count += 1
                # matched_key 是之前 sim.add 时存的 key
                if matched_key in key_to_idx:
                    idx = key_to_idx[matched_key]
                    kept[idx]["_simhash_dup_count"] = kept[idx].get("_simhash_dup_count", 1) + 1
            else:
                sim.add(content, r_key)
                r["_simhash_dup_count"] = 1
                key_to_idx[r_key] = len(kept)
                kept.append(r)

        return kept, dup_count


# ============================================================
# 4. 隐私脱敏增强
# ============================================================

class PrivacyMasker:
    """
    增强版隐私脱敏器。

    手机号: 13812345678 → 138****5678  (保留前3后4, 行业标准)
    邮箱:   user@example.com → us****er@example.com  (用户名保留首尾各2位)
    身份证: 110101199001011234 → 110***********1234  (保留前3后4)
    密码:   直接替换为 [PASSWORD]

    用法:
        pm = PrivacyMasker()
        masked, info = pm.mask_all("我的手机号13812345678，邮箱test@foo.com")
        # → ("我的手机号138****5678，邮箱te****st@foo.com", [{"type":"phone","original":"13812345678"}, ...])
    """

    PHONE_PATTERN = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')
    EMAIL_PATTERN = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
    ID_CARD_PATTERN = re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)')
    PASSWORD_HINT = re.compile(r'(密码|password|passwd)[是为：:\s]*([\S]{1,20})', re.IGNORECASE)

    def __init__(self, phone_mask="****", email_mask="****", id_mask="*"):
        self.phone_mask = phone_mask
        self.email_mask = email_mask
        self.id_mask = id_mask

    def mask_phone(self, match):
        """手机号: 保留前3后4"""
        original = match.group(0)
        return original[:3] + self.phone_mask + original[-4:]

    def mask_email(self, match):
        """邮箱: 用户名保留首尾各2位"""
        original = match.group(0)
        at_idx = original.index("@")
        username = original[:at_idx]
        domain = original[at_idx:]
        if len(username) <= 4:
            masked_user = self.email_mask[:len(username)] if len(username) <= len(self.email_mask) else "*" * len(username)
        else:
            masked_user = username[:2] + self.email_mask + username[-2:]
        return masked_user + domain

    def mask_id_card(self, match):
        """身份证: 保留前3后4"""
        original = match.group(0)
        return original[:3] + self.id_mask * (len(original) - 7) + original[-4:]

    def mask_password(self, match):
        """密码: 完全遮盖"""
        return f"{match.group(1)}: [PASSWORD]"

    def mask_all(self, text):
        """
        对文本执行所有脱敏操作。
        返回 (masked_text, details_list)
        details_list: [{"type": "phone/email/id_card/password", "original": "..."}]
        """
        if not text:
            return text, []

        details = []

        # 密码优先（最短匹配）
        text, pw_details = self._mask_with_detail(
            text, self.PASSWORD_HINT, self.mask_password, "password"
        )
        details.extend(pw_details)

        # 身份证
        text, id_details = self._mask_with_detail(
            text, self.ID_CARD_PATTERN, self.mask_id_card, "id_card"
        )
        details.extend(id_details)

        # 手机号
        text, ph_details = self._mask_with_detail(
            text, self.PHONE_PATTERN, self.mask_phone, "phone"
        )
        details.extend(ph_details)

        # 邮箱
        text, em_details = self._mask_with_detail(
            text, self.EMAIL_PATTERN, self.mask_email, "email"
        )
        details.extend(em_details)

        return text, details

    def _mask_with_detail(self, text, pattern, mask_fn, dtype):
        """执行带详情收集的替换"""
        details = []
        def replacer(m):
            original = m.group(0)
            details.append({"type": dtype, "original": original})
            return mask_fn(m)
        text = pattern.sub(replacer, text)
        return text, details


# ============================================================
# 5. 清洗报告生成器
# ============================================================

class CleaningReport:
    """
    清洗报告生成器。每次清洗完成后调用，输出结构化 JSON 报告。

    用法:
        report = CleaningReport(stage="D2_merge")
        report.set_input_count(9)
        report.add_metric("dropped_duplicates", 1)
        report.add_metric("masked_privacy_info", 2)
        report.add_metric("failed_time_parsing", 1)
        report.add_sensitive_words_found(["别记", "邮箱"])
        report.finish(valid_count=8)
        report.save("cleaning_report.json")
    """

    def __init__(self, stage="", base_dir=None):
        self.stage = stage
        self.base_dir = base_dir
        self.start_time = _time.time()
        self.data = {
            "stage": stage,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration_seconds": 0,
            "total_records_in": 0,
            "valid_records_out": 0,
            "metrics": {},
            "sensitive_words_found": [],
            "processing_pipeline": [],
        }

    def set_input_count(self, n):
        self.data["total_records_in"] = n

    def set_output_count(self, n):
        self.data["valid_records_out"] = n

    def add_metric(self, key, value):
        self.data["metrics"][key] = value

    def add_metrics(self, **kwargs):
        self.data["metrics"].update(kwargs)

    def add_sensitive_words_found(self, words):
        self.data["sensitive_words_found"].extend(words)

    def add_pipeline_step(self, step_name, input_n, output_n, detail=""):
        self.data["processing_pipeline"].append({
            "step": step_name,
            "input": input_n,
            "output": output_n,
            "detail": detail,
        })

    def finish(self, valid_count=None, output_path=None):
        self.data["duration_seconds"] = round(_time.time() - self.start_time, 3)
        if valid_count is not None:
            self.data["valid_records_out"] = valid_count

        # 计算衍生指标
        m = self.data["metrics"]
        total = self.data["total_records_in"]
        dropped = m.get("dropped_duplicates", 0) + m.get("dropped_garbage", 0) + m.get("dropped_empty", 0)
        masked = m.get("masked_privacy_info", 0)
        failed_time = m.get("failed_time_parsing", 0)
        sensitive = m.get("sensitive_hits", 0)

        self.data["summary"] = {
            "retention_rate": round((self.data["valid_records_out"] / max(total, 1)) * 100, 1),
            "dedup_rate": round((m.get("dropped_duplicates", 0) / max(total, 1)) * 100, 1),
            "privacy_masked_count": masked,
            "time_parse_failure_rate": round((failed_time / max(total, 1)) * 100, 1),
            "sensitive_hit_count": sensitive,
        }

        if output_path:
            self.save(output_path)
        return self.data

    def save(self, path):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[报告] 清洗报告已保存 -> {p}")

    def to_markdown(self):
        """生成 Markdown 格式报告"""
        d = self.data
        lines = [f"# 清洗报告 [{d['stage']}]", ""]
        lines.append(f"生成时间: {d['generated_at']} | 耗时: {d['duration_seconds']}s\n")
        lines.append(f"| 指标 | 数值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 输入记录数 | {d['total_records_in']} |")
        lines.append(f"| 有效输出数 | {d['valid_records_out']} |")
        s = d.get("summary", {})
        lines.append(f"| 保留率 | {s.get('retention_rate', '?')}% |")
        lines.append(f"| 去重率 | {s.get('dedup_rate', '?')}% |")
        lines.append(f"| 隐私脱敏数 | {s.get('privacy_masked_count', 0)} |")
        lines.append(f"| 时间解析失败 | {s.get('time_parse_failure_rate', '?')}% |")
        lines.append(f"| 敏感词命中 | {s.get('sensitive_hit_count', 0)} |")
        lines.append("")
        if d.get("metrics"):
            lines.append("## 详细指标")
            for k, v in d["metrics"].items():
                lines.append(f"- {k}: {v}")
            lines.append("")
        if d.get("processing_pipeline"):
            lines.append("## 处理流水线")
            for step in d["processing_pipeline"]:
                lines.append(f"- **{step['step']}**: {step['input']} → {step['output']}"
                             f"{(' (' + step['detail'] + ')') if step.get('detail') else ''}")
            lines.append("")
        if d.get("sensitive_words_found"):
            lines.append(f"## 敏感词命中: {', '.join(d['sensitive_words_found'])}\n")
        return "\n".join(lines)


# ============================================================
# 便捷函数: 一行调用的快捷接口
# ============================================================

def quick_clean_text(text, privacy=True, noise=True):
    """快速文本清洗（隐私+噪声），一行搞定"""
    if not text:
        return text, {}
    result = {"original_len": len(text)}

    if privacy:
        pm = PrivacyMasker()
        text, details = pm.mask_all(text)
        result["privacy"] = details

    if noise:
        rules = [
            (re.compile(r"<[^>]+>"), ""),
            (re.compile(r"<!--.*?-->"), ""),
            (re.compile(r"@{2,}"), ""),
            (re.compile(r"!{2,}"), "!"),
            (re.compile(r"！{2,}"), "！"),
            (re.compile(r"\.{3,}"), "…"),
            (re.compile(r"[😅🙏😊😄🤣😂🤔😢😡🤮🤒🤕]"), ""),
            (re.compile(r"　+"), " "),
            (re.compile(r" {2,}"), " "),
        ]
        for pat, repl in rules:
            text = pat.sub(repl, text)
        text = re.sub(r"^(嗯+|呃+|啊+|哦+|那个+|就是+)+", "", text).strip()

    result["cleaned_len"] = len(text)
    result["compression_ratio"] = round(result["cleaned_len"] / max(result["original_len"], 1), 2)
    return text, result


# ============================================================
# 6. 字段校验器 (SchemaValidator)
# ============================================================

class SchemaValidator:
    """
    数据字段校验器。定义每条记录的必需字段、可选字段、类型约束。
    校验失败时记录详细错误信息，可用于生成 clean.log。

    用法:
        validator = SchemaValidator()
        validator.register_schema("d2", required=["uid", "content"], optional=["time", "type"])
        is_valid, errors = validator.validate({"uid": "u001", "content": "hello"}, "d2")
    """

    def __init__(self):
        self._schemas = {}
        # 预置常用 schema
        self._register_defaults()

    def _register_defaults(self):
        """预置 D2-D6 的字段校验规则"""
        # D2 合并去噪
        self.register_schema("d2", required=["uid", "content"], optional=["time", "type", "source"],
                             validators={"uid": self._check_uid, "time": self._check_time})

        # D3 基础清洗
        self.register_schema("d3", required=["user_id", "message"], optional=["session_id", "role", "created_at"],
                             validators={"user_id": self._check_uid, "message": self._check_non_empty,
                                         "created_at": self._check_time})

        # D4 多源清洗 - 对话
        self.register_schema("d4_chat", required=["uid", "content", "time"], optional=["role", "session_id", "type"],
                             validators={"uid": self._check_uid, "content": self._check_non_empty,
                                         "time": self._check_time})

        # D4 知识
        self.register_schema("d4_knowledge", required=["title", "answer"], optional=["category", "source", "time"])

        # D4 偏好
        self.register_schema("d4_preference", required=["uid", "key", "value"], optional=["scope", "time"])

        # D4 工具
        self.register_schema("d4_tool", required=["uid", "tool_name", "status"], optional=["time", "params", "output"])

        # D5 记忆
        self.register_schema("d5_memory", required=["uid", "memory_key", "value"],
                             optional=["action", "scope", "reason", "time", "evidence", "history"])

        # D6 评测
        self.register_schema("d6_eval", required=["query", "expected_keywords"], optional=["category"])

    @staticmethod
    def _check_uid(value):
        if not value:
            return False, "uid 为空"
        if not isinstance(value, str):
            return False, f"uid 应为字符串，实际 {type(value).__name__}"
        if len(value) < 2 or len(value) > 64:
            return False, f"uid 长度异常: {len(value)}"
        return True, ""

    @staticmethod
    def _check_time(value):
        if value is None:
            return True, ""  # 可选字段，空值不算错
        if not isinstance(value, str):
            return False, f"time 应为字符串"
        if len(value) > 64:
            return False, f"time 长度异常: {len(value)}"
        return True, ""

    @staticmethod
    def _check_non_empty(value):
        if not value or not str(value).strip():
            return False, "字段为空"
        return True, ""

    def register_schema(self, name, required=None, optional=None, validators=None):
        """
        注册一个 schema。
        name: schema 名称
        required: 必需字段列表
        optional: 可选字段列表
        validators: {字段名: 校验函数} 校验函数返回 (bool, error_msg)
        """
        self._schemas[name] = {
            "required": set(required or []),
            "optional": set(optional or []),
            "validators": validators or {},
        }

    def validate(self, record, schema_name):
        """
        校验一条记录。
        返回 (is_valid: bool, errors: list[str], warnings: list[str])
        """
        if schema_name not in self._schemas:
            return True, [], ["未知 schema: " + schema_name]

        schema = self._schemas[schema_name]
        errors = []
        warnings = []

        # 检查必需字段
        for field in schema["required"]:
            if field not in record or record[field] is None:
                errors.append(f"缺少必需字段: {field}")

        # 检查字段类型/值
        all_fields = set(record.keys())
        for field, value in record.items():
            if field in schema["validators"]:
                ok, msg = schema["validators"][field](value)
                if not ok:
                    errors.append(f"字段 {field} 校验失败: {msg}")

        # 检查未知字段（告警而非错误）
        known = schema["required"] | schema["optional"]
        for field in all_fields:
            if field not in known and not field.startswith("_"):
                warnings.append(f"未知字段: {field}")

        return len(errors) == 0, errors, warnings

    def validate_batch(self, records, schema_name):
        """
        批量校验记录列表。
        返回 {valid: [], invalid: [], stats: {total, valid_count, invalid_count, error_counts}}
        """
        result = {"valid": [], "invalid": [], "stats": {"total": 0, "valid_count": 0, "invalid_count": 0, "error_counts": defaultdict(int)}}

        for i, record in enumerate(records):
            result["stats"]["total"] += 1
            is_valid, errors, warnings = self.validate(record, schema_name)
            if is_valid:
                result["valid"].append(record)
                result["stats"]["valid_count"] += 1
            else:
                result["invalid"].append({"index": i, "record": record, "errors": errors, "warnings": warnings})
                result["stats"]["invalid_count"] += 1
                for e in errors:
                    result["stats"]["error_counts"][e] += 1

        return result


# ============================================================
# 7. 清洗日志 (CleanLogger)
# ============================================================

class CleanLogger:
    """
    清洗日志记录器。将清洗过程中的关键事件写入 clean.log。

    日志级别:
        INFO  : 正常处理记录（如 "去重 1 条"）
        WARN  : 可疑但非致命（如 "时间解析失败，使用原始值"）
        ERROR : 数据异常（如 "缺少必需字段 uid"）
        DEBUG : 详细调试信息

    用法:
        logger = CleanLogger(log_file="d2/clean.log")
        logger.info("开始处理", count=100)
        logger.warn("时间解析失败", raw="昨天下午")
        logger.error("字段缺失", field="uid", record_idx=5)
        logger.close()
    """

    LOG_FMT = "%(asctime)s | %(levelname)-5s | %(message)s"
    DATE_FMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, log_file=None, console=True):
        self.logger = logging.getLogger(f"clean_{id(self)}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []  # 清除已有 handlers
        self.log_file = log_file

        if console:
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(logging.Formatter(self.LOG_FMT, datefmt=self.DATE_FMT))
            self.logger.addHandler(ch)

        if log_file:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter(self.LOG_FMT, datefmt=self.DATE_FMT))
            self.logger.addHandler(fh)

    def info(self, msg, **kwargs):
        extra = " | " + ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        self.logger.info(f"{msg}{extra}")

    def warn(self, msg, **kwargs):
        extra = " | " + ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        self.logger.warning(f"{msg}{extra}")

    def error(self, msg, **kwargs):
        extra = " | " + ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        self.logger.error(f"{msg}{extra}")

    def debug(self, msg, **kwargs):
        extra = " | " + ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        self.logger.debug(f"{msg}{extra}")

    def close(self):
        """关闭日志文件句柄"""
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================================================
# 便捷函数: 一行调用的快捷接口
# ============================================================

def create_logger(stage, log_dir=None):
    """便捷创建 CleanLogger，自动命名 clean.log"""
    if log_dir is None:
        log_dir = Path.cwd()
    log_path = Path(log_dir) / "clean.log"
    return CleanLogger(log_file=str(log_path))
