#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mini_agent.py - 训练营 Mini Agent (30 分)
=========================================
一个能"感知-思考-行动"的最小 Agent 框架
集成 2 节点 LangGraph 工作流 + SQLite 记忆 + 工具调用

设计原则:
  1. 单文件 (除 LangGraph 外零外部依赖)
  2. 可解释 (每一步都有 trace)
  3. 工具化 (Calculator/Time/Knowledge 三件套)
  4. 有记忆 (SQLite 持久化对话)

Agent 循环:
  observe → think → act → reflect
"""
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

# 复用 LangGraph 工作流
try:
    import sys
    _this_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(_this_dir))
    from knowledge_qa_workflow import (
        load_knowledge_base, classify_intent,
        retrieve_answer, chitchat_response,
    )
    HAS_WORKFLOW = True
except ImportError:
    HAS_WORKFLOW = False


# ============================================================
# 1. 工具 (Tools) - Agent 的"手脚"
# ============================================================

def tool_calculator(expression: str) -> str:
    """
    工具: 计算器 (使用 ast 解析, 不调用 eval, 防代码注入)
    入参: 数学表达式 (如 "1+2*3")
    出参: 计算结果字符串
    """
    import ast
    import operator
    if not re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', expression):
        return f"错误: 表达式包含非法字符 (只允许数字和 + - * /)"

    # 安全的二元运算白名单
    _BIN_OPS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.FloorDiv: operator.floordiv,
    }
    _UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            return _BIN_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        raise ValueError(f"不支持的节点: {type(node).__name__}")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree)
        return f"计算结果: {expression} = {result}"
    except Exception as e:
        return f"计算失败: {e}"


def tool_current_time(args: str = "") -> str:
    """工具: 获取当前时间"""
    return f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


def tool_save_memory(agent, key: str, value: str) -> str:
    """工具: 保存到记忆库 (SQLite)"""
    return agent.memory.save(key, value)


# ============================================================
# 2. 记忆 (Memory) - SQLite 实现
# ============================================================

class Memory:
    """基于 SQLite 的轻量记忆, key-value 形式"""

    def __init__(self, db_path: str = "d:/藏数据/raw/agent/agent_memory.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_key ON memory(key)")

    def save(self, key: str, value: str) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO memory(ts, key, value) VALUES (?, ?, ?)",
                (ts, key, value)
            )
        return f"已记住: {key} = {value}"

    def recall(self, key: str) -> str:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM memory WHERE key = ? ORDER BY id DESC LIMIT 1",
                (key,)
            ).fetchone()
        return row[0] if row else f"未找到: {key}"

    def list_all(self) -> list:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT key, value, ts FROM memory ORDER BY id DESC LIMIT 20"
            ).fetchall()
        return [{"key": r[0], "value": r[1], "ts": r[2]} for r in rows]


# ============================================================
# 3. Agent 主类 (ReAct 循环)
# ============================================================

class MiniAgent:
    """
    极简 Agent: observe → think → act → reflect

    支持 4 类工具:
      - calculator: 数学计算
      - time: 获取时间
      - memory.save: 保存记忆
      - memory.recall: 回忆
    """

    def __init__(self, knowledge_path: str = None):
        self.name = "MiniAgent-Kylin"
        self.memory = Memory()
        self.knowledge = load_knowledge_base(knowledge_path) if HAS_WORKFLOW else []
        self.tools = {
            "calculator": tool_calculator,
            "time": tool_current_time,
            "save": self.memory.save,
            "recall": self.memory.recall,
        }
        # 对话历史
        self.history = []

    # ------- 思考: 决定要不要用工具 -------
    def _decide_tool(self, question: str) -> tuple:
        """
        决定是否调用工具
        返回 (tool_name, args, confidence)
        """
        q = question.strip()

        # 计算请求
        m = re.search(r'计算\s*([\d\s\+\-\*\/\.\(\)]+)', q)
        if m:
            return ("calculator", m.group(1), 0.95)
        # 纯算式
        if re.match(r'^[\d\s\+\-\*\/\.\(\)]+$', q) and any(op in q for op in '+-*/'):
            return ("calculator", q, 0.9)
        # 时间 (BUG-12 修复: 加括号, 消除运算符优先级歧义)
        if ("几点" in q) or ("时间" in q) or ("现在" in q and "时" in q):
            return ("time", "", 0.9)
        # 记忆保存 (用户说"记住"/"我喜欢")
        m = re.search(r'记住[:：]?\s*(.+)', q)
        if m:
            content = m.group(1).strip()
            # 拆 key=value
            if "=" in content or "是" in content:
                parts = re.split(r'[=是]', content, maxsplit=1)
                return ("save", (parts[0].strip(), parts[1].strip()), 0.85)
        # 记忆回忆
        # 特殊模式: "我叫什么名字" / "我多大了" 等
        m = re.search(r'我(?:叫|是)\s*什么', q)
        if m:
            return ("recall", "我的名字", 0.9)
        m = re.search(r'我(?:多|几)大', q)
        if m:
            return ("recall", "我的年龄", 0.9)
        # 通用: "我X是Y" -> 查 X
        m = re.search(r'我(?:的)?([\u4e00-\u9fa5]{2,8}?)(?:是|叫)', q)
        if m:
            key = m.group(1).strip()
            if key not in ("什么", "多大", "几岁"):
                return ("recall", "我的" + key, 0.75)
        # 不是工具调用, 走知识库
        return (None, None, 0.0)

    # ------- 行动: 执行工具或调工作流 -------
    def _act(self, question: str, trace: list) -> str:
        tool, args, conf = self._decide_tool(question)

        # 工具路径
        if tool == "calculator":
            trace.append(f"[think] 检测到计算请求 (conf={conf})")
            result = tool_calculator(args)
            trace.append(f"[act] calculator({args}) -> {result}")
            return result

        if tool == "time":
            trace.append(f"[think] 检测到时间请求")
            result = tool_current_time(args)
            trace.append(f"[act] time() -> {result}")
            return result

        if tool == "save":
            key, value = args
            trace.append(f"[think] 检测到记忆保存: {key}={value}")
            result = self.memory.save(key, value)
            trace.append(f"[act] memory.save({key}, {value})")
            return result

        if tool == "recall":
            trace.append(f"[think] 检测到记忆回忆: {args}")
            value = self.memory.recall(args)
            result = f"你之前说过 {args} = {value}" if "未找到" not in value else value
            trace.append(f"[act] memory.recall({args}) -> {value}")
            return result

        # 知识库路径 (调 LangGraph 工作流)
        trace.append(f"[think] 路由到 LangGraph 工作流")
        if HAS_WORKFLOW:
            intent = classify_intent(question)
            trace.append(f"[classify] intent = {intent}")
            if intent == "relevant":
                result = retrieve_answer(question, self.knowledge)
                trace.append(f"[retrieve] source={result.get('source')}, score={result.get('score', 0):.1f}")
            else:
                result = chitchat_response(question)
                trace.append(f"[chitchat]")
        else:
            result = {"answer": "(工作流未加载, 请检查 knowledge_qa_workflow.py)", "source": "none", "score": 0}

        return result["answer"]

    # ------- 对外接口: 接收用户输入 -------
    def chat(self, question: str) -> dict:
        """主入口: 接收问题, 返回答案 + 思考过程"""
        trace = [f"[observe] 用户问: {question}"]
        t0 = time.time()
        answer = self._act(question, trace)
        dt = time.time() - t0

        # 存历史
        self.history.append({
            "ts": datetime.now().strftime("%H:%M:%S"),
            "q": question,
            "a": answer[:120],
        })

        return {
            "question": question,
            "answer": answer,
            "trace": trace,
            "latency_ms": int(dt * 1000),
        }


# ============================================================
# 4. 演示 + 测试
# ============================================================

def demo():
    print("=" * 60)
    print(f"  {MiniAgent().name} - 训练营 Mini Agent 演示")
    print("=" * 60)

    agent = MiniAgent()

    test_questions = [
        ("工具-计算",   "计算 1+2*3"),                # → calculator
        ("工具-时间",   "现在几点?"),                  # → time
        ("工具-保存",   "记住: 我的名字 = 藏世杰"),     # → memory.save
        ("工具-回忆",   "我叫什么名字?"),              # → memory.recall
        ("知识库",       "麒麟系统怎么装 .deb 包?"),    # → retrieve
        ("闲聊",         "你好啊"),                     # → chitchat
    ]

    for label, q in test_questions:
        print(f"\n{'─' * 60}")
        print(f"[{label}] {q}")
        result = agent.chat(q)
        print(f"[答案] ({result['latency_ms']}ms):")
        for line in result["answer"].split("\n")[:5]:
            print(f"   {line}")
        print(f"[思考过程]:")
        for step in result["trace"]:
            print(f"   {step}")

    # 记忆库
    print(f"\n{'─' * 60}")
    print("[记忆库快照]:")
    for m in agent.memory.list_all():
        print(f"   [{m['ts']}] {m['key']} = {m['value']}")


if __name__ == "__main__":
    demo()
