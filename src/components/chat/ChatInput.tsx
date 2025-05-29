
import React, { useState } from 'react';
import { Smile, Paperclip, Send } from 'lucide-react';

interface ChatInputProps {
  onSendMessage: (message: string) => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({ onSendMessage }) => {
  const [message, setMessage] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim()) {
      onSendMessage(message);
      setMessage('');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="border-t p-4 bg-white rounded-b-xl">
      <div className="flex items-center gap-4 w-full">
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="p-2 hover:bg-gray-100 rounded-full transition-colors flex-shrink-0"
          >
            <Smile className="w-5 h-5 text-gray-500" />
          </button>
          <button
            type="button"
            className="p-2 hover:bg-gray-100 rounded-full transition-colors flex-shrink-0"
          >
            <Paperclip className="w-5 h-5 text-gray-500" />
          </button>
        </div>
        <div className="flex-1 flex items-center gap-2">
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Enter your message..."
            className="flex-1 p-2 border rounded-full focus:outline-none focus:ring-2 focus:ring-chatbot-accent min-w-0"
          />
          <button
            type="submit"
            className="p-2 bg-chatbot-accent text-white rounded-full hover:bg-opacity-90 transition-colors flex-shrink-0"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </form>
  );
};
