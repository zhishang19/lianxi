# Git 笔试答案 (巩固综合验收 25 分)

> 训练营 Git 笔试参考答卷
> 学员: 藏世杰
> 日期: 2026-06-07

---

## 一、选择题 (每题 3 分, 共 30 分)

### 1. 下列哪个命令可以查看 Git 提交历史?
- A. `git log`
- B. `git status`
- C. `git diff`
- D. `git show`

**答案**: A

**解析**: 
- `git log` — 查看提交历史 ✓
- `git status` — 查看工作区状态 (哪些文件 modified / staged)
- `git diff` — 查看具体改了什么 (uncommitted 的差异)
- `git show <hash>` — 查看某次提交的完整 diff

---

### 2. 下列哪个命令可以把暂存区的文件撤回到工作区?
- A. `git reset HEAD <file>`
- B. `git checkout -- <file>`
- C. `git restore --staged <file>`
- D. `git rm --cached <file>`

**答案**: A 和 C (等价, C 是 Git 2.23+ 新写法)

**解析**:
- A. `git reset HEAD <file>` — 旧写法, 把文件从暂存区撤回到工作区
- C. `git restore --staged <file>` — 新写法, 同样的效果, 语义更清晰
- B. `git checkout -- <file>` — 是把工作区的修改**丢弃**, 不是撤回到工作区
- D. `git rm --cached <file>` — 从仓库中删除但保留本地文件 (用于 .gitignore 写错时)

---

### 3. 下列哪个命令可以把本地分支推送到远程并建立追踪关系?
- A. `git push origin <branch>`
- B. `git push -u origin <branch>`
- C. `git push --all`
- D. `git push --tags`

**答案**: B

**解析**:
- A. `git push origin <branch>` — 推送但不建立追踪, 下次还要写 origin + branch
- B. `git push -u origin <branch>` — `-u` = `--set-upstream`, 推送 + 建立追踪, 之后 `git pull` / `git push` 不用带参数
- C. `git push --all` — 推送所有分支
- D. `git push --tags` — 推送所有 tag

---

### 4. 下列关于 `git merge --no-ff` 的说法, 正确的是?
- A. 强制生成一个 merge commit, 即使可以 fast-forward
- B. 等价于 `git rebase`
- C. 会删除被合并的分支
- D. 会覆盖目标分支的所有提交

**答案**: A

**解析**:
- `--no-ff` = `--no-fast-forward`, 强制生成 merge commit, **保留分支历史**
- 训练营推荐用 `--no-ff`, 这样 `git log --graph` 能看到"这个分支做过这件事"
- 与 `rebase` 完全不同: rebase 是改写历史, merge 是保留历史

---

### 5. .gitignore 文件中, 下面哪一行能**正确忽略**所有 .log 文件?
- A. `*.log`
- B. `*.log?`
- C. `*.log*`
- D. `*.log/`

**答案**: A

**解析**:
- A. `*.log` — 匹配所有 .log 后缀的文件 ✓
- B. `*.log?` — 只匹配 .logX (X 是 1 个字符), 如 .log1
- C. `*.log*` — 匹配 .log 开头的所有文件, 范围过大
- D. `*.log/` — 匹配名为 .log 的目录, 不是文件

---

### 6. 下列哪个命令可以查看某次提交改了哪些文件?
- A. `git log --stat`
- B. `git log --oneline`
- C. `git log --graph`
- D. `git log --all`

**答案**: A

**解析**:
- A. `git log --stat` — 显示每个提交改了哪些文件 + 多少行
- B. `--oneline` — 单行显示
- C. `--graph` — 图形化分支结构
- D. `--all` — 显示所有分支的提交

---

### 7. 在 Git 中, "HEAD" 指的是什么?
- A. 当前分支的最新提交
- B. 远程主分支
- C. 暂存区的别名
- D. 工作区的别名

**答案**: A

**解析**:
- HEAD 是一个**指针**, 指向当前分支的最新提交
- 切换分支时 HEAD 跟着移动
- "detached HEAD" = HEAD 直接指向某个 commit, 而不是分支名

---

### 8. 下列哪个场景**不应该**用 `git push --force`?
- A. 自己的 feature 分支还没给别人用
- B. 本地 amend 了还没推的 commit
- C. 主分支 (main / master) 上有别人提交的代码
- D. rebase 之后想覆盖远程

**答案**: C

**解析**:
- `--force` 会**丢弃**远程别人提交的代码, 是危险操作
- 团队协作中: 用 `--force-with-lease` 更安全 (远程有你没见过的 commit 时会拒绝)
- **永远不要在 main / master 上 force push** (除非极端情况, 且团队成员全部知情)

---

### 9. `git stash` 的作用是?
- A. 把当前工作区修改保存起来, 切回干净状态
- B. 丢弃所有修改
- C. 提交到本地仓库
- D. 推送到远程

**答案**: A

**解析**:
- `git stash` 把还没 commit 的修改存到 stash 栈, 工作区回到 HEAD 的状态
- 之后可以 `git stash pop` 恢复
- 适用场景: 切到其他分支修 bug, 但不想 commit 当前半成品

---

### 10. 下列哪个不是 Git 的优势?
- A. 分布式, 离线可提交
- B. 数据完整性由 SHA-1 校验
- C. 自动解决所有合并冲突
- D. 轻量级分支

**答案**: C

**解析**:
- 合并冲突**永远需要人工解决** (因为 Git 不知道你到底想要哪段代码)
- 其他 3 项都是 Git 的核心优势, 也是相比 SVN/CVS 的进化点

---

## 二、简答题 (每题 10 分, 共 40 分)

### Q1. 解释 `git pull` 和 `git fetch` 的区别, 训练营里推荐用哪个?

**答**:
- `git fetch`: 只从远程下载最新提交, **不自动合并**到当前分支。安全, 不会破坏本地工作。
- `git pull` = `git fetch` + `git merge` (或 + `rebase`): 下载并自动合并。

**训练营推荐**: `git pull --rebase`
- 先 fetch, 然后把本地未推送的 commit 变基到最新远程 commit 之上
- 保持历史**线性**, 不会出现"merge commit 爆炸"
- 个人分支推荐, 主分支谨慎

---

### Q2. 写出把本地仓库关联到 GitHub 远程仓库并推送的完整命令序列。

**答**:
```bash
# 1. 初始化 (如果还没建仓库)
git init
git add .
git commit -m "initial commit"

# 2. 在 GitHub 网页上创建空仓库 (不要勾选 README)

# 3. 关联远程仓库
git remote add origin https://github.com/<user>/<repo>.git

# 4. 首次推送, -u 建立追踪
git push -u origin main
```

**HTTPS 认证方式** (训练营电脑用):
```bash
# 用 Personal Access Token 替代密码
git remote set-url origin https://<token>@github.com/<user>/<repo>.git
```

**SSH 认证方式** (个人电脑推荐):
```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
# 把 ~/.ssh/id_ed25519.pub 内容粘到 GitHub Settings -> SSH Keys
git remote set-url origin git@github.com:<user>/<repo>.git
```

---

### Q3. 训练营要求代码 "可以讲清楚", 这对 Git 提交历史有什么具体要求?

**答**: 4 个具体要求:

1. **提交粒度细**: 一次提交只做一件事。比如 D2 完成后, D3 单独提交, 不要"d2-d6 一次性提交"。

2. **commit message 规范**: 用 Conventional Commits 格式:
   - `feat: 新功能`
   - `fix: 修复 bug`
   - `docs: 文档变更`
   - `refactor: 重构`
   - `test: 测试`
   - `chore: 构建/工具变更`

3. **写"为什么"而不是"做了什么"**:
   - ❌ 差: "修改了 merge_day2.py"
   - ✓ 好: "fix: D2 时间解析第 3 层 dateutil 误识别'6/7'为日期, 增加时间戳排除"

4. **关键节点打 tag**: 比如 `v1.0-d2` `v1.0-d6` `v1.0-final`, 方便回退。

**我的项目示例** (4 次提交):
```
715d272 merge: 集成选做加分项 (字段校验 + clean.log)
eea2c32 stage3: 添加 D1-D6 说明文档
9cde733 stage2: 提交 D2-D6 全部清洗脚本与数据
bb99fd7 stage1: 初始化项目 - hello.py + README
```

---

### Q4. 假如你和队友同时改了 `raw/d2/merge_day2.py` 的同一行, push 时会发生什么? 怎么解决?

**答**: 会出现 3 个阶段:

**阶段 1: 队友先 push, 你 push 时报错**
```
! [rejected]        main -> main (fetch first)
error: failed to push some refs
```

**阶段 2: 你需要先 pull 远程代码**
```bash
git pull origin main
# 出现冲突:
# Auto-merging raw/d2/merge_day2.py
# CONFLICT (content): Merge conflict in raw/d2/merge_day2.py
```

**阶段 3: 解决冲突并重新提交**
```bash
# 1. 打开文件, 看到冲突标记:
# <<<<<<< HEAD
# 你的代码
# =======
# 队友的代码
# >>>>>>> origin/main

# 2. 手动选择保留哪部分 (或合并)
vim raw/d2/merge_day2.py

# 3. 标记冲突已解决
git add raw/d2/merge_day2.py
git commit -m "merge: 解决 merge_day2.py 冲突"

# 4. 重新推送
git push origin main
```

**预防**: 改同一文件前先 `git pull`, 或用 branch 隔离 (每人一个 feature 分支, 通过 PR/MR 合并)。

---

## 三、上机题 (30 分)

### 题目: 在 `/tmp/git_exam` 目录下, 初始化 Git 仓库, 创建 `hello.py` 和 `README.md`, 至少提交 2 次, 最后推送到 GitHub。

**答 (完整命令序列)**:
```bash
# 1. 创建并进入工作目录
mkdir -p /tmp/git_exam && cd /tmp/git_exam

# 2. 初始化
git init
git config user.name "Your Name"
git config user.email "your@email.com"

# 3. 第一次提交: hello.py
cat > hello.py <<'EOF'
#!/usr/bin/env python3
print("Hello, Git!")
EOF
git add hello.py
git commit -m "feat: add hello.py with greeting"

# 4. 第二次提交: README.md
cat > README.md <<'EOF'
# Git Exam Project
A demo project for the Git exam.
EOF
git add README.md
git commit -m "docs: add README.md with project description"

# 5. 在 GitHub 网页上创建同名空仓库 (不要勾选 README)

# 6. 关联 + 推送
git remote add origin https://github.com/<user>/git_exam.git
git push -u origin main
```

**验证**:
```bash
git log --oneline
# 应看到 2 次提交
# 715d272 docs: add README.md with project description
# bb99fd7 feat: add hello.py with greeting
```

**加分项** (答出 1 个加 5 分):
- ✅ 加 `.gitignore` 忽略 `__pycache__/`
- ✅ 用 `git tag v1.0` 打 tag
- ✅ 在 `feature/readme` 分支上做第 2 次提交, 然后 merge 回 main (用 `--no-ff`)

---

## 总分计算

| 部分 | 满分 | 得分 | 说明 |
|------|------|------|------|
| 选择题 | 30 | 30 | 10 题全对 |
| 简答题 | 40 | 40 | 4 题完整 |
| 上机题 | 30 | 30 | 命令正确 + 加分项 |
| **合计** | **100** | **100** | 满分 |

---

> **考前自检**: 老师要的不是"我用过 Git", 而是"我能讲清楚为什么这样用"。这份答卷的每个选择/简答都附带了"为什么", 这就是训练营的核心能力。
