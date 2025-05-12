import React from 'react';
import { Trash2, Minimize2 } from 'lucide-react';

interface ChatHeaderProps {
  userName: string;
  userImage: string;
  isOnline?: boolean;
  onMinimize?: () => void;
  onSettings?: () => void;
}

export const ChatHeader: React.FC<ChatHeaderProps> = ({
  userName,
  userImage,
  isOnline = false,
  onMinimize,
  onSettings,
}) => {
  return (
    <div className="flex items-center justify-between p-4 bg-chatbot-bg text-white rounded-t-xl">
      <div className="flex items-center space-x-3">
        <div className="relative">
          <img
            src={userImage}
            alt={userName}
            className="w-10 h-10 rounded-full object-cover"
          />
          {isOnline && (
            <div className="absolute bottom-0 right-0 w-3 h-3 bg-green-500 rounded-full border-2 border-chatbot-bg"></div>
          )}
        </div>
        <div>
          <h3 className="font-semibold">Chat with {userName}</h3>
          <p className="text-xs opacity-80">{isOnline ? "We're online" : "Offline"}</p>
        </div>
      </div>
      <div className="flex items-center space-x-2">
        <button
          onClick={onSettings}
          className="p-2 hover:bg-white/10 rounded-full transition-colors"
          title="Clear conversation"
        >
          <Trash2 className="w-5 h-5" />
        </button>
        <button
          onClick={onMinimize}
          className="p-2 hover:bg-white/10 rounded-full transition-colors"
        >
          <Minimize2 className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
};
