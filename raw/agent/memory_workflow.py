"""
OS Agent 记忆检索工作流 (基于 LangGraph)

架构: 5 节点 + 条件路由
  ┌─────────────────────────────────────────────────────────────┐
  │                         START                                │
  └─────────────────────────┬───────────────────────────────────┘
                            ▼
                    ┌───────────────┐
                    │  Node A       │
                    │ 意图识别       │ ← 闲聊 / 查记忆 / 隐私查询
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌──────────┐   ┌───────────┐  ┌───────────┐
     │ Node B   │   │ Node B    │  │ Node E    │
     │ 记忆检索  │   │ 记忆检索   │  │ 隐私检查   │
     └────┬─────┘   └─────┬─────┘  └─────┬─────┘
          │               │              │
          ▼               ▼              ▼
     ┌──────────┐   ┌───────────┐  ┌───────────┐
     │ Node C   │   │ Node C    │  │ Node C    │
     │ 偏好路由  │   │ 偏好路由   │  │ 生成回答   │
     └────┬─────┘   └─────┬─────┘  └───────────┘
          │               │
          ▼               ▼
     ┌──────────┐   ┌───────────┐
     │ Node D   │   │ Node D    │
     │ 生成回答  │   │ 生成回答   │
     └────┬─────┘   └─────┬─────┘
          │               │
          └───────┬───────┘
                  ▼
               ┌────────┐
               │  END   │
               └────────┘

节点说明:
  A - 意图识别: 判断用户意图 (chatter/memory_query/privacy_query)
  B - 记忆检索: 用字符 bigram + uid 匹配从 SQLite 检索记忆
  C - 偏好路由: 检查是否有冲突偏好，决定采用哪个版本
  D - 生成回答: 结合检索到的记忆生成最终回答
  E - 隐私检查: 检测是否涉及隐私信息，决定脱敏策略
"""

import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal, Optional, Sequence

# ========== 依赖检查 ==========
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    print("[警告] langgraph 未安装，使用纯 Python 实现工作流")


# ========== 工作流状态 ==========
@dataclass
class WorkflowState:
    """LangGraph 工作流的状态"""
    uid: str = ""                          # 用户 ID
    query: str = ""                        # 用户查询
    intent: str = ""                       # 识别出的意图: chatter/memory_query/privacy_query
    retrieved_memories: list = field(default_factory=list)  # 检索到的记忆
    conflict_detected: bool = False        # 是否检测到记忆冲突
    resolved_memory: Optional[dict] = None # 解决冲突后的记忆
    answer: str = ""                       # 最终回答
    privacy_risk: bool = False             # 是否存在隐私风险
    trace: list = field(default_factory=list)  # 执行轨迹（可解释性证据）

    def add_trace(self, node: str, detail: str):
        """记录执行轨迹"""
        self.trace.append({"node": node, "detail": detail})


# ========== SQLite 记忆数据库 ==========
class MemoryDB:
    """SQLite 记忆存储，支持高效检索"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """建表 + 索引"""
        c = self.conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                value TEXT NOT NULL,
                action TEXT DEFAULT 'keep',       -- keep/override/remove/review
                scope TEXT DEFAULT 'long',         -- long/short/none/needs_review
                reason TEXT,
                evidence TEXT,
                time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 核心索引：保证查询时间 <= 500ms
            CREATE INDEX IF NOT EXISTS idx_uid ON agent_memory(uid);
            CREATE INDEX IF NOT EXISTS idx_memory_key ON agent_memory(memory_key);
            CREATE INDEX IF NOT EXISTS idx_action ON agent_memory(action);
            CREATE INDEX IF NOT EXISTS idx_uid_action ON agent_memory(uid, action);
            CREATE INDEX IF NOT EXISTS idx_uid_key ON agent_memory(uid, memory_key);
        """)
        self.conn.commit()

    def import_from_jsonl(self, jsonl_path: str):
        """从 JSONL 文件批量导入记忆"""
        path = Path(jsonl_path)
        if not path.exists():
            print(f"  [DB] 文件不存在: {path}")
            return 0

        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    self.conn.execute(
                        """INSERT INTO agent_memory
                           (uid, memory_key, value, action, scope, reason, evidence, time)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            r.get("uid", ""),
                            r.get("memory_key", ""),
                            r.get("value", ""),
                            r.get("action", "keep"),
                            r.get("scope", "long"),
                            r.get("reason", ""),
                            json.dumps(r.get("evidence", []), ensure_ascii=False),
                            r.get("time", ""),
                        ),
                    )
                    count += 1
                except (json.JSONDecodeError, Exception):
                    pass

        self.conn.commit()
        print(f"  [DB] 导入 {count} 条记忆 → {self.db_path}")
        return count

    def search(self, uid: str, query: str, top_k: int = 5) -> list[dict]:
        """
        字符 bigram 检索: uid 匹配 + 字符 bigram 命中
        """
        # 1) 先按 uid + action 过滤
        rows = self.conn.execute(
            """SELECT * FROM agent_memory
               WHERE uid = ? AND action IN ('keep', 'override', 'remove')
               ORDER BY time DESC""",
            (uid,),
        ).fetchall()

        if not rows:
            return []

        # 2) 字符 bigram 打分
        def to_bigrams(s):
            s = (s or "").lower()
            chars = re.findall(r"[\u4e00-\u9fa5]|\w", s)
            return set(a + b for a, b in zip(chars, chars[1:])) | set(chars)

        q_bigrams = to_bigrams(query)
        scored = []
        for row in rows:
            text = row["value"] + " " + row["memory_key"]
            t_bigrams = to_bigrams(text)
            overlap = q_bigrams & t_bigrams
            if overlap:
                scored.append({
                    "id": row["id"],
                    "uid": row["uid"],
                    "memory_key": row["memory_key"],
                    "value": row["value"],
                    "action": row["action"],
                    "scope": row["scope"],
                    "reason": row["reason"],
                    "evidence": row["evidence"],
                    "time": row["time"],
                    "score": len(overlap),
                    "overlap_keys": list(overlap)[:3],
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def get_by_key(self, uid: str, memory_key: str) -> list[dict]:
        """按 uid + memory_key 精确查询"""
        rows = self.conn.execute(
            """SELECT * FROM agent_memory
               WHERE uid = ? AND memory_key = ?
               ORDER BY time DESC""",
            (uid, memory_key),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()


# ========== 字符 bigram 检索器 (纯 Python 版) ==========
class SimpleRetriever:
    """不依赖 LangGraph 的简单检索器"""

    def __init__(self, memories: list[dict]):
        self.memories = memories

    def search(self, uid: str, query: str, top_k: int = 5) -> list[dict]:
        candidates = [
            m for m in self.memories
            if m.get("uid") == uid and m.get("action") in ("keep", "override", "remove")
        ]

        def to_bigrams(s):
            s = (s or "").lower()
            chars = re.findall(r"[\u4e00-\u9fa5]|\w", s)
            return set(a + b for a, b in zip(chars, chars[1:])) | set(chars)

        q_bigrams = to_bigrams(query)
        scored = []
        for m in candidates:
            text = m.get("value", "") + " " + m.get("memory_key", "")
            t_bigrams = to_bigrams(text)
            overlap = q_bigrams & t_bigrams
            if overlap:
                scored.append({**m, "score": len(overlap), "overlap_keys": list(overlap)[:3]})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


# ========== LangGraph 工作流 ==========
def create_workflow(db_or_retriever):
    """
    创建 LangGraph 工作流
    参数 db_or_retriever: MemoryDB 或 SimpleRetriever 实例
    """

    # ---- Node A: 意图识别 ----
    def intent_recognition(state: WorkflowState) -> WorkflowState:
        """判断用户意图: chatter/memory_query/privacy_query"""
        q = state.query.lower()

        # 隐私查询模式
        if any(kw in q for kw in ("我的手机", "我的邮箱", "我的电话", "我的身份证号", "密码是什么")):
            state.intent = "privacy_query"
            state.privacy_risk = True
            state.add_trace("A_intent", f"检测到隐私查询: {state.query[:30]}")
            return state

        # 记忆查询模式
        if any(kw in q for kw in ("怎么", "为什么", "如何", "帮我", "查", "找", "更新", "安装")):
            state.intent = "memory_query"
            state.add_trace("A_intent", f"检测到记忆查询: {state.query[:30]}")
            return state

        # 闲聊
        state.intent = "chatter"
        state.add_trace("A_intent", f"判定为闲聊: {state.query[:30]}")
        return state

    # ---- Node B: 记忆检索 ----
    def memory_retrieval(state: WorkflowState) -> WorkflowState:
        """从数据库/检索器中搜索记忆"""
        if isinstance(db_or_retriever, MemoryDB):
            results = db_or_retriever.search(state.uid, state.query, top_k=5)
        else:
            results = db_or_retriever.search(state.uid, state.query, top_k=5)

        state.retrieved_memories = results
        state.add_trace("B_retrieval", f"检索到 {len(results)} 条记忆, uid={state.uid}")
        return state

    # ---- Node C: 偏好路由（冲突检测与解决） ----
    def preference_routing(state: WorkflowState) -> WorkflowState:
        """检查记忆冲突，采用最新版本"""
        memories = state.retrieved_memories

        # 按 memory_key 分组，检测冲突
        by_key = {}
        for m in memories:
            key = m.get("memory_key", "")
            if key not in by_key:
                by_key[key] = []
            by_key[key].append(m)

        resolved = []
        conflict_found = False
        for key, mems in by_key.items():
            # 如果有 override 动作，采用最新版本
            overrides = [m for m in mems if m.get("action") == "override"]
            keeps = [m for m in mems if m.get("action") == "keep"]
            removes = [m for m in mems if m.get("action") == "remove"]

            if removes:
                # forget 指令 → 不返回该记忆
                state.add_trace("C_routing", f"memory_key={key}: forget 指令, 过滤")
                continue

            if overrides:
                # 有覆盖 → 取最新的 override
                latest = sorted(overrides, key=lambda x: x.get("time", ""), reverse=True)[0]
                resolved.append(latest)
                if keeps:
                    conflict_found = True
                    state.add_trace("C_routing", f"memory_key={key}: override 覆盖 keep, 冲突已解决")
            elif keeps:
                resolved.extend(keeps)

        state.resolved_memory = resolved[0] if resolved else None
        state.conflict_detected = conflict_found
        state.add_trace("C_routing", f"冲突检测: {conflict_found}, 解决后 {len(resolved)} 条")
        return state

    # ---- Node D: 生成回答 ----
    def generate_answer(state: WorkflowState) -> WorkflowState:
        """结合检索到的记忆生成回答"""
        memories = state.retrieved_memories
        resolved = state.resolved_memory

        # forget 命中 → 脱敏
        forgets = [m for m in memories if m.get("action") == "remove"]
        if forgets:
            key = forgets[0].get("memory_key", "")
            if key in ("email", "phone"):
                state.answer = f"未保存你的{'邮箱' if key == 'email' else '手机号'}信息（已按 forget 指令清除）。"
                state.add_trace("D_answer", "forget 命中 → 脱敏回答")
                return state

        # 有检索结果 → 基于记忆回答
        if resolved:
            m = resolved
            state.answer = f"根据你的偏好【{m.get('memory_key', '')}】：{m.get('value', '')}"
            if state.conflict_detected:
                state.answer += f"（冲突已解决，采用最新版本）"
            state.add_trace("D_answer", f"基于记忆生成回答")
            return state

        if memories:
            m = memories[0]
            state.answer = f"相关信息：{m.get('value', '')}"
            state.add_trace("D_answer", "使用检索结果回答")
            return state

        # 无记忆 → 默认回答
        if state.intent == "chatter":
            state.answer = "你好！有什么我可以帮你的吗？"
        else:
            state.answer = "未找到相关记忆信息。"
        state.add_trace("D_answer", "无记忆 → 默认回答")
        return state

    # ---- Node E: 隐私检查 ----
    def privacy_check(state: WorkflowState) -> WorkflowState:
        """检测并脱敏隐私信息"""
        state.add_trace("E_privacy", f"隐私风险: {state.privacy_risk}")

        # 隐私查询 → 直接返回脱敏回答
        if state.privacy_risk:
            memories = state.retrieved_memories
            forgets = [m for m in memories if m.get("action") == "remove"]
            if forgets:
                key = forgets[0].get("memory_key", "")
                state.answer = f"未保存你的{'邮箱' if key == 'email' else '手机号'}信息（已按 forget 指令清除）。"
            else:
                state.answer = "未保存你的个人信息，也不能查询未授权的隐私数据。"
            state.add_trace("E_privacy", "隐私查询 → 脱敏回答")
            return state

        # 检查回答中是否包含隐私
        answer = state.answer
        if re.search(r"1[3-9]\d{9}", answer):
            answer = re.sub(r"(1[3-9]\d)\d{4}(\d{4})", r"\1****\2", answer)
            state.add_trace("E_privacy", "回答中检测到手机号 → 脱敏")
        if re.search(r"[\w.-]+@[\w.-]+\.\w+", answer):
            answer = re.sub(r"(\w{2})[\w.-]*@([\w.-]+\.\w+)", r"\1****@\2", answer)
            state.add_trace("E_privacy", "回答中检测到邮箱 → 脱敏")

        state.answer = answer
        return state

    # ---- 条件路由 ----
    def route_intent(state: WorkflowState) -> str:
        """根据意图路由到不同节点"""
        if state.intent == "privacy_query":
            return "privacy_check"
        elif state.intent == "memory_query":
            return "memory_retrieval"
        else:
            return "generate_answer"

    # ========== 构建图 ==========
    if HAS_LANGGRAPH:
        workflow = StateGraph(WorkflowState)

        # 添加节点
        workflow.add_node("intent_recognition", intent_recognition)
        workflow.add_node("memory_retrieval", memory_retrieval)
        workflow.add_node("preference_routing", preference_routing)
        workflow.add_node("generate_answer", generate_answer)
        workflow.add_node("privacy_check", privacy_check)

        # 设置入口
        workflow.set_entry_point("intent_recognition")

        # 条件路由
        workflow.add_conditional_edges(
            "intent_recognition",
            route_intent,
            {
                "memory_retrieval": "memory_retrieval",
                "privacy_check": "privacy_check",
                "generate_answer": "generate_answer",
            },
        )

        # memory_retrieval → preference_routing → generate_answer
        workflow.add_edge("memory_retrieval", "preference_routing")
        workflow.add_edge("preference_routing", "generate_answer")
        workflow.add_edge("privacy_check", "generate_answer")
        workflow.add_edge("generate_answer", END)

        graph = workflow.compile()
        return graph

    else:
        # 纯 Python 降级实现
        return PurePythonWorkflow(
            intent_recognition, memory_retrieval,
            preference_routing, generate_answer, privacy_check,
            route_intent,
        )


class PurePythonWorkflow:
    """纯 Python 实现的降级工作流"""

    def __init__(self, intent_fn, retrieval_fn, routing_fn, answer_fn, privacy_fn, route_fn):
        self.intent_fn = intent_fn
        self.retrieval_fn = retrieval_fn
        self.routing_fn = routing_fn
        self.answer_fn = answer_fn
        self.privacy_fn = privacy_fn
        self.route_fn = route_fn

    def invoke(self, state: WorkflowState) -> WorkflowState:
        # A: 意图识别
        state = self.intent_fn(state)

        # 路由
        next_node = self.route_fn(state)

        if next_node == "memory_retrieval":
            # B: 记忆检索
            state = self.retrieval_fn(state)
            # C: 偏好路由
            state = self.routing_fn(state)
        elif next_node == "privacy_check":
            # B: 记忆检索
            state = self.retrieval_fn(state)
            # E: 隐私检查
            state = self.privacy_fn(state)

        # D: 生成回答
        state = self.answer_fn(state)

        return state


# ========== 运行入口 ==========
def main():
    import argparse
    parser = argparse.ArgumentParser(description="OS Agent 记忆检索工作流")
    parser.add_argument("--db", type=str, default=":memory:", help="SQLite 数据库路径")
    parser.add_argument("--import-from", type=str, help="从 JSONL 导入记忆")
    parser.add_argument("--uid", type=str, default="u001", help="用户 ID")
    parser.add_argument("--query", type=str, default="帮我导出月报", help="查询内容")
    parser.add_argument("--trace", action="store_true", help="打印执行轨迹")
    args = parser.parse_args()

    print("="*60)
    print("OS Agent 记忆检索工作流 (LangGraph)")
    print("="*60)

    # 1. 初始化数据库
    if args.db == ":memory:":
        db = MemoryDB(":memory:")
    else:
        db = MemoryDB(args.db)

    # 2. 导入记忆
    import_path = args.import_from
    if not import_path:
        # 默认从 D5 输出导入
        default_path = Path(__file__).resolve().parent.parent / "d5" / "merged_memories.jsonl"
        if default_path.exists():
            import_path = str(default_path)

    if import_path:
        db.import_from_jsonl(import_path)

    # 3. 创建检索器 (纯 Python 降级)
    all_memories = []
    if import_path and Path(import_path).exists():
        with open(import_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        all_memories.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    retriever = SimpleRetriever(all_memories)

    # 4. 创建工作流
    workflow = create_workflow(retriever)

    # 5. 执行查询
    state = WorkflowState(uid=args.uid, query=args.query)
    print(f"\n[查询] uid={args.uid}, query='{args.query}'")

    if HAS_LANGGRAPH:
        # LangGraph 执行
        result = workflow.invoke(state)
    else:
        # 纯 Python 执行
        result = workflow.invoke(state)

    # 6. 输出结果
    print(f"\n[意图] {result.intent}")
    print(f"[检索] {len(result.retrieved_memories)} 条记忆")
    if result.retrieved_memories:
        for m in result.retrieved_memories:
            print(f"  - key={m['memory_key']}, action={m['action']}, value={m['value'][:50]}")
    print(f"[冲突] {'是' if result.conflict_detected else '否'}")
    print(f"[回答] {result.answer}")
    print(f"[隐私风险] {'是' if result.privacy_risk else '否'}")

    if args.trace:
        print(f"\n[执行轨迹]")
        for t in result.trace:
            print(f"  {t['node']}: {t['detail']}")

    # 7. 演示多个查询
    print("\n" + "="*60)
    print("演示: 多轮对话")
    print("="*60)

    demo_queries = [
        ("u001", "帮我导出月报，要详细版"),
        ("u002", "回复我一下驱动更新步骤"),
        ("u004", "我的邮箱是什么？"),
        ("u007", "解释一下为什么要这样做"),
        ("u010", "刚才 web_search 超时，所以驱动知识是不是不能用了？"),
    ]

    for uid, query in demo_queries:
        s = WorkflowState(uid=uid, query=query)
        r = workflow.invoke(s)
        print(f"\n[{uid}] {query}")
        print(f"  → [{r.intent}] {r.answer[:80]}")

    db.close()


if __name__ == "__main__":
    main()
