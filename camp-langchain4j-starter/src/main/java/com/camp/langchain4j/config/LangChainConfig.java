package com.camp.langchain4j.config;

import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.dashscope.QwenChatModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * LangChain4j 配置 - 注册大模型 Bean
 *
 * 训练营推荐: 通义千问 qwen-turbo (速度快, 免费额度够用)
 * 也可改成: OpenAI GPT-3.5 / DeepSeek / Ollama 本地模型
 */
@Configuration
public class LangChainConfig {

    @Value("${langchain4j.dashscope.api-key:}")
    private String apiKey;

    @Bean
    public ChatLanguageModel chatLanguageModel() {
        if (apiKey == null || apiKey.isBlank()) {
            throw new IllegalStateException(
                "未配置 DASHSCOPE_API_KEY, 请在 .env 中设置后重启");
        }
        return QwenChatModel.builder()
                .apiKey(apiKey)
                .modelName("qwen-turbo")
                .build();
    }
}
