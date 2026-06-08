# D4 多源清洗报告

生成时间: 2026-06-08 09:36:22

## 1. 统计
- 对话: 15 条 / 7 session (SimHash去重)
- 知识: 6 个案例 (丢弃垃圾 0)
- 偏好: 8 个聚合 (冲突 3)
- 工具: 7 条 (去重 1)

## 2. 发现的隐私字段 (PrivacyMasker 增强脱敏)
- session=S103 uid=u004 -> 已增强脱敏
- session=S105 uid=u006 -> 已增强脱敏

## 3. DFA 敏感词命中
- session=S103 uid=u004: 检测到 forget 指令
- session=S105 uid=u006: 检测到 forget 指令
- session=S105 uid=u006: 检测到 forget 指令

## 4. 发现的冲突项
- **U002 emoji_policy**: 系统默认=允许 vs 用户明确=禁用 -> 用户优先
- **u001 output_style**: v1=简洁、少废话 vs v2=详细、带数据表格 -> v2 覆盖 v1
- **U002 emoji_policy**: 系统默认=允许 vs 用户明确=禁用 -> 用户优先
- **u003 driver_update_entry**: v1=系统更新 vs v2=驱动管理器 -> v2 覆盖 v1

## 5. needs_review 列表
- preferences.security_level: 缺 uid，scope=needs_review
- knowledge: 案例缺标题，疑似垃圾行
- knowledge['会义纪要偏好计忆']: 错别字 会义->会议; 计忆->记忆
- chat session=S100 uid=u001: 临时指令，scope=short
- chat session=S103 uid=u004: 触发 forget 指令 (DFA)
- chat session=S104 uid=U005: 临时指令，scope=short
- chat session=S105 uid=u006: 触发 forget 指令 (DFA)
- chat session=S105 uid=u006: 触发 forget 指令 (DFA)
- tools: trace=T-506 重复 2 次
