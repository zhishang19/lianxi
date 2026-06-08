package com.camp.langchain4j.service;

import dev.langchain4j.model.chat.ChatLanguageModel;
import org.springframework.stereotype.Service;

/**
 * ChatService - 业务封装层
 *
 * 训练营扩展点: 在这里加 RAG / Memory / Tool Calling
 *
 * BUG-9 修复: 业务层抛 IllegalArgumentException, 配合 GlobalExceptionHandler 返回 400
 * BUG-14 修复: preference 截断 + 去掉换行, 防 prompt 注入
 */
@Service
public class ChatService {

    private static final int MAX_QUESTION_LEN = 2000;
    private static final int MAX_PREFERENCE_LEN = 500;

    private final ChatLanguageModel model;

    public ChatService(ChatLanguageModel model) {
        this.model = model;
    }

    /** D7 必做: 简单问答 */
    public String chat(String question) {
        if (question == null || question.isBlank()) {
            throw new IllegalArgumentException("question 不能为空");
        }
        if (question.length() > MAX_QUESTION_LEN) {
            throw new IllegalArgumentException("question 长度不能超过 " + MAX_QUESTION_LEN);
        }
        return model.chat(question);
    }

    /** D7 A 轨: 带用户偏好的问答 (把偏好塞进 system prompt) */
    public String chatWithPreference(String question, String preference) {
        if (question == null || question.isBlank()) {
            throw new IllegalArgumentException("question 不能为空");
        }
        if (question.length() > MAX_QUESTION_LEN) {
            throw new IllegalArgumentException("question 长度不能超过 " + MAX_QUESTION_LEN);
        }
        // preference 截断 + 去换行, 防 prompt 注入
        String raw = (preference == null || preference.isBlank()) ? "无特殊偏好" : preference;
        String safe = raw.length() > MAX_PREFERENCE_LEN ? raw.substring(0, MAX_PREFERENCE_LEN) : raw;
        safe = safe.replace("\n", " ").replace("\r", " ");
        String prompt = String.format(
            "请严格按以下用户偏好回答: 【%s】\n用户问题: %s",
            safe, question
        );
        return model.chat(prompt);
    }
}
