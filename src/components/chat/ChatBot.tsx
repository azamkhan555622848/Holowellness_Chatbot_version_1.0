/** @format */

import React, { useState, useEffect } from "react";
import { ChatHeader } from "./ChatHeader";
import { ChatMessage } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { ThinkingBar } from "../ThinkingBar";

interface Message {
  _id?: string; // message_id from backend
  text: string;
  isUser: boolean;
  timestamp: string;
  isThinking?: boolean;
  rating?: number; // 1-5, or undefined
  thinking?: string; // AI thinking process
  retrievedContext?: string; // Retrieved context from documents
}

export const ChatBot = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingText, setThinkingText] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [expandedThinking, setExpandedThinking] = useState<{[key: number]: boolean}>({});
  const [expandedContext, setExpandedContext] = useState<{[key: number]: boolean}>({});

  useEffect(() => {
    const savedSessionId = localStorage.getItem("chatSessionId");
    if (savedSessionId) setSessionId(savedSessionId);
  }, []);

  // Basic fetch with timeout and simple retry for transient 502/504
  const fetchWithRetry = async (
    input: RequestInfo | URL,
    init: RequestInit,
    options: { timeoutMs?: number; retries?: number; backoffMs?: number } = {}
  ): Promise<Response> => {
    const timeoutMs = options.timeoutMs ?? 20000;
    let retries = options.retries ?? 2;
    const backoffMs = options.backoffMs ?? 800;

    // eslint-disable-next-line no-constant-condition
    while (true) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetch(input, { ...init, signal: controller.signal });
        clearTimeout(timer);
        if (res.ok) return res;
        // Retry on gateway errors
        if ((res.status === 502 || res.status === 504) && retries > 0) {
          await new Promise((r) => setTimeout(r, backoffMs));
          retries -= 1;
          continue;
        }
        return res;
      } catch (err) {
        clearTimeout(timer);
        // Network error or timeout → retry if budget remains
        if (retries > 0) {
          await new Promise((r) => setTimeout(r, backoffMs));
          retries -= 1;
          continue;
        }
        throw err;
      }
    }
  };

  const handleSendMessage = async (message: string) => {
    setMessages((prev) => [
      ...prev,
      {
        text: message,
        isUser: true,
        timestamp: new Date().toLocaleTimeString(),
      },
    ]);

    setIsThinking(true);
    setThinkingText("");
    let dots = 0;
    const intervalId = setInterval(() => {
      dots = (dots + 1) % 4;
      setThinkingText(".".repeat(dots));
    }, 500);

    try {
      const payload: any = {
        query: message,
        user_id: "68368fff90e7c4615a08a719", // Change to your logic
      };
      if (sessionId) payload.session_id = sessionId;

      const response = await fetchWithRetry(
        "/api/chat",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
        { timeoutMs: 45000, retries: 3, backoffMs: 1200 }
      );

      clearInterval(intervalId);
      setIsThinking(false);
      setThinkingText("");

      if (!response.ok) {
        let errorDetail = `HTTP ${response.status}`;
        try {
          const errorData = await response.json();
          if (errorData?.error) {
            errorDetail = errorData.error;
          }
        } catch {
          // Failed to parse error JSON, keep HTTP status
        }
        throw new Error(errorDetail);
      }

      const data = await response.json();

      if (data.session_id) {
        setSessionId(data.session_id);
        localStorage.setItem("chatSessionId", data.session_id);
      }

      setMessages((prev) => [
        ...prev,
        {
          text: data.response,
          isUser: false,
          timestamp: new Date().toLocaleTimeString(),
          _id: data.message_id, // Backend must send this!
          thinking: data.thinking,
          retrievedContext: data.retrieved_context,
        },
      ]);
    } catch (error) {
      console.error("❌ Chat error:", error);
      clearInterval(intervalId);
      setIsThinking(false);
      setThinkingText("");
      setMessages((prev) => [
        ...prev,
        {
          text: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
          isUser: false,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    }
  };

  const handleReactToMessage = async (
    messageId: string,
    starRating: number
  ) => {
    try {
      await fetch("/api/chat/rate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: messageId, rating: starRating }),
      });

      setMessages((prev) =>
        prev.map((msg) =>
          msg._id === messageId
            ? { ...msg, rating: starRating || undefined }
            : msg
        )
      );
    } catch (err) {
      console.error("❌ Failed to rate message:", err);
    }
  };

  const clearConversation = (force?: boolean | React.MouseEvent) => {
    const realForce = typeof force === "boolean" ? force : false;

    if (sessionId) {
      fetch("/api/memory/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      })
        .then(() => {
          setMessages([]);
          setSessionId(null);
          localStorage.removeItem("chatSessionId");
        })
        .catch((error) => console.error("❌ Error clearing memory:", error));
    } else {
      setMessages([]);
    }
  };

  return (
    <div className="fixed bottom-4 right-4 w-[480px] max-w-[90vw] shadow-xl rounded-xl overflow-hidden bg-gray-50">
      <ChatHeader
        userName="Artur Beterbiev"
        userImage="/lovable-uploads/320d61e5-9a63-4856-887a-7ac4bd694b9b.png"
        isOnline={true}
        onMinimize={() => console.log("Minimize")}
        onSettings={clearConversation}
      />

      <div className="h-[400px] overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <div key={index} className="space-y-1">
            <ChatMessage
              message={message.text}
              isUser={message.isUser}
              timestamp={message.timestamp}
              isThinking={message.isThinking}
            />

            {/* Show thinking process for AI responses */}
            {!message.isUser && message.thinking && (
              <div className="ml-2 mt-2 bg-blue-50 rounded-md border border-blue-200">
                <button
                  onClick={() => setExpandedThinking(prev => ({...prev, [index]: !prev[index]}))}
                  className="w-full flex items-center justify-between p-2 text-xs font-semibold text-blue-700 hover:bg-blue-100 rounded-t-md"
                >
                  <span>🤔 View thinking process</span>
                  <span className={`transform transition-transform ${expandedThinking[index] ? 'rotate-180' : ''}`}>
                    ▼
                  </span>
                </button>
                {expandedThinking[index] && (
                  <div className="p-3 pt-0 text-xs text-blue-600 whitespace-pre-wrap border-t border-blue-200">
                    {message.thinking}
                  </div>
                )}
              </div>
            )}

            {/* Show retrieved context for AI responses */}
            {!message.isUser && message.retrievedContext && (
              <div className="ml-2 mt-2 bg-green-50 rounded-md border border-green-200">
                <button
                  onClick={() => setExpandedContext(prev => ({...prev, [index]: !prev[index]}))}
                  className="w-full flex items-center justify-between p-2 text-xs font-semibold text-green-700 hover:bg-green-100 rounded-t-md"
                >
                  <span>📚 View retrieved sources</span>
                  <span className={`transform transition-transform ${expandedContext[index] ? 'rotate-180' : ''}`}>
                    ▼
                  </span>
                </button>
                {expandedContext[index] && (
                  <div className="p-3 pt-0 text-xs text-green-600 whitespace-pre-wrap max-h-48 overflow-y-auto border-t border-green-200">
                    {message.retrievedContext}
                  </div>
                )}
              </div>
            )}

            {/* Show rating stars for every AI response */}
            {!message.isUser && message._id && (
              <div className="flex items-center gap-1 ml-2 mt-1 text-base">
                <span className="text-sm text-gray-400">Rate:</span>
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    onClick={() =>
                      handleReactToMessage(
                        message._id!,
                        message.rating === star ? 0 : star
                      )
                    }
                    className={`hover:scale-125 transition ${
                      message.rating && message.rating >= star
                        ? "text-yellow-500"
                        : "text-gray-300"
                    }`}
                    title={`Rate ${star}`}>
                    ★
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {isThinking && <ThinkingBar text={thinkingText} />}
      </div>

      <ChatInput onSendMessage={handleSendMessage} />
    </div>
  );
};
