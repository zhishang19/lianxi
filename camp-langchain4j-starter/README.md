# camp-langchain4j-starter

> 训练营任务: LangChain4j (35 分) - 跑通 `/api/chat` 接口
> 这是一个**最小可运行**的 Spring Boot 3 + LangChain4j 1.x 模板
> 学员只需 clone → 配置 API Key → mvn spring-boot:run 即可

## 项目结构

```
camp-langchain4j-starter/
├── pom.xml                              # Maven 配置 (Spring Boot 3.3 + LangChain4j 1.0.0)
├── src/main/java/
│   └── com/camp/langchain4j/
│       ├── CampLangchain4jApplication.java   # 启动类
│       ├── controller/
│       │   └── ChatController.java           # /api/chat 控制器
│       ├── service/
│       │   └── ChatService.java              # LangChain4j 业务封装
│       └── config/
│           └── LangChainConfig.java          # 大模型 Bean 配置
├── src/main/resources/
│   └── application.yml                  # 配置文件 (含 API Key 占位符)
├── .env.example                         # 环境变量示例
├── README.md                            # 启动说明
└── TEST.md                              # 测试用例
```

## 快速开始

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 编辑 .env, 填入你的 DASHSCOPE_API_KEY (通义千问) 或 OPENAI_API_KEY
# 训练营推荐: 通义千问 (国内访问快, 新用户免费)
# DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx

# 3. 启动
mvn spring-boot:run

# 4. 测试
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好, 请用一句话介绍你自己"}'
```

## 核心依赖 (pom.xml 摘录)

```xml
<dependencies>
    <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
        <groupId>dev.langchain4j</groupId>
        <artifactId>langchain4j-spring-boot-starter</artifactId>
        <version>1.0.0-beta3</version>
    </dependency>
    <dependency>
        <groupId>dev.langchain4j</groupId>
        <artifactId>langchain4j-dashscope</artifactId>
        <version>1.0.0-beta3</version>
    </dependency>
</dependencies>
```

## 关键代码 (3 个文件)

### 1. `CampLangchain4jApplication.java` - 启动类
```java
package com.camp.langchain4j;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class CampLangchain4jApplication {
    public static void main(String[] args) {
        SpringApplication.run(CampLangchain4jApplication.class, args);
    }
}
```

### 2. `LangChainConfig.java` - 大模型 Bean
```java
package com.camp.langchain4j.config;

import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.dashscope.QwenChatModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class LangChainConfig {

    @Value("${langchain4j.dashscope.api-key}")
    private String apiKey;

    @Bean
    public ChatLanguageModel chatLanguageModel() {
        return QwenChatModel.builder()
                .apiKey(apiKey)
                .modelName("qwen-turbo")
                .build();
    }
}
```

### 3. `ChatController.java` - /api/chat 接口
```java
package com.camp.langchain4j.controller;

import com.camp.langchain4j.service.ChatService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping("/chat")
    public String chat(@RequestBody ChatRequest request) {
        return chatService.chat(request.message());
    }

    public record ChatRequest(String message) {}
}
```

### 4. `ChatService.java` - 业务封装
```java
package com.camp.langchain4j.service;

import dev.langchain4j.model.chat.ChatLanguageModel;
import org.springframework.stereotype.Service;

@Service
public class ChatService {

    private final ChatLanguageModel model;

    public ChatService(ChatLanguageModel model) {
        this.model = model;
    }

    public String chat(String message) {
        return model.generate(message);
    }
}
```

### 5. `application.yml` - 配置
```yaml
server:
  port: 8080

langchain4j:
  dashscope:
    api-key: ${DASHSCOPE_API_KEY:}

logging:
  level:
    dev.langchain4j: INFO
```

## 训练营验收清单

- [ ] 项目能 `mvn spring-boot:run` 起来, 不报错
- [ ] `curl /api/chat` 返回非空字符串
- [ ] `.env` 加入 `.gitignore`, API Key 没硬编码
- [ ] 在 `TEST.md` 记录 3 个测试用例的输入/输出
- [ ] 用 JDK 17 + Maven 3.8+ (训练营标准环境)
