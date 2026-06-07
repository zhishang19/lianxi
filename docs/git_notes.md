# Git 学习笔记

> 训练营任务: Git 工程规范 (20 分) + Git 笔试 (巩固综合验收 25 分)
> 整理日期: 2026-06-07
> 学员: 藏世杰

---

## 1. 为什么要学 Git？

训练营老师反复强调: **代码要能自己讲清楚**。Git 不仅是"存代码"的工具，更是：
- **版本快照** — 每次提交就是一次可回退的"存档点"
- **责任追溯** — `git log` 能告诉老师"这段代码什么时候加的、为什么加"
- **协作语言** — `branch / merge / rebase` 是和队友对话的词汇

---

## 2. 9 个核心命令（训练营必会）

| 命令 | 作用 | 示例 |
|------|------|------|
| `git init` | 初始化本地仓库 | `git init` |
| `git clone <url>` | 克隆远程仓库 | `git clone https://github.com/xxx/lianxi.git` |
| `git status` | 查看工作区状态 | `git status` |
| `git add <file>` | 暂存文件 | `git add .` 或 `git add raw/d2/` |
| `git commit -m "msg"` | 提交到本地仓库 | `git commit -m "stage1: 初始化"` |
| `git log --oneline` | 查看提交历史 | `git log --oneline -10` |
| `git branch <name>` | 创建分支 | `git branch feature/d4` |
| `git checkout <name>` | 切换分支 | `git checkout main` |
| `git merge <name>` | 合并分支 | `git merge --no-ff feature/d4` |

### 状态流转图

```
工作区(working tree)
    │  git add <file>
    ▼
暂存区(staging area / index)
    │  git commit -m "msg"
    ▼
本地仓库(local repo)
    │  git push origin main
    ▼
远程仓库(remote repo / origin)
```

---

## 3. .gitignore 的"三件套"

我项目的 [.gitignore](file:///d:/藏数据/.gitignore) 覆盖了 3 类高频污染文件:

```gitignore
# 1. Python 编译缓存 (每次运行都会生成, 绝不入库)
__pycache__/
*.py[cod]
*$py.class

# 2. 虚拟环境 (每人路径不同, 体积巨大)
venv/
.venv/
env/

# 3. IDE 配置 (个人偏好, 不应污染团队)
.vscode/
.idea/
*.swp

# 4. 大数据文件 (我额外加的, 防止 raw/generated 撑爆仓库)
raw/generated/d*/
*.db
```

> **为什么 `raw/generated/` 要忽略?**
> 这是批量生成的 5 万条测试数据, 单次提交会有几十 MB。代码 (`.py`) 入库, 数据 (`.jsonl`) 留本地, 老师要看时再生成。

---

## 4. 分支策略: 为什么需要分支？

### 场景: 我在做 D4 多源清洗时, 发现 D2 的合并脚本有 bug

**错误做法**: 直接在 main 上改 D2 脚本, 改到一半发现 D4 也跑不通了, 回滚困难。

**正确做法**:
```bash
# 1. 切到 main, 拉最新
git checkout main
git pull

# 2. 从 main 开新分支修 D2 bug
git checkout -b fix/d2-time-pipeline

# 3. 修复并提交
git add raw/d2/merge_day2.py
git commit -m "fix: 修正 D2 时间解析的第3层 dateutil 误判"

# 4. 切回 main, 把修复合并回来
git checkout main
git merge --no-ff fix/d2-time-pipeline
```

**`--no-ff` 的含义**: 即使是 fast-forward 合并, 也强制生成一个 merge commit, 保留"分支做过这件事"的历史痕迹。

### 我的项目用分支做了什么

```
main
 └── feature/cleanup-enhance
      └── commit: 选做加分 (字段校验 + clean.log)
```

我开了一个 `feature/cleanup-enhance` 分支来开发选做加分项, 主分支保持稳定可用。

---

## 5. 4 个常见报错与修复

| 报错 | 原因 | 修复 |
|------|------|------|
| `fatal: not a git repository` | 当前目录不是 git 仓库 | `cd` 到仓库根目录, 或 `git init` |
| `error: failed to push some refs` | 远程有本地没有的提交 | `git pull --rebase` 后再 push |
| `CONFLICT (content): Merge conflict` | 同一文件两边都改了 | 打开文件, 手动选 `<<<<<<<` 之间的内容, 再 `git add` + `git commit` |
| `Permission denied (publickey)` | SSH 密钥未配置 | 用 HTTPS 协议 + Personal Access Token, 或 `ssh-keygen` 生成密钥 |

---

## 6. 实战: 我用 Git 做了 4 次提交

```
715d272 (HEAD -> main, origin/main) merge: 集成选做加分项 (字段校验 + clean.log)
eea2c32 stage3: 添加 D1-D6 说明文档
9cde733 stage2: 提交 D2-D6 全部清洗脚本与数据
bb99fd7 stage1: 初始化项目 - hello.py + README
```

每次提交都符合训练营要求:
- **commit message 格式**: `<type>: <subject>` (Conventional Commits)
- **单一职责**: 一次提交只做一件事
- **可读性**: 老师 5 秒能看懂这次提交改了什么

---

## 7. 推送到 GitHub 的两种认证方式

| 方式 | 命令 | 适用场景 |
|------|------|---------|
| HTTPS + Token | `https://<token>@github.com/xxx/lianxi.git` | 临时推送, 不想配 SSH |
| SSH 密钥 | `git@github.com:xxx/lianxi.git` | 长期开发, 推送频繁 |

我用的是 HTTPS + Personal Access Token, 因为训练营电脑重装后 SSH 密钥会丢, Token 可以重新生成。

---

## 8. 老师可能问的 5 个问题（自检）

1. **`git pull` 和 `git fetch` 有什么区别?**
   → `fetch` 只下载, 不合并; `pull` = fetch + merge。训练营里推荐 `git pull --rebase`, 保持线性历史。

2. **`git reset` 和 `git revert` 有什么区别?**
   → `reset` 改写历史 (危险的, 已推送的不能用); `revert` 生成新提交抵消旧提交 (安全的)。

3. **`.gitignore` 写错了, 文件已经入库了怎么办?**
   → `git rm --cached <file>` (注意加 `--cached`, 不会删本地文件), 然后再 commit。

4. **怎么撤销还没 commit 的修改?**
   → `git checkout -- <file>` (旧版) / `git restore <file>` (新版)。`git restore --staged <file>` 撤销 `git add`。

5. **merge 和 rebase 选哪个?**
   → 团队协作: 永远 merge (保留历史); 个人分支: 可以 rebase (历史更线性)。训练营演示用 merge 即可。

---

## 9. 训练营实战 checklist

- [x] 本地仓库 ≥ 2 次提交 (我做了 4 次)
- [x] .gitignore 覆盖 venv / pycache / .env / IDE
- [x] commit message 简洁有意义
- [x] 至少演示一次分支合并
- [x] 代码能 push 到 GitHub 并被老师看到

---

> **总结**: Git 不是"会用 add/commit/push 就完事", 而是要会用 `branch` 隔离风险, 用 `merge` 整合成果, 用 `log` 讲故事。
