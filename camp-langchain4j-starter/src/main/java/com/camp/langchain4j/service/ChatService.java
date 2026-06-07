package com.camp.langchain4j.service;

import dev.langchain4j.model.chat.ChatLanguageModel;
import org.springframework.stereotype.Service;

/**
 * ChatService - 业务封装层
 *
 * 训练营扩展点: 在这里加 RAG / Memory / Tool Calling
 */
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
