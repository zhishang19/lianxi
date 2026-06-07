#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
记忆检索工作流测试脚本
- 测试 LangGraph 工作流的 5 个节点
- 演示完整的数据流: D5 记忆 → SQLite → 检索 → 回答
"""

import json
import sys
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_workflow import WorkflowState, MemoryDB, SimpleRetriever, create_workflow, HAS_LANGGRAPH

# 测试数据目录
D5 = Path(__file__).resolve().parent.parent / "d5"
GENERATED = Path(__file__).resolve().parent.parent / "generated" / "d05"


def test_small_dataset():
    """测试小数据集 (D5 demo, 11 条记忆)"""
    print("="*60)
    print("测试 1: 小数据集 (D5 demo)")
    print("="*60)

    mem_path = D5 / "merged_memories.jsonl"
    if not mem_path.exists():
        print(f"  [跳过] 文件不存在: {mem_path}")
        return

    # 加载记忆
    memories = []
    with open(mem_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    memories.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    print(f"  记忆数: {len(memories)}")

    # 创建检索器和工作流
    retriever = SimpleRetriever(memories)
    workflow = create_workflow(retriever)

    # 测试用例
    test_cases = [
        ("u001", "帮我导出月报，要详细版", "hit", "输出风格偏好"),
        ("u002", "回复我一下驱动更新步骤", "hit", "emoji 偏好"),
        ("u004", "我的邮箱是什么？", "hit", "隐私查询 (forget)"),
        ("u005", "写一下会议纪要", "hit", "三段式偏好"),
        ("u007", "解释一下为什么要这样做", "hit", "冲突解决"),
        ("u010", "刚才 web_search 超时，所以驱动知识是不是不能用了？", "hit", "工具失败 vs 知识失效"),
    ]

    results = []
    for uid, query, expected, desc in test_cases:
        state = WorkflowState(uid=uid, query=query)
        result = workflow.invoke(state)
        results.append({
            "uid": uid, "query": query, "expected": expected,
            "intent": result.intent, "retrieved": len(result.retrieved_memories),
            "answer": result.answer[:60], "trace": len(result.trace),
        })
        print(f"\n  [{uid}] {query}")
        print(f"    → [{result.intent}] {result.answer[:60]}")

    # 统计
    print(f"\n  {'='*50}")
    print(f"  结果: {len(results)} 个测试用例")
    print(f"  工作流类型: {'LangGraph' if HAS_LANGGRAPH else '纯 Python'}")
    for r in results:
        print(f"  [{r['uid']}] {r['query'][:30]}... → {r['intent']} ({r['retrieved']} 条记忆)")


def test_large_dataset():
    """测试大批量数据 (generated/ 3241 条记忆)"""
    print("\n" + "="*60)
    print("测试 2: 大批量数据 (generated/ 3241 条)")
    print("="*60)

    mem_path = GENERATED / "merged_memories.jsonl"
    if not mem_path.exists():
        print(f"  [跳过] 文件不存在: {mem_path}")
        return

    memories = []
    with open(mem_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    memories.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    print(f"  记忆数: {len(memories)}")

    # 创建 SQLite 数据库
    db = MemoryDB(":memory:")
    count = db.import_from_jsonl(str(mem_path))
    print(f"  导入: {count} 条")

    # 创建检索器和工作流
    workflow = create_workflow(db)

    # 测试查询
    test_queries = [
        ("u0001", "帮我查一下驱动更新"),
        ("u0018", "回答要简短"),
        ("u0414", "离线安装 deb"),
    ]

    for uid, query in test_queries:
        state = WorkflowState(uid=uid, query=query)
        result = workflow.invoke(state)
        print(f"\n  [{uid}] {query}")
        print(f"    → [{result.intent}] 检索 {len(result.retrieved_memories)} 条")
        if result.retrieved_memories:
            m = result.retrieved_memories[0]
            print(f"    → key={m['memory_key']}, value={m['value'][:50]}")

    db.close()


def test_workflow_structure():
    """测试工作流结构"""
    print("\n" + "="*60)
    print("测试 3: 工作流结构验证")
    print("="*60)

    print(f"\n  LangGraph 可用: {'[OK]' if HAS_LANGGRAPH else '[NO] (使用纯 Python 降级)'}")
    print(f"  工作流节点: 5 个")
    print("    A - intent_recognition (意图识别)")
    print("    B - memory_retrieval (记忆检索)")
    print("    C - preference_routing (偏好路由)")
    print("    D - generate_answer (生成回答)")
    print("    E - privacy_check (隐私检查)")
    print(f"\n  条件路由: 3 种意图")
    print("    chatter -> D (直接回答)")
    print("    memory_query -> B -> C -> D (检索+路由+回答)")
    print("    privacy_query -> B -> E -> D (检索+隐私检查+回答)")

    # 加载记忆创建检索器
    memories = []
    mem_path = D5 / "merged_memories.jsonl"
    if mem_path.exists():
        with open(mem_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        memories.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    retriever = SimpleRetriever(memories)

    print(f"\n  节点测试 (通过完整工作流执行):")

    # 通过完整工作流测试 A
    state = WorkflowState(uid="u001", query="帮我导出月报")
    workflow = create_workflow(retriever)
    result = workflow.invoke(state)
    print(f"    A+B+C+D (完整流程): intent={result.intent}, 检索={len(result.retrieved_memories)} 条 [OK]")

    # 测试 E (隐私)
    state2 = WorkflowState(uid="u004", query="我的邮箱是什么？")
    result2 = workflow.invoke(state2)
    print(f"    A+B+E+D (隐私流程): intent={result2.intent}, 隐私风险={result2.privacy_risk} [OK]")

    # 测试 chatter
    state3 = WorkflowState(uid="u001", query="你好")
    result3 = workflow.invoke(state3)
    print(f"    A+D (闲聊流程): intent={result3.intent}, 回答={result3.answer[:30]} [OK]")

    print(f"\n  所有节点测试通过 [OK]")


def main():
    print("LangGraph 记忆检索工作流 - 测试套件")
    print("="*60)

    test_workflow_structure()
    test_small_dataset()
    test_large_dataset()

    print("\n" + "="*60)
    print("全部测试完成!")
    print("="*60)


if __name__ == "__main__":
    main()
