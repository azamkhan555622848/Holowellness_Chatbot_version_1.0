import React from 'react';

interface ThinkingBarProps {
  text: string;
}

export const ThinkingBar: React.FC<ThinkingBarProps> = ({ text }) => {
  return (
    <div className="p-3 bg-purple-50 border border-purple-100 text-purple-800 rounded-lg mb-2 text-sm font-medium flex items-center gap-2">
      <span className="flex items-center gap-2">
        Thinking <span role="img" aria-label="thinking">🧠</span>
      </span>
      <span className="text-purple-600">{text.replace('Thinking', '')}</span>
    </div>
  );
}; 