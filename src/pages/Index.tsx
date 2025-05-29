
import { ChatBot } from '@/components/chat/ChatBot';

const Index = () => {
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-100 to-gray-200 flex items-center justify-center">
      <div className="text-center mb-96">
        <h1 className="text-4xl font-bold mb-4">Welcome to Our Support Chat</h1>
        <p className="text-xl text-gray-600">How can we help you today?</p>
      </div>
      <ChatBot />
    </div>
  );
};

export default Index;
