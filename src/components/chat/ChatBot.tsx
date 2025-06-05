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
}

export const ChatBot = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingText, setThinkingText] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    const savedSessionId = localStorage.getItem("chatSessionId");
    if (savedSessionId) setSessionId(savedSessionId);
  }, []);

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

      const response = await fetch(
        "https://eefb-140-113-169-2.ngrok-free.app/api/chat",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }
      );

      clearInterval(intervalId);
      setIsThinking(false);
      setThinkingText("");

      if (!response.ok) throw new Error("Network error");

      const data = await response.json();

      if (data.session_id) {
        setSessionId(data.session_id);
        localStorage.setItem("chatSessionId", data.session_id);
      }

      if (data.thinking) {
        setMessages((prev) => [
          ...prev,
          {
            text: data.thinking,
            isUser: false,
            timestamp: new Date().toLocaleTimeString(),
            isThinking: true,
          },
        ]);
      }

      setMessages((prev) => [
        ...prev,
        {
          text: data.response,
          isUser: false,
          timestamp: new Date().toLocaleTimeString(),
          _id: data.message_id, // Backend must send this!
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
          text: "Error fetching response",
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
      await fetch("https://eefb-140-113-169-2.ngrok-free.app/api/chat/rate", {
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
      fetch("https://eefb-140-113-169-2.ngrok-free.app/api/memory/clear", {
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
    <div className="fixed bottom-4 right-4 w-[380px] shadow-xl rounded-xl overflow-hidden bg-gray-50">
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
