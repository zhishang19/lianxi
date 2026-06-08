package com.camp.langchain4j.controller;

import com.camp.langchain4j.service.ChatService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 训练营 D7 验收接口
 *
 * - GET  /api/health            健康检查 (必做)
 * - GET  /api/chat?q=...        简单问答 (D7 必做)
 * - POST /api/chat/preference   带偏好的问答 (D7 A 轨加做)
 *   请求体: {"question":"...","preference":"..."}
 */
@RestController
@RequestMapping("/api")
public class ChatController {

    private final ChatService chatService;

    public ChatController(ChatService chatService) {
        this.chatService = chatService;
    }

    @GetMapping("/health")
    public String health() {
        return "ok";
    }

    @GetMapping("/chat")
    public Map<String, String> chat(@RequestParam("q") String question) {
        String answer = chatService.chat(question);
        return Map.of("question", question, "answer", answer);
    }

    @PostMapping("/chat/preference")
    public Map<String, String> chatWithPreference(@RequestBody ChatPreferenceRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("请求体不能为空");
        }
        String answer = chatService.chatWithPreference(request.question(), request.preference());
        return Map.of(
                "question", request.question() == null ? "" : request.question(),
                "preference", request.preference() == null ? "" : request.preference(),
                "answer", answer
        );
    }

    /** A 轨请求体 */
    public record ChatPreferenceRequest(String question, String preference) {}
}
