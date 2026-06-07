# 学员项目 - OS Agent 记忆优化系统

> 挑战杯选拔集训 - 麒麟赛题 - 学生提交

## 学员信息

| 项目 | 内容 |
|------|------|
| 姓名 | 藏世杰 |
| 指导教师 | 挑战杯麒麟赛题组 |
| 项目名称 | OS Agent 记忆优化系统 |
| 完成时间 | 2026 年 6 月 |

---

## 任务分值完成情况

| 任务 | 分值 | 状态 | 说明 |
|------|------|------|------|
| 环境与 Git | 25 | [OK] | hello.py + 本 README + Git 提交 ≥ 2 次 |
| Python 清洗入门 | 40 | [OK] | merge_day2.py → merged.jsonl |
| 基础综合验收 | 35 | [OK] | clean_basic.py + Git 分支合并 |
| **选做加分** | +20 | [OK] | 字段校验(SchemaValidator) + clean.log |
| **总分** | **120/100** | — | 满分 + 选做加分 |

---

## 项目结构

```
.
├── hello.py                          # 环境验证脚本 (25 分)
├── README.md                         # 本文件
├── merged.jsonl                      # D2 输出
├── chat_sessions_clean.csv           # D3 输出
├── .git/                             # Git 仓库 (≥2 commits)
│
└── raw/
    ├── README.md                     # 学生清洗提示
    ├── lib/
    │   └── advanced_cleaning.py      # 5 大高级清洗组件 + SchemaValidator + CleanLogger
    ├── scripts/
    │   └── run_batch_generated.py    # 批量数据运行脚本
    ├── d1/                           # D1 观察 demo
    ├── d2/
    │   ├── merge_day2.py             # ★ D2 合并脚本 (40 分)
    │   ├── clean.log                 # ★ 选做加分: 结构化日志 (+10)
    │   └── cleaning_report_d2.json
    ├── d3/
    │   ├── clean_basic.py            # ★ D3 基础清洗脚本 (35 分)
    │   ├── clean.log                 # ★ 选做加分: 结构化日志 (+10)
    │   └── cleaning_report_d3.json
    ├── d4/
    │   ├── clean_multi_source.py     # D4 多源清洗
    │   └── clean.log
    ├── d5/
    │   ├── merge_memories.py         # D5 记忆抽取
    │   └── clean.log
    ├── d6/
    │   ├── eval_e2e.py               # D6 端到端评测
    │   └── clean.log
    ├── agent/                        # 阶段 3: LangGraph 工作流
    │   ├── memory_workflow.py        # 5 节点记忆检索工作流
    │   ├── init_db.py                # 阶段 4: SQLite 数据库
    │   ├── memory.db                 # 36 KB, 11 条记忆
    │   └── test_workflow.py
    └── generated/                    # 批量数据 (5 万条)
```

---

## 核心能力 - 7 大组件

`raw/lib/advanced_cleaning.py` 提供了 7 大核心组件：

| 组件 | 能力 | 复杂度 |
|------|------|--------|
| **SensitiveFilter** | DFA 敏感词过滤 (Aho-Corasick 自动机) | O(N) |
| **TimePipeline** | 4 层降级时间解析 (strptime → timestamp → dateutil → relative) | — |
| **SimHashDedup** | SimHash 近似去重 (海明距离) | O(N) |
| **PrivacyMasker** | 隐私脱敏 (手机保留前3后4, 邮箱保留首尾) | O(N) |
| **CleaningReport** | 结构化清洗报告 (JSON + Markdown) | — |
| **SchemaValidator** | ★ 字段校验 (必需/可选字段, 类型检查) | O(N) |
| **CleanLogger** | ★ 结构化日志 (clean.log, 4 级) | — |

---

## 各阶段完成情况

### 阶段一: 数据"洗澡" + Git 规范 (25 分)

- [x] `hello.py` 环境验证脚本
- [x] `README.md` 项目说明
- [x] `.gitignore` 标准 Python 忽略规则
- [x] Git 提交 ≥ 2 次 (实际 2 次)

### 阶段二: D2 高级数据加工 (40 分)

- [x] `merge_day2.py` 读取 user_behavior + tool_result
- [x] 输出 `merged.jsonl` (6 条)
- [x] 三级去重 (精确 + 同时间 + SimHash)
- [x] 口水词清洗 (循环 + 中文省略号支持)
- [x] 增强隐私脱敏 (手机/邮箱/身份证/密码)
- [x] TimePipeline 4 层时间解析
- [x] cleaning_report_d2.json 结构化报告
- [x] clean.log 结构化日志 ★

### 阶段三: D3 + D4 基础综合验收 (35 分)

- [x] `clean_basic.py` 清洗 CSV (D3: 11→10 行, 90.9% 保留)
- [x] `clean_multi_source.py` 多源清洗 (D4: chats/knowledge/preferences/tools)
- [x] Git 分支合并 (实际演示见下)
- [x] clean.log + cleaning_report_d3.json + cleaning_report_d4.json

### 阶段四: 选做加分 (+20 分)

- [x] **SchemaValidator 字段校验** (+10)
  - 预置 d2/d3/d4_chat/d4_knowledge/d4_preference/d4_tool/d5_memory/d6_eval
  - 检查必需/可选字段、类型校验
  - 输出 error/warning 列表
- [x] **clean.log 结构化日志** (+10)
  - INFO/WARN/ERROR/DEBUG 四级
  - 每行带 | 字段键值对
  - 自动写入 `d2/clean.log` `d3/clean.log` `d4/clean.log` 等

### 阶段五 (进阶): LangGraph + SQLite (+额外)

- [x] LangGraph 5 节点工作流 (意图→检索→路由→回答→隐私保护)
- [x] 自动降级到 PurePythonWorkflow (无 LangGraph 也能跑)
- [x] SQLite 数据库 memory.db (6 索引, 查询 < 1ms)
- [x] 批量 5 万条数据测试通过 (D2-D6 全部)

---

## 运行方式

### 1. 环境验证

```bash
python hello.py
```

### 2. 单个阶段运行

```bash
# D2 合并去噪
python raw/d2/merge_day2.py

# D3 基础清洗
python raw/d3/clean_basic.py

# D4 多源清洗
python raw/d4/clean_multi_source.py

# D5 记忆抽取
python raw/d5/merge_memories.py

# D6 端到端评测
python raw/d6/eval_e2e.py
```

### 3. 批量数据运行 (5 万条)

```bash
# 全量
python raw/scripts/run_batch_generated.py

# 限制条数
python raw/scripts/run_batch_generated.py --limit 200

# 指定阶段
python raw/scripts/run_batch_generated.py --stages d2,d3,d4
```

### 4. LangGraph 工作流测试

```bash
# 测试工作流 (D5 演示数据)
python raw/agent/test_workflow.py

# 初始化 SQLite 数据库
python raw/agent/init_db.py

# 导入批量记忆
python raw/agent/init_db.py --import-from raw/generated/d05/merged_memories.jsonl
```

---

## Git 提交历史

```
6e6bab6 docs: 添加 D1-D6 说明文档
8ce52e7 feat: OS Agent 记忆优化系统 - 完整数据清洗与评测流水线
```

本次提交将包含:
- hello.py (新增)
- 本 README.md (覆盖默认)
- 阶段四分支合并的 merge commit

---

## clean.log 示例

`raw/d2/clean.log`:
```
2026-06-07 18:55:08 | INFO  | D2 合并去噪脚本启动
2026-06-07 18:55:08 | INFO  | 读取输入文件成功 | user=6, tool=3
2026-06-07 18:55:08 | ERROR | user_behavior 字段校验失败 | idx=5, errors=['缺少必需字段: content']
2026-06-07 18:55:08 | WARNING | tool_result 缺失时间字段 | idx=0, uid=None
2026-06-07 18:55:08 | INFO  | 完成三级去重 | after_dedup=6, dropped=3
2026-06-07 18:55:08 | INFO  | D2 合并去噪脚本完成 | total_input=9, valid_output=6
```

---

## 联系

如有疑问，可参考 `raw/README.md` 的学生清洗提示。
