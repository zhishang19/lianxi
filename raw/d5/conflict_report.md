# D5 冲突与流转报告

生成时间: 2026-06-07 18:58:22

## 1. 统计
- 事件总数: 14 (精确去重 0 条, SimHash 去重 0 条)
- 快照总数: 11
- 冲突项: 3
- needs_review: 1

## 2. 冲突项（谁覆盖谁）
### 1. [u001] output_style - preference_override
- 旧值: `输出简洁版` (event=E-002, time=2026-06-04 09:00:00)
- 新值: `输出详细版，带数据表格` (event=E-001, time=2026-06-04 09:01:00)
- 决策: 最新明确偏好覆盖旧偏好，旧版本进入 history

### 2. [u002] emoji_policy - preference_override
- 旧值: `默认允许 emoji` (event=E-004, time=2026-06-01 00:00:00)
- 新值: `回复不要使用 emoji` (event=E-003, time=2026-06-04 10:15:00)
- 决策: 最新明确偏好覆盖旧偏好，旧版本进入 history

### 3. [u003] driver_update_entry - knowledge_override
- 旧值: `驱动更新入口是系统更新` (event=E-005, time=2026-06-04 14:00:00)
- 新值: `驱动更新入口是驱动管理器` (event=E-006, time=2026-06-04 18:30:00)
- 决策: 新知识覆盖旧知识，保留覆盖证据

## 3. needs_review 列表
- [u007] answer_style: 时间缺失 (event=E-012)

## 4. 临时指令未覆盖长期（验证）
- 已自动保证：所有 temporary_instruction 输出 scope=short，不进入 long-term 检索。

## 5. forget 移除清单（不应进入长期记忆）
- 共处理 0 条 forget 事件，相关 memory_value 已从可检索记忆中移除。

## 6. 同义 / 错别字归一
- 祥细 → 详细
- 奇麟 → 麒麟
- 会义 → 会议
- 计忆 → 记忆
- 设制 → 设置

## 7. 与快照的差异
| uid | memory_key | snapshot_value | event_value | 状态 |
|-----|-----------|---------------|-------------|------|
| u001 | output_style | `简洁、少废话` | `输出详细版，带数据表格` | 差异（以最新事件为准） |
| u001 | output_style | `详细版、带数据表格` | `输出详细版，带数据表格` | 差异（以最新事件为准） |
| u002 | emoji_policy | `允许` | `回复不要使用 emoji` | 差异（以最新事件为准） |
| u002 | emoji_policy | `禁用` | `回复不要使用 emoji` | 差异（以最新事件为准） |
| u003 | driver_update_entry | `系统更新` | `驱动更新入口是驱动管理器` | 差异（以最新事件为准） |
| u003 | driver_update_entry | `驱动管理器` | `驱动更新入口是驱动管理器` | 差异（以最新事件为准） |
| u005 | meeting_minutes_format | `三段式：背景、决定、待办` | `今天这次用 bullet 列表` | 差异（以最新事件为准） |
| u005 | meeting_minutes_format | `bullet 列表` | `今天这次用 bullet 列表` | 差异（以最新事件为准） |
| u006 | phone | `139****1111` | — | snapshot 单独存在 |
| u007 | answer_style | `先结论后步骤，不要太长` | `回答需要详细解释，每一步写原因。` | 差异（以最新事件为准） |
| u007 | answer_style | `详细解释，每一步写原因` | `回答需要详细解释，每一步写原因。` | 差异（以最新事件为准） |