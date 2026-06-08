package com.camp.langchain4j;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 训练营 LangChain4j 启动类
 *
 * 启动: mvn spring-boot:run
 *
 * 验收接口:
 *   curl "http://localhost:8080/api/health"
 *   curl "http://localhost:8080/api/chat?q=你好"
 *   curl -X POST http://localhost:8080/api/chat/preference \
 *     -H "Content-Type: application/json" \
 *     -d '{"question":"写一段月报摘要","preference":"简洁、少废话"}'
 *
 * 默认走本地 Ollama (qwen2.5:7b);
 * 切换云端: $env:CAMP_LLM_PROVIDER="openai" ; $env:OPENAI_API_KEY="sk-..."
 *
 * CORS: 允许所有来源 (训练营开发用, 生产应限白名单)
 */
@SpringBootApplication
public class CampLangchain4jApplication {

    public static void main(String[] args) {
        SpringApplication.run(CampLangchain4jApplication.class, args);
        System.out.println("========================================");
        System.out.println("  Camp LangChain4j Started on :8080");
        System.out.println("  GET  /api/health");
        System.out.println("  GET  /api/chat?q=...");
        System.out.println("  POST /api/chat/preference");
        System.out.println("========================================");
    }
}
