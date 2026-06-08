#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_all.py - 一键运行所有 D2-D6 + Agent 验证脚本
====================================================
训练营一键验证: 跑通整个数据清洗 + Agent 流水线

运行: python run_all.py [--skip d5]
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


def run(name, script, cwd=None, args=None):
    """运行一个脚本, 流式输出"""
    cmd = [PYTHON, str(script)]
    if args:
        cmd.extend(args)
    cmd_str = " ".join(cmd)
    print(f"\n{'=' * 60}")
    print(f"  [{name}] {script.name}")
    print(f"  CMD: {cmd_str}")
    print("=" * 60)
    t0 = time.time()
    # 强制子进程用 UTF-8 输出
    import os
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        # 流式输出 (不 capture), 让用户实时看到
        result = subprocess.run(
            cmd, cwd=str(cwd or ROOT),
            encoding="utf-8", errors="replace",
            timeout=120, env=env,
        )
        dt = time.time() - t0
        status = "PASS" if result.returncode == 0 else "FAIL"
        return {"name": name, "status": status, "elapsed": round(dt, 2), "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "TIMEOUT", "elapsed": 120, "returncode": -1}
    except Exception as e:
        return {"name": name, "status": "ERROR", "elapsed": 0, "returncode": -1, "err": str(e)}


def main():
    results = []
    skip = set(sys.argv[1:]) if len(sys.argv) > 1 else set()

    tasks = [
        ("D2 合并去噪",   "raw/d2/merge_day2.py",        ROOT),
        ("D3 基础清洗",   "raw/d3/clean_basic.py",       ROOT),
        ("D4 多源清洗",   "raw/d4/clean_multi_source.py", ROOT),
        ("D5 记忆合并",   "raw/d5/merge_memories.py",    ROOT),
        ("D6 端到端评测", "raw/d6/eval_e2e.py",          ROOT),
        ("Agent 2节点QA", "raw/agent/knowledge_qa_workflow.py", ROOT),
        ("Mini Agent",    "raw/agent/mini_agent.py",     ROOT),
        ("Memory 工作流", "raw/agent/test_workflow.py",  ROOT),
    ]

    for name, script, cwd in tasks:
        # BUG-10 修复: 默认全跑, 传 --skip 时跳过含关键词的任务 (而不是"仅含")
        if skip and any(s in name for s in skip):
            print(f"\n[SKIP] {name}  (匹配 skip 列表: {skip})")
            results.append({"name": name, "status": "SKIP"})
            continue
        script_path = cwd / script
        if not script_path.exists():
            print(f"\n[WARN] {script} 不存在, 跳过")
            results.append({"name": name, "status": "SKIP"})
            continue
        results.append(run(name, script_path, cwd))

    # 汇总
    print("\n\n" + "=" * 60)
    print("  运行汇总")
    print("=" * 60)
    print(f"  {'任务':<20s} {'状态':<10s} {'耗时':<10s}")
    print("  " + "-" * 50)
    pass_count = 0
    for r in results:
        icon_map = {"PASS": "[OK]", "FAIL": "[X]", "TIMEOUT": "[T]", "SKIP": "[-]", "ERROR": "[!]"}
        status_icon = icon_map.get(r["status"], "[?]")
        print(f"  {r['name']:<20s} {status_icon} {r['status']:<8s} {r.get('elapsed', 0):>6.1f}s")
        if r["status"] == "PASS":
            pass_count += 1
    total = len(results)
    print(f"\n  通过: {pass_count}/{total} = {pass_count * 100 // max(total, 1)}%")
    return 0 if pass_count == total else 1


if __name__ == "__main__":
    # 强制 UTF-8 输出, 解决 Windows GBK 编码问题
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
