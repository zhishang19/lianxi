#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
organize.py - 项目整理脚本
==========================
清理临时文件 + 重新组织目录结构
运行: python organize.py
"""
import shutil
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(r"d:\藏数据")
LOG_FILE = ROOT / "organize_log.json"


def log_action(actions, action, src, dst=None, status="OK", note=""):
    actions.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "src": str(src.relative_to(ROOT)) if src else None,
        "dst": str(dst.relative_to(ROOT)) if dst else None,
        "status": status,
        "note": note,
    })


def main():
    actions = []

    # 1. 删除临时文件
    print("=" * 60)
    print("  项目整理 - 清理临时文件")
    print("=" * 60)

    temp_files = [
        ROOT / "push_out.log",         # git push 输出
        ROOT / "push_err.log",         # git push 错误
        ROOT / "demo_branch_change.txt",  # 分支合并演示残留
    ]
    for f in temp_files:
        if f.exists():
            f.unlink()
            log_action(actions, "DELETE", f, note="临时日志/演示文件")
            print(f"  [DEL] {f.name}")

    # 2. 清理 __pycache__
    for cache_dir in ROOT.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)
            log_action(actions, "DELETE_DIR", cache_dir, note="Python 编译缓存")
            print(f"  [DEL] {cache_dir.relative_to(ROOT)}/")

    # 3. 删除 .db 临时文件 (会在重新运行时重新生成)
    for db_file in (ROOT / "raw" / "agent").glob("*.db"):
        if db_file.name not in ("memory.db",):  # 保留主数据库
            db_file.unlink()
            log_action(actions, "DELETE", db_file, note="临时数据库")
            print(f"  [DEL] {db_file.relative_to(ROOT)}")

    # 4. 删除根目录的 demo 输出 (已经在 raw/ 下有副本)
    # 保留这些作为 D2/D3 的官方输出, 不删除

    # 5. 确认目录结构
    print("\n" + "=" * 60)
    print("  当前项目结构")
    print("=" * 60)

    expected = {
        "README.md": "项目说明",
        "hello.py": "环境验证",
        "requirements.txt": "依赖清单",
        "merged.jsonl": "D2 输出 (合并去噪后)",
        "chat_sessions_clean.csv": "D3 输出 (基础清洗后)",
        "docs/": "文档",
        "raw/": "原始数据 + 清洗",
        "raw/lib/": "公共库 (advanced_cleaning)",
        "raw/scripts/": "工具脚本",
        "raw/d1/ ~ d6/": "D1-D6 各阶段",
        "raw/agent/": "LangGraph + Agent + DB",
        "raw/generated/": "批量生成数据",
        "camp-langchain4j-starter/": "Java 模板 (阶段 3)",
    }

    for name, desc in expected.items():
        path = ROOT / name
        if path.exists():
            print(f"  [OK]   {name:35s}  {desc}")
        else:
            print(f"  [--]   {name:35s}  {desc} (不存在)")

    # 写日志
    LOG_FILE.write_text(
        json.dumps({"actions": actions}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  整理日志: {LOG_FILE.name}")
    print(f"  操作数:   {len(actions)}")


if __name__ == "__main__":
    main()
