package com.camp.langchain4j;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 训练营 LangChain4j 启动类
 *
 * 启动: mvn spring-boot:run
 * 测试: curl -X POST http://localhost:8080/api/chat -H "Content-Type: application/json" -d '{"message":"你好"}'
 */
@SpringBootApplication
public class CampLangchain4jApplication {

    public static void main(String[] args) {
        SpringApplication.run(CampLangchain4jApplication.class, args);
        System.out.println("========================================");
        System.out.println("  Camp LangChain4j Started on :8080");
        System.out.println("  Try: POST /api/chat");
        System.out.println("========================================");
    }
}
