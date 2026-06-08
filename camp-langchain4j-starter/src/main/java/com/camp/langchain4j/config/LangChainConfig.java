package com.camp.langchain4j.config;

import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.ollama.OllamaChatModel;
import dev.langchain4j.model.openai.OpenAiChatModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * LangChain4j 配置 - 二选一注册大模型 Bean
 *
 * 切换后端只需改环境变量 CAMP_LLM_PROVIDER (ollama / openai)
 * Ollama: 集训机房本地 qwen2.5:7b, 无需 API Key
 * OpenAI: 兼容 OpenAI/DeepSeek 等云端接口, 需 OPENAI_API_KEY
 */
@Configuration
public class LangChainConfig {

    @Value("${camp.llm.provider:ollama}")
    private String provider;

    // --- Ollama 配置 ---
    @Value("${camp.llm.ollama.base-url:http://localhost:11434}")
    private String ollamaBaseUrl;

    @Value("${camp.llm.ollama.model-name:qwen2.5:7b}")
    private String ollamaModelName;

    // --- OpenAI 配置 ---
    @Value("${camp.llm.openai.api-key:}")
    private String openaiApiKey;

    @Value("${camp.llm.openai.base-url:https://api.openai.com/v1}")
    private String openaiBaseUrl;

    @Value("${camp.llm.openai.model-name:gpt-3.5-turbo}")
    private String openaiModelName;

    @Bean
    public ChatLanguageModel chatLanguageModel() {
        if ("openai".equalsIgnoreCase(provider)) {
            if (openaiApiKey == null || openaiApiKey.isBlank()) {
                throw new IllegalStateException(
                    "CAMP_LLM_PROVIDER=openai 但未配置 OPENAI_API_KEY");
            }
            return OpenAiChatModel.builder()
                    .apiKey(openaiApiKey)
                    .baseUrl(openaiBaseUrl)
                    .modelName(openaiModelName)
                    .build();
        }

        // 默认 Ollama
        return OllamaChatModel.builder()
                .baseUrl(ollamaBaseUrl)
                .modelName(ollamaModelName)
                .build();
    }
}
