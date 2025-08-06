import React from 'react';
import { marked } from 'marked';

interface ChatMessageProps {
  message: string;
  isUser?: boolean;
  timestamp?: string;
  isThinking?: boolean;
}

export const ChatMessage: React.FC<ChatMessageProps> = ({ 
  message, 
  isUser = false, 
  timestamp,
  isThinking = false
}) => {
  const createMarkup = (markdownText: string) => {
    if (typeof marked?.parse === 'function') {
      const rawMarkup = marked.parse(markdownText);
      return { __html: rawMarkup };
    } else {
      console.error("marked.parse is not available");
      return { __html: markdownText };
    }
  };

  const messageClass = isUser
    ? 'bg-blue-500 text-white self-end rounded-l-lg rounded-br-lg'
    : isThinking 
      ? 'bg-gray-200 text-gray-700 self-start rounded-r-lg rounded-bl-lg font-mono text-xs whitespace-pre-wrap overflow-x-auto'
      : 'bg-gray-200 text-gray-800 self-start rounded-r-lg rounded-bl-lg';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`p-3 max-w-[75%] break-words overflow-hidden ${messageClass}`}>
        <div className="break-words" style={{ wordWrap: 'break-word', overflowWrap: 'break-word' }} dangerouslySetInnerHTML={createMarkup(message)} />
        {timestamp && (
          <div className={`text-xs mt-1 ${isUser ? 'text-blue-200' : 'text-gray-500'}`}>
            {timestamp}
          </div>
        )}
      </div>
    </div>
  );
};
