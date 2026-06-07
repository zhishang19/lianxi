#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
knowledge_qa_workflow.py - 2 节点 LangGraph 工作流
====================================================
训练营任务: LangGraph (35 分) - 搭 2-3 节点工作流

业务场景: 麒麟 OS 运维知识问答
  - 读 D2 洗好的 raw/d4/knowledge.json (含 IT 运维问答对)
  - Node 1: classify_intent - 判断问题是否与 IT 运维相关
  - Node 2: retrieve_answer - 从知识库检索并生成答案
  - 旁路: chitchat - 不相关问题直接返回 "我不知道"

输入: 用户问题 (str)
输出: 答案 + 引用来源 (dict)

工作流图:
    START
      │
      ▼
  ┌────────────────┐
  │ classify_intent │
  └────────┬───────┘
           │
     ┌─────┴──────┐
     │             │
  relevant    irrelevant
     │             │
     ▼             ▼
  ┌────────┐   ┌────────┐
  │retrieve│   │chitchat│
  └───┬────┘   └───┬────┘
      │             │
      └──────┬──────┘
             ▼
            END
"""

import json
import re
import sys
from pathlib import Path
from typing import TypedDict, Literal

# 尝试导入 LangGraph, 缺失则用 PurePython 降级
try:
    from langgraph.graph import StateGraph, START, END
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False


# ============================================================
# 1. 知识库加载 (来自 D2/D4 清洗的输出)
# ============================================================

def load_knowledge_base(path: str = None) -> list:
    """
    加载 D2 洗好的 knowledge.json
    失败时回退到内置的 3 条 demo 数据
    """
    if path is None:
        # 默认从项目根的 raw/d4/knowledge.json 读
        candidates = [
            Path(__file__).resolve().parent.parent / "d4" / "knowledge.json",
            Path("d:/藏数据/raw/d4/knowledge.json"),
            Path("raw/d4/knowledge.json"),
        ]
        for p in candidates:
            if p.exists():
                path = str(p)
                break

    if path and Path(path).exists():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            print(f"[KB] 加载了 {len(data)} 条知识 (来源: {path})")
            return data
        except Exception as e:
            print(f"[KB] 加载失败: {e}, 使用 demo 数据")

    # 内置 demo 数据 (兜底)
    return [
        {
            "title": "麒麟系统安装 .deb 软件包",
            "tags": ["麒麟", "安装", "deb"],
            "steps": [
                "打开终端, cd 到 deb 所在目录",
                "执行 sudo dpkg -i xxx.deb",
                "如有依赖问题, 执行 sudo apt install -f",
            ],
            "notes": ["路径有空格要加引号"]
        },
        {
            "title": "麒麟系统配置打印机",
            "tags": ["麒麟", "打印机"],
            "steps": [
                "系统设置 → 打印机 → 添加",
                "选择 IPP 或 SMB 协议",
                "输入打印机 IP, 点击查找"
            ],
            "notes": []
        },
        {
            "title": "内网 DNS 解析失败排查",
            "tags": ["网络", "DNS", "排查"],
            "steps": [
                "ping 8.8.8.8 验证网络连通性",
                "cat /etc/resolv.conf 查看 DNS 服务器",
                "nslookup baidu.com 测试解析",
                "如失败, 切换到 223.5.5.5 或 114.114.114.114"
            ],
            "notes": ["内网 DNS 经常被劫持"]
        }
    ]


# ============================================================
# 2. 意图分类 (Node 1)
# ============================================================

# 训练营关心的"是否与 IT 运维相关"的关键词
IT_KEYWORDS = [
    "麒麟", "安装", "配置", "网络", "系统", "驱动", "打印", "扫描",
    "dpkg", "apt", "yum", "rpm", ".deb", ".rpm",
    "DNS", "IP", "端口", "路由", "网关", "防火墙",
    "服务", "进程", "日志", "性能", "内存", "CPU",
    "软件", "硬件", "更新", "升级", "补丁", "病毒", "查杀",
    "权限", "用户", "组", "密码", "登录", "ssh",
    "安装包", "依赖", "环境", "变量", "路径",
]

CHITCHAT_KEYWORDS = [
    "你好", "hello", "hi", "天气", "在吗", "你是谁",
    "讲个笑话", "唱歌", "聊天", "陪我", "无聊",
]


def classify_intent(question: str) -> Literal["relevant", "irrelevant"]:
    """
    Node 1: 意图分类
    规则匹配 (训练营不要求 LLM, 用关键词足够):
      - 命中 IT 关键词 → relevant
      - 命中闲聊关键词 → irrelevant
      - 都不命中 → relevant (默认尝试回答)
    """
    q = question.lower()
    # 闲聊优先
    for kw in CHITCHAT_KEYWORDS:
        if kw in q:
            return "irrelevant"
    # IT 关键词
    for kw in IT_KEYWORDS:
        if kw.lower() in q:
            return "relevant"
    # 默认走相关
    return "relevant"


# ============================================================
# 3. 检索与答案生成 (Node 2)
# ============================================================

def _score_match(question: str, entry: dict) -> float:
    """
    计算问题与知识条目的匹配分
    评分维度:
      - title 完全匹配: +10
      - title 包含查询词: +5
      - tag 命中: +3/个
      - steps/notes 命中: +1/个 (最多 +5)
    """
    score = 0.0
    q = question.lower()
    title = entry.get("title", "").lower()

    if title == q:
        score += 10
    for token in re.split(r"\s+", q):
        token = token.strip()
        if len(token) >= 2 and token in title:
            score += 5

    for tag in entry.get("tags", []):
        if str(tag).lower() in q:
            score += 3

    body_text = " ".join(entry.get("steps", [])) + " " + " ".join(entry.get("notes", []))
    for token in re.split(r"\s+", q):
        if len(token) >= 2 and token in body_text.lower():
            score += 1

    return score


def retrieve_answer(question: str, knowledge: list) -> dict:
    """
    Node 2: 检索知识库
    策略: 评分排序, 取 Top 1
    训练营提示: 训练营数据小 (3-50 条), 全量遍历够用
    """
    scored = [(_score_match(question, e), e) for e in knowledge]
    scored.sort(key=lambda x: -x[0])
    best_score, best = scored[0] if scored else (0, None)

    if not best or best_score < 1:
        return {
            "answer": "抱歉, 我的知识库里没找到相关答案。你可以换个问法, 或者去麒麟官方论坛提问。",
            "source": None,
            "score": 0.0,
            "candidates": [(s, e.get("title")) for s, e in scored[:3]],
        }

    # 拼接答案
    answer_parts = [f"【{best['title']}】"]
    for i, step in enumerate(best.get("steps", []), 1):
        answer_parts.append(f"{i}. {step}")
    for note in best.get("notes", []):
        answer_parts.append(f"💡 {note}")
    answer_parts.append(f"\n(来源: 知识库条目, 匹配分 {best_score:.1f})")

    return {
        "answer": "\n".join(answer_parts),
        "source": best.get("title"),
        "score": best_score,
        "tags": best.get("tags", []),
    }


# ============================================================
# 4. 闲聊节点 (旁路)
# ============================================================

def chitchat_response(question: str) -> dict:
    """闲聊兜底"""
    q = question.lower()
    if "你好" in q or "hello" in q or "hi" in q:
        msg = "你好! 我是麒麟 OS 运维知识助手, 可以问我关于系统配置、软件安装、网络故障等问题。"
    elif "你是谁" in q:
        msg = "我是训练营 LangGraph 阶段做的小助手, 专攻 IT 运维问答。"
    else:
        msg = "不好意思, 我是运维知识助手, 这类问题我不太擅长。可以问我 IT 相关的问题试试?"
    return {"answer": msg, "source": "chitchat", "score": 0.0}


# ============================================================
# 5. LangGraph 工作流
# ============================================================

class QAState(TypedDict):
    """工作流状态"""
    question: str
    intent: str
    answer: str
    source: str
    score: float
    trace: list


def build_langgraph_workflow(knowledge: list):
    """构建 LangGraph 工作流 (有 langgraph 时)"""
    # 节点函数
    def node_classify(state: QAState) -> QAState:
        intent = classify_intent(state["question"])
        return {
            **state,
            "intent": intent,
            "trace": state.get("trace", []) + [f"[classify] -> {intent}"],
        }

    def node_retrieve(state: QAState) -> QAState:
        result = retrieve_answer(state["question"], knowledge)
        return {
            **state,
            "answer": result["answer"],
            "source": result.get("source", ""),
            "score": result.get("score", 0.0),
            "trace": state.get("trace", []) + [f"[retrieve] -> source={result.get('source')}"],
        }

    def node_chitchat(state: QAState) -> QAState:
        result = chitchat_response(state["question"])
        return {
            **state,
            "answer": result["answer"],
            "source": result.get("source", "chitchat"),
            "score": 0.0,
            "trace": state.get("trace", []) + ["[chitchat]"],
        }

    # 路由函数
    def route_after_classify(state: QAState) -> str:
        return "retrieve" if state["intent"] == "relevant" else "chitchat"

    # 构建图
    graph = StateGraph(QAState)
    graph.add_node("classify", node_classify)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("chitchat", node_chitchat)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges(
        "classify", route_after_classify,
        {"retrieve": "retrieve", "chitchat": "chitchat"},
    )
    graph.add_edge("retrieve", END)
    graph.add_edge("chitchat", END)

    return graph.compile()


# ============================================================
# 6. Pure Python 降级 (无 LangGraph 时)
# ============================================================

def run_pure_python(question: str, knowledge: list) -> dict:
    """LangGraph 不可用时的降级实现, 行为完全一致"""
    trace = []
    intent = classify_intent(question)
    trace.append(f"[classify] -> {intent}")

    if intent == "relevant":
        result = retrieve_answer(question, knowledge)
        trace.append(f"[retrieve] -> source={result.get('source')}")
    else:
        result = chitchat_response(question)
        trace.append("[chitchat]")

    return {
        "question": question,
        "intent": intent,
        "answer": result["answer"],
        "source": result.get("source", ""),
        "score": result.get("score", 0.0),
        "trace": trace,
    }


# ============================================================
# 7. 演示入口
# ============================================================

def main():
    print("=" * 60)
    print("  LangGraph 2 节点工作流 - 麒麟运维知识问答")
    print("=" * 60)

    knowledge = load_knowledge_base()
    print(f"知识库: {len(knowledge)} 条\n")

    if HAS_LANGGRAPH:
        print("[✓] 检测到 LangGraph, 使用 StateGraph")
        app = build_langgraph_workflow(knowledge)
        run = lambda q: app.invoke({"question": q, "intent": "", "answer": "",
                                      "source": "", "score": 0.0, "trace": []})
    else:
        print("[!] 未安装 LangGraph, 使用 Pure Python 降级")
        print("    安装: pip install langgraph langchain-core")
        run = lambda q: run_pure_python(q, knowledge)

    # 演示 4 个问题 (覆盖所有路由)
    test_questions = [
        "麒麟系统怎么装 .deb 包?",          # → relevant → retrieve
        "内网 DNS 解析失败怎么办?",          # → relevant → retrieve (匹配 DNS 条目)
        "你好啊",                            # → irrelevant → chitchat
        "今天天气怎么样?",                   # → irrelevant → chitchat
    ]

    for i, q in enumerate(test_questions, 1):
        print(f"\n--- Q{i}: {q}")
        result = run(q)
        print(f"  意图: {result.get('intent')}")
        print(f"  来源: {result.get('source')}")
        print(f"  评分: {result.get('score', 0):.1f}")
        print(f"  答案: {result.get('answer', '')[:200]}")
        print(f"  路径: {' -> '.join(result.get('trace', []))}")

    print("\n" + "=" * 60)
    print("  演示完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
