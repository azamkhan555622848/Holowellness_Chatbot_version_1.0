
import React from 'react';

interface QuickReplyProps {
  options: string[];
  onSelect: (option: string) => void;
}

export const QuickReply: React.FC<QuickReplyProps> = ({ options, onSelect }) => {
  return (
    <div className="flex flex-wrap gap-2 mb-4">
      {options.map((option, index) => (
        <button
          key={index}
          onClick={() => onSelect(option)}
          className="px-4 py-2 rounded-full bg-white border border-gray-200 text-chatbot-accent text-sm hover:bg-gray-50 transition-colors"
        >
          {option}
        </button>
      ))}
    </div>
  );
};
