import React, { useState, useEffect } from 'react';
import { ChatHeader } from './ChatHeader';
import { ChatMessage } from './ChatMessage';
import { ChatInput } from './ChatInput';
import { ThinkingBar } from '../ThinkingBar';

interface Message {
  text: string;
  isUser: boolean;
  timestamp: string;
  isThinking?: boolean;
}

export const ChatBot = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingText, setThinkingText] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Load session ID from localStorage on component mount
  useEffect(() => {
    const savedSessionId = localStorage.getItem('chatSessionId');
    if (savedSessionId) {
      setSessionId(savedSessionId);
    }
  }, []);

  const handleSendMessage = async (message: string) => {
    // Add user message
    setMessages(prev => [...prev, {
      text: message,
      isUser: true,
      timestamp: new Date().toLocaleTimeString()
    }]);

    // Start thinking indicator
    setIsThinking(true);
    setThinkingText("");
    let dots = 0;
    const intervalId = setInterval(() => {
      dots = (dots + 1) % 4;
      const dotStr = "".concat(".".repeat(dots));
      setThinkingText(dotStr);
    }, 500);

    try {
      const response = await fetch('https://eefb-140-113-169-2.ngrok-free.app/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
          query: message,
          session_id: sessionId 
        })
      });

      if (!response.ok) {
        throw new Error('Network error');
      }

      // Clear thinking indicator
      clearInterval(intervalId);
      setIsThinking(false);
      setThinkingText("");

      // Get complete response
      const data = await response.json();
      
      // Update session ID if provided by the server
      if (data.session_id) {
        setSessionId(data.session_id);
        localStorage.setItem('chatSessionId', data.session_id);
      }
      
      // Check if we have a thinking part
      if (data.thinking) {
        // Add thinking message first
        setMessages(prev => [...prev, {
          text: data.thinking,
          isUser: false,
          timestamp: new Date().toLocaleTimeString(),
          isThinking: true
        }]);
      }
      
      // Add the actual response
      setMessages(prev => [...prev, {
        text: data.response,
        isUser: false,
        timestamp: new Date().toLocaleTimeString()
      }]);

    } catch (error) {
      console.error(error);
      clearInterval(intervalId);
      setIsThinking(false);
      setThinkingText("");
      setMessages(prev => [...prev, {
        text: 'Error fetching response',
        isUser: false,
        timestamp: new Date().toLocaleTimeString()
      }]);
    }
  };

  // Function to clear the conversation and session
  const clearConversation = () => {
    if (sessionId) {
      fetch('https://eefb-140-113-169-2.ngrok-free.app/api/memory/clear', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ session_id: sessionId })
      })
      .then(response => response.json())
      .then(() => {
        setMessages([]);
        setSessionId(null);
        localStorage.removeItem('chatSessionId');
      })
      .catch(error => console.error('Error clearing memory:', error));
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
        onMinimize={() => console.log('Minimize')}
        onSettings={clearConversation}
      />
      <div className="h-[400px] overflow-y-auto p-4 space-y-4">
        {messages.map((message, index) => (
          <ChatMessage
            key={index}
            message={message.text}
            isUser={message.isUser}
            timestamp={message.timestamp}
            isThinking={message.isThinking}
          />
        ))}
        {isThinking && <ThinkingBar text={thinkingText} />}
      </div>
      <ChatInput onSendMessage={handleSendMessage} />
    </div>
  );
};
