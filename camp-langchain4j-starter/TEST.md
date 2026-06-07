# 训练营 LangChain4j 启动指南

## 1. 前置条件

| 工具 | 版本 | 安装 |
|------|------|------|
| JDK | 17+ | `java -version` 应输出 17.x |
| Maven | 3.8+ | `mvn -version` 应输出 3.8.x |
| 通义千问 API Key | — | https://dashscope.console.aliyun.com/apiKey |

## 2. 5 步跑起来

```bash
# Step 1: 进入项目
cd camp-langchain4j-starter

# Step 2: 复制环境变量
cp .env.example .env

# Step 3: 编辑 .env, 填入 DASHSCOPE_API_KEY
# 用记事本 / VSCode 打开 .env, 把 sk-your-real-key-here 替换成真 Key

# Step 4: 加载环境变量 (Windows PowerShell)
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
    }
}

# (Linux/macOS) 加载环境变量
# export $(cat .env | xargs)

# Step 5: 启动 Spring Boot
mvn spring-boot:run
```

看到 `Camp LangChain4j Started on :8080` 即启动成功。

## 3. 测试 /api/chat

打开另一个终端:

```bash
# Windows PowerShell
$body = @{ message = "你好, 请用一句话介绍你自己" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/chat -ContentType "application/json" -Body $body

# Linux/macOS
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好, 请用一句话介绍你自己"}'
```

期望返回: 一句自我介绍的字符串。

## 4. 常见报错

| 报错 | 原因 | 修复 |
|------|------|------|
| `DASHSCOPE_API_KEY is not set` | 没配置环境变量 | 检查 .env 是否加载 |
| `401 Unauthorized` | API Key 无效 | 重新申请, 注意带 `sk-` 前缀 |
| `Connection refused: no further information` | 网络问题 | 训练营电脑可能需要代理 |
| `port 8080 already in use` | 端口被占 | `application.yml` 改 `server.port` |
| `JAVA_HOME not found` | 没装 JDK | 训练营环境应该预装, 检查环境变量 |

## 5. 训练营扩展练习 (选做)

### 5.1 接入 RAG: 让模型回答训练营阶段二清洗出的知识
把 `raw/d4/knowledge.json` 转成向量存到内存, 检索后塞进 prompt。

### 5.2 接入 Memory: 记住用户上次问了什么
使用 `langchain4j` 的 `MessageWindowChatMemory` 维持 10 轮上下文。

### 5.3 接入 Tool: 让模型能调用计算器/天气 API
使用 `@Tool` 注解定义方法, 模型自动决定何时调用。

---

> **训练营红线**: API Key **绝不能**硬编码在 application.yml 或 Java 代码里, 必须从环境变量读, 且 `.env` 加入 `.gitignore`。
