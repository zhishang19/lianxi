#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
raw 文件夹整理脚本
==================
目标:
  1. 创建合理的目录结构 (lib/, scripts/, outputs/)
  2. 将散落在 raw/ 根目录的文件迁移到正确位置
  3. 清理 __pycache__ 和临时文件
  4. 记录详细迁移日志

分类标准:
  raw/d1~d6/    - 每日任务数据 (保持不动)
  raw/lib/      - 公共库模块 (advanced_cleaning.py)
  raw/scripts/  - 工具脚本 (run_batch_generated.py)
  raw/agent/    - LangGraph 工作流 (保持)
  raw/generated/- 批量生成数据 (保持)
  raw/outputs/  - 跨目录输出汇总
"""

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# ========== 锚点 ==========
RAW_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RAW_DIR.parent

# 新目录
LIB_DIR = RAW_DIR / "lib"
SCRIPTS_DIR = RAW_DIR / "scripts"
OUTPUTS_DIR = RAW_DIR / "outputs"

# 日志文件
LOG_FILE = RAW_DIR / "reorganization_log.json"

# 迁移计划
MIGRATION_PLAN = [
    # (源文件, 目标目录, 分类说明)
    (RAW_DIR / "advanced_cleaning.py", LIB_DIR, "公共清洗库: DFA敏感词/时间流水线/SimHash/脱敏"),
    (RAW_DIR / "run_batch_generated.py", SCRIPTS_DIR, "批量运行脚本: D2-D6 generated/ 数据全量处理"),

    # 项目根目录的 misplaced 文件
    (PROJECT_ROOT / "chat_sessions_clean.csv", RAW_DIR / "d3", "D3 输出文件: 清洗后对话 CSV"),

    # __pycache__ 需要清理 (记录但不迁移)
    (RAW_DIR / "__pycache__", None, "清理: __pycache__ 目录"),
    (RAW_DIR / "agent" / "__pycache__", None, "清理: __pycache__ 目录"),
]

# __pycache__ 清理列表 (递归)
PYCACHE_DIRS = []


def discover_pycache(base: Path):
    """递归查找所有 __pycache__ 目录"""
    for item in base.rglob("__pycache__"):
        if item.is_dir():
            PYCACHE_DIRS.append(item)


def ensure_dirs():
    """创建新目录"""
    new_dirs = []
    for d in [LIB_DIR, SCRIPTS_DIR, OUTPUTS_DIR]:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            new_dirs.append(str(d))
        else:
            new_dirs.append(f"{d} (已存在)")
    return new_dirs


def migrate_file(src: Path, dest_dir: Path, description: str) -> dict:
    """
    迁移单个文件
    返回操作记录
    """
    record = {
        "source": str(src),
        "destination": str(dest_dir / src.name),
        "description": description,
        "size_bytes": 0,
        "status": "",
    }

    if not src.exists():
        record["status"] = "SKIP (文件不存在)"
        return record

    record["size_bytes"] = src.stat().st_size

    dest = dest_dir / src.name

    # 如果目标已存在且内容相同，跳过
    if dest.exists():
        if dest.stat().st_size == record["size_bytes"]:
            record["status"] = "SKIP (目标已存在且大小相同)"
            return record
        else:
            # 备份旧文件
            backup = dest.with_suffix(dest.suffix + ".bak")
            shutil.copy2(str(dest), str(backup))
            record["backup"] = str(backup)

    shutil.move(str(src), str(dest))
    record["status"] = "MOVED"
    return record


def clean_pycache(path: Path) -> dict:
    """清理 __pycache__ 目录"""
    record = {
        "path": str(path),
        "files_deleted": 0,
        "size_freed": 0,
        "status": "",
    }

    if not path.exists():
        record["status"] = "SKIP (目录不存在)"
        return record

    # 统计
    for f in path.rglob("*"):
        if f.is_file():
            record["files_deleted"] += 1
            record["size_freed"] += f.stat().st_size

    shutil.rmtree(str(path))
    record["status"] = "DELETED"
    return record


def generate_directory_tree(base: Path, indent: int = 0, prefix: str = "") -> list:
    """生成目录树"""
    lines = []
    items = sorted(base.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))

    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "

        if item.is_dir():
            # 跳过 __pycache__
            if item.name == "__pycache__":
                continue
            lines.append(f"{prefix}{connector}[DIR] {item.name}/")
            extension = "    " if is_last else "│   "
            lines.extend(generate_directory_tree(item, indent + 1, prefix + extension))
        else:
            # 跳过临时文件
            if item.name.endswith((".pyc", ".bak", ".log")):
                continue
            size = item.stat().st_size
            size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
            lines.append(f"{prefix}{connector}[FILE] {item.name} ({size_str})")

    return lines


def main():
    print("=" * 70)
    print("raw 文件夹整理")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"基准目录: {RAW_DIR}")
    print()

    log = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_dir": str(RAW_DIR),
        "operations": [],
        "summary": {
            "files_moved": 0,
            "files_skipped": 0,
            "pycache_cleaned": 0,
            "bytes_freed": 0,
        }
    }

    # ========== 步骤 1: 创建新目录 ==========
    print("[步骤 1] 创建新目录结构")
    new_dirs = ensure_dirs()
    for d in new_dirs:
        print(f"  [OK] {d}")
    log["operations"].append({
        "step": "create_dirs",
        "directories": new_dirs,
        "status": "OK"
    })
    print()

    # ========== 步骤 2: 文件迁移 ==========
    print("[步骤 2] 文件迁移")
    for src, dest_dir, desc in MIGRATION_PLAN:
        if dest_dir is None:
            # 清理操作
            print(f"  [清理] {src.name} - {desc}")
            continue

        print(f"  迁移: {src.name}")
        print(f"    从: {src}")
        print(f"    到: {dest_dir}")
        print(f"    说明: {desc}")

        record = migrate_file(src, dest_dir, desc)
        log["operations"].append({
            "step": "migrate",
            **record
        })

        if record["status"] == "MOVED":
            print(f"    状态: MOVED ({record['size_bytes']} bytes)")
            log["summary"]["files_moved"] += 1
        else:
            print(f"    状态: {record['status']}")
            log["summary"]["files_skipped"] += 1
        print()

    # ========== 步骤 3: 清理 __pycache__ ==========
    print("[步骤 3] 清理 __pycache__ 和临时文件")
    discover_pycache(RAW_DIR)

    for pyc_dir in PYCACHE_DIRS:
        print(f"  清理: {pyc_dir}")
        record = clean_pycache(pyc_dir)
        log["operations"].append({
            "step": "clean_pycache",
            **record
        })
        if record["status"] == "DELETED":
            print(f"    删除 {record['files_deleted']} 个文件, 释放 {record['size_freed']} bytes")
            log["summary"]["pycache_cleaned"] += 1
            log["summary"]["bytes_freed"] += record["size_freed"]
        else:
            print(f"    状态: {record['status']}")
    print()

    # ========== 步骤 4: 验证 ==========
    print("[步骤 4] 验证迁移结果")
    all_ok = True

    # 验证 moved files 在新位置存在
    for op in log["operations"]:
        if op.get("step") == "migrate" and op.get("status") == "MOVED":
            dest = Path(op["destination"])
            if dest.exists():
                print(f"  [OK] {dest.name}")
            else:
                print(f"  [ERROR] {dest.name} 不存在!")
                all_ok = False

    # 验证关键文件还在
    critical_files = [
        RAW_DIR / "d2" / "merge_day2.py",
        RAW_DIR / "d3" / "clean_basic.py",
        RAW_DIR / "d4" / "clean_multi_source.py",
        RAW_DIR / "d5" / "merge_memories.py",
        RAW_DIR / "d6" / "eval_e2e.py",
        RAW_DIR / "agent" / "memory_workflow.py",
    ]
    for cf in critical_files:
        if cf.exists():
            print(f"  [OK] {cf.relative_to(RAW_DIR)}")
        else:
            print(f"  [MISSING] {cf.relative_to(RAW_DIR)}")
            all_ok = False

    # 验证 __pycache__ 被清理
    pycache_remaining = list(RAW_DIR.rglob("__pycache__"))
    if pycache_remaining:
        print(f"  [WARN] 仍有 {len(pycache_remaining)} 个 __pycache__ 目录")
    else:
        print(f"  [OK] 所有 __pycache__ 已清理")
    print()

    # ========== 步骤 5: 生成目录树 ==========
    print("[步骤 5] 生成整理后目录树")
    tree_lines = generate_directory_tree(RAW_DIR)
    tree_text = "raw/\n" + "\n".join(tree_lines)
    print(tree_text)
    print()

    # ========== 步骤 6: 保存日志 ==========
    log["summary"]["all_ok"] = all_ok
    log["directory_tree"] = tree_text

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print(f"[OK] 迁移日志: {LOG_FILE}")
    print()

    # ========== 总结 ==========
    print("=" * 70)
    print("整理完成")
    print("=" * 70)
    print(f"  文件迁移: {log['summary']['files_moved']}")
    print(f"  跳过文件: {log['summary']['files_skipped']}")
    print(f"  清理 __pycache__: {log['summary']['pycache_cleaned']} 个")
    print(f"  释放空间: {log['summary']['bytes_freed']} bytes")
    print(f"  验证状态: {'全部通过' if all_ok else '有错误'}")
    print()
    print("新目录结构:")
    print(f"  raw/lib/          - 公共清洗库 (advanced_cleaning.py)")
    print(f"  raw/scripts/      - 工具脚本 (run_batch_generated.py)")
    print(f"  raw/outputs/      - 跨目录输出汇总")
    print(f"  raw/d1~d6/        - 每日任务数据 (保持不变)")
    print(f"  raw/agent/        - LangGraph 工作流 (保持不变)")
    print(f"  raw/generated/    - 批量生成数据 (保持不变)")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
