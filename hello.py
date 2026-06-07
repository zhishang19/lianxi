#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hello.py - 环境验证脚本
=======================
第一阶段任务 (25 分):
- 验证 Python 环境正常
- 打印学员姓名/学号/指导教师
- 打印当前时间
- 计算 1+2+...+100 = 5050
"""
from datetime import datetime


def main():
    print("=" * 60)
    print("  OS Agent 记忆优化系统 - 环境验证")
    print("=" * 60)

    # 1. Python 版本验证
    import sys
    print(f"Python 版本: {sys.version}")
    print(f"Python 路径: {sys.executable}")

    # 2. 学员信息
    print()
    print("学员信息:")
    print("  姓    名: 苏炯炼")
    print("  学    号: 202504030411")
    print("  指导老师: 林涌东")
    print(f"  当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 3. 计算 1+2+...+100
    total = sum(range(1, 101))
    print()
    print(f"计算 1+2+3+...+100 = {total}")

    # 4. 验证标准库
    print()
    print("标准库验证:")
    modules = ["json", "csv", "re", "datetime", "pathlib", "hashlib"]
    for m in modules:
        try:
            __import__(m)
            print(f"  [OK] {m}")
        except ImportError:
            print(f"  [FAIL] {m}")

    # 5. 验证第三方库
    print()
    print("第三方库验证:")
    try:
        from dateutil import parser
        print(f"  [OK] python-dateutil")
    except ImportError:
        print(f"  [--] python-dateutil (可选)")

    try:
        import ahocorasick
        print(f"  [OK] pyahocorasick (DFA)")
    except ImportError:
        print(f"  [--] pyahocorasick (可选, 用正则回退)")

    print()
    print("=" * 60)
    print("  环境验证完成 - OK")
    print("=" * 60)


if __name__ == "__main__":
    main()
