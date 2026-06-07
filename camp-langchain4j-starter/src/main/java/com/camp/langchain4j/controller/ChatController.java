package com.camp.langchain4j.controller;

import com.camp.langchain4j.service.ChatService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * /api/chat 接口
 *
 * 入参: {"message": "用户问题"}
 * 出参: 模型回复字符串
 */
@RestController
@RequestMapping("/api")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @PostMapping("/chat")
    public String chat(@RequestBody ChatRequest request) {
        if (request == null || request.message() == null || request.message().isBlank()) {
            return "错误: message 不能为空";
        }
        return chatService.chat(request.message());
    }

    /** 请求体 */
    public record ChatRequest(String message) {}
}
