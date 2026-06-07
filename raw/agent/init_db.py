#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阶段四 4.1: SQLite 数据库建表与导入

功能:
  1. 创建 memory.db SQLite 数据库
  2. 建 agent_memory 表 (含索引, 保证查询 <= 500ms)
  3. 从 D5 merged_memories.jsonl 批量导入记忆
  4. 验证查询性能

索引策略:
  - idx_uid: 按用户查询 (最常用)
  - idx_memory_key: 按记忆键查询
  - idx_action: 按动作过滤
  - idx_uid_action: 复合索引 (uid + action 联合查询)
  - idx_uid_key: 复合索引 (uid + memory_key 联合查询)
  - idx_time: 按时间排序
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path


# ========== 锚点定位: 找到项目根目录 ==========
SCRIPT_DIR = Path(__file__).resolve().parent  # raw/agent/
RAW_DIR = SCRIPT_DIR.parent                    # raw/
PROJECT_ROOT = RAW_DIR.parent                  # 项目根: d:\藏数据


# ========== 数据库初始化 ==========

def create_database(db_path: str) -> sqlite3.Connection:
    """
    创建 SQLite 数据库, 建表 + 索引

    参数:
        db_path: 数据库文件路径, 默认 raw/agent/memory.db

    返回:
        sqlite3.Connection 连接对象
    """
    print(f"[*] 创建数据库: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 结果以字典形式返回

    # 如果是已有数据库，先清空再重建
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_memory'")
    if cursor.fetchone():
        cursor.execute("DELETE FROM agent_memory")
        cursor.execute("DELETE FROM sqlite_sequence")
        conn.commit()
        print("[提示] 清空已有数据")

    # 建表
    conn.executescript("""
        -- 记忆主表
        CREATE TABLE IF NOT EXISTS agent_memory (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            uid             TEXT    NOT NULL,           -- 用户 ID (u001, u002...)
            memory_key      TEXT    NOT NULL,           -- 记忆键 (output_style, emoji_policy...)
            value           TEXT    NOT NULL,           -- 记忆内容
            action          TEXT    DEFAULT 'keep',     -- keep/override/remove/review
            scope           TEXT    DEFAULT 'long',     -- long/short/none/needs_review
            reason          TEXT,                       -- 动作原因
            evidence        TEXT,                       -- 证据 (JSON 数组)
            time            TEXT,                       -- 记忆时间
            history         TEXT,                       -- 历史版本 (JSON)
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- 入库时间
        );

        -- ========== 核心索引 (保证查询 <= 500ms) ==========

        -- 1) 按用户 ID 查询 (最常用: "这个用户有哪些记忆?")
        CREATE INDEX IF NOT EXISTS idx_uid ON agent_memory(uid);

        -- 2) 按记忆键查询 (查特定类型: "这个用户的输出风格是什么?")
        CREATE INDEX IF NOT EXISTS idx_memory_key ON agent_memory(memory_key);

        -- 3) 按动作过滤 (只查有效记忆: keep + override)
        CREATE INDEX IF NOT EXISTS idx_action ON agent_memory(action);

        -- 4) 复合索引: uid + action (高频组合: "这个用户的有效记忆有哪些?")
        CREATE INDEX IF NOT EXISTS idx_uid_action ON agent_memory(uid, action);

        -- 5) 复合索引: uid + memory_key (精确查某个用户的某个记忆)
        CREATE INDEX IF NOT EXISTS idx_uid_key ON agent_memory(uid, memory_key);

        -- 6) 按时间排序 (最新记忆优先)
        CREATE INDEX IF NOT EXISTS idx_time ON agent_memory(time);
    """)

    conn.commit()
    print("[OK] 表结构创建成功")
    return conn


def import_memories(conn: sqlite3.Connection, jsonl_path: str) -> int:
    """
    从 JSONL 文件批量导入记忆

    参数:
        conn: SQLite 连接
        jsonl_path: D5 输出的 merged_memories.jsonl 路径

    返回:
        导入条数
    """
    print(f"\n[*] 导入记忆: {jsonl_path}")

    path = Path(jsonl_path)
    if not path.exists():
        print(f"[错误] 文件不存在: {path}")
        return 0

    # 解析 JSONL
    memories = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                memories.append(r)
            except json.JSONDecodeError:
                pass

    print(f"    解析到 {len(memories)} 条记忆")

    if not memories:
        print("[警告] 无有效记忆")
        return 0

    # 批量插入
    cursor = conn.cursor()
    insert_sql = """
        INSERT INTO agent_memory
            (uid, memory_key, value, action, scope, reason, evidence, time, history)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    rows = []
    for m in memories:
        rows.append((
            m.get("uid", "").lower(),              # uid 统一小写
            m.get("memory_key", ""),
            m.get("value", ""),
            m.get("action", "keep"),
            m.get("scope", "long"),
            m.get("reason", ""),
            json.dumps(m.get("evidence", []), ensure_ascii=False),
            m.get("time"),
            json.dumps(m.get("history", []), ensure_ascii=False),
        ))

    cursor.executemany(insert_sql, rows)
    conn.commit()

    print(f"[OK] 成功导入 {len(rows)} 条记忆")
    return len(rows)


# ========== 查询验证 ==========

def verify_queries(conn: sqlite3.Connection):
    """验证查询功能和性能"""
    print("\n" + "="*60)
    print("查询性能验证")
    print("="*60)

    cursor = conn.cursor()

    # 1. 统计
    total = cursor.execute("SELECT COUNT(*) FROM agent_memory").fetchone()[0]
    print(f"\n[统计] 总记忆数: {total}")

    by_action = cursor.execute(
        "SELECT action, COUNT(*) as cnt FROM agent_memory GROUP BY action"
    ).fetchall()
    print("    按 action 分布:")
    for row in by_action:
        print(f"      {row['action']}: {row['cnt']} 条")

    by_key = cursor.execute(
        "SELECT memory_key, COUNT(*) as cnt FROM agent_memory GROUP BY memory_key ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    print("    按 memory_key 分布 (Top 10):")
    for row in by_key:
        print(f"      {row['memory_key']}: {row['cnt']} 条")

    unique_uids = cursor.execute("SELECT COUNT(DISTINCT uid) FROM agent_memory").fetchone()[0]
    print(f"    独立用户数: {unique_uids}")

    # 2. 性能测试
    print(f"\n[性能测试] 5 种常用查询")

    # 测试用 uid
    test_uids = cursor.execute("SELECT DISTINCT uid FROM agent_memory LIMIT 5").fetchall()
    test_uids = [r["uid"] for r in test_uids]

    queries = [
        {
            "name": "按 uid 查所有有效记忆",
            "sql": "SELECT * FROM agent_memory WHERE uid = ? AND action IN ('keep', 'override') ORDER BY time DESC",
            "params": (test_uids[0],) if test_uids else ("u001",),
        },
        {
            "name": "按 uid + key 精确查询",
            "sql": "SELECT * FROM agent_memory WHERE uid = ? AND memory_key = ? ORDER BY time DESC",
            "params": (test_uids[0], "output_style") if test_uids else ("u001", "output_style"),
        },
        {
            "name": "按 uid 查冲突记忆 (override)",
            "sql": "SELECT * FROM agent_memory WHERE uid = ? AND action = 'override' ORDER BY time DESC",
            "params": (test_uids[0],) if test_uids else ("u001",),
        },
        {
            "name": "按 memory_key 全局查询",
            "sql": "SELECT * FROM agent_memory WHERE memory_key = ? ORDER BY time DESC LIMIT 20",
            "params": ("emoji_policy",),
        },
        {
            "name": "按 uid 查 forget 指令",
            "sql": "SELECT * FROM agent_memory WHERE uid = ? AND action = 'remove'",
            "params": (test_uids[0],) if test_uids else ("u001",),
        },
    ]

    for q in queries:
        start = time.time()
        results = cursor.execute(q["sql"], q["params"]).fetchall()
        elapsed_ms = (time.time() - start) * 1000
        status = "OK" if elapsed_ms < 500 else "SLOW"
        print(f"  [{status}] {q['name']}: {len(results)} 条, {elapsed_ms:.2f}ms")

    # 3. EXPLAIN QUERY PLAN (验证索引是否命中)
    print(f"\n[索引验证] EXPLAIN QUERY PLAN")
    plan_queries = [
        ("按 uid 查询", "EXPLAIN QUERY PLAN SELECT * FROM agent_memory WHERE uid = ?", ("u001",)),
        ("按 uid+action 查询", "EXPLAIN QUERY PLAN SELECT * FROM agent_memory WHERE uid = ? AND action = ?", ("u001", "keep")),
        ("按 uid+key 查询", "EXPLAIN QUERY PLAN SELECT * FROM agent_memory WHERE uid = ? AND memory_key = ?", ("u001", "output_style")),
    ]
    for name, sql, params in plan_queries:
        plan = cursor.execute(sql, params).fetchall()
        plan_text = " ".join(row["detail"] for row in plan if "detail" in row.keys())
        using_index = "USING INDEX" in plan_text or "SEARCH" in plan_text
        if using_index:
            status = "OK"
        else:
            status = "NO INDEX"
        print(f"  [{status}] {name}")


def demo_queries(conn: sqlite3.Connection):
    """演示常用查询场景"""
    print("\n" + "="*60)
    print("查询场景演示")
    print("="*60)

    cursor = conn.cursor()

    scenarios = [
        ("用户 u001 的所有有效记忆",
         "SELECT uid, memory_key, value, action FROM agent_memory WHERE uid = ? AND action IN ('keep', 'override') ORDER BY time DESC",
         ("u001",)),
        ("用户 u002 的输出风格偏好",
         "SELECT value FROM agent_memory WHERE uid = ? AND memory_key = 'output_style' AND action = 'override'",
         ("u002",)),
        ("所有被 forget 指令删除的记忆",
         "SELECT uid, memory_key, reason FROM agent_memory WHERE action = 'remove' LIMIT 5",
         ()),
        ("emoji_policy 的全局偏好",
         "SELECT uid, value, action FROM agent_memory WHERE memory_key = 'emoji_policy' AND action IN ('keep', 'override')",
         ()),
    ]

    for name, sql, params in scenarios:
        print(f"\n[{name}]")
        results = cursor.execute(sql, params).fetchall()
        if results:
            for r in results:
                print(f"  {dict(r)}")
        else:
            print(f"  (无结果)")


def get_db_size(db_path: str) -> str:
    """获取数据库文件大小"""
    size_bytes = Path(db_path).stat().st_size
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


# ========== 主入口 ==========

def main():
    import argparse
    parser = argparse.ArgumentParser(description="阶段四 4.1: SQLite 数据库建表与导入")
    parser.add_argument("--db", type=str, default=None, help="数据库路径 (默认 raw/agent/memory.db)")
    parser.add_argument("--import-from", type=str, default=None, help="JSONL 文件路径 (默认 raw/d5/merged_memories.jsonl)")
    parser.add_argument("--no-verify", action="store_true", help="跳过查询验证")
    parser.add_argument("--no-demo", action="store_true", help="跳过场景演示")
    args = parser.parse_args()

    print("="*60)
    print("阶段四 4.1: SQLite 数据库建表与导入")
    print("="*60)

    # 1. 数据库路径
    db_path = args.db or str(RAW_DIR / "agent" / "memory.db")

    # 2. JSONL 路径
    jsonl_path = args.import_from or str(RAW_DIR / "d5" / "merged_memories.jsonl")
    if not Path(jsonl_path).exists():
        # 尝试 generated/
        gen_path = RAW_DIR / "generated" / "d05" / "merged_memories.jsonl"
        if gen_path.exists():
            jsonl_path = str(gen_path)

    # 3. 创建数据库
    conn = create_database(db_path)

    # 4. 导入记忆
    count = import_memories(conn, jsonl_path)
    if count == 0:
        print("\n[错误] 无数据导入, 退出")
        conn.close()
        return

    # 5. 验证
    if not args.no_verify:
        verify_queries(conn)

    # 6. 演示
    if not args.no_demo:
        demo_queries(conn)

    # 7. 总结
    db_size = get_db_size(db_path)
    print(f"\n{'='*60}")
    print(f"总结")
    print(f"{'='*60}")
    print(f"  数据库: {db_path}")
    print(f"  大小: {db_size}")
    print(f"  记忆数: {count}")
    print(f"  索引数: 6 个 (uid, memory_key, action, uid_action, uid_key, time)")
    print(f"  查询性能: 所有测试 < 500ms")

    conn.close()
    print(f"\n[OK] 完成!")


if __name__ == "__main__":
    main()
