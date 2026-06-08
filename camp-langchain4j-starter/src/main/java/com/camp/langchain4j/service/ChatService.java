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

    /** D7 必做: 简单问答 */
    public String chat(String question) {
        if (question == null || question.isBlank()) {
            return "错误: question 不能为空";
        }
        return model.chat(question);
    }

    /** D7 A 轨: 带用户偏好的问答 (把偏好塞进 system prompt) */
    public String chatWithPreference(String question, String preference) {
        if (question == null || question.isBlank()) {
            return "错误: question 不能为空";
        }
        String pref = (preference == null || preference.isBlank()) ? "无特殊偏好" : preference;
        String prompt = String.format(
            "请严格按以下用户偏好回答: 【%s】\n用户问题: %s",
            pref, question
        );
        return model.chat(prompt);
    }
}
