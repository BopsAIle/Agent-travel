import { useEffect, useRef, useState } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import './App.css';

import Header from './components/Header';
import ChatWindow from './components/ChatWindow';
import ChatHistorySidebar from './components/ChatHistorySidebar';
import LoginScreen from './components/LoginScreen';
import AgentMonitor from './components/AgentMonitor';
import { useAuth } from './context/AuthContext';
import { API_BASE, readError } from './api';
import {
  WELCOME_MESSAGE,
  mapChatSummaries,
  messagesFromExport,
} from './chatHistory';

const API_URL = `${API_BASE}/chat-stream`;

function ChatApp() {
  const { user, logout, authHeaders } = useAuth();
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [slots, setSlots] = useState({});
  const [agentStatus, setAgentStatus] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState([]);
  const [activeChatId, setActiveChatId] = useState('');
  const [historyOpen, setHistoryOpen] = useState(
    () => typeof window !== 'undefined' && window.innerWidth >= 900
  );
  const [page, setPage] = useState('chat');

  const abortControllerRef = useRef(null);
  const sessionIdRef = useRef('');
  const messagesRef = useRef(messages);
  const slotsRef = useRef(slots);

  messagesRef.current = messages;
  slotsRef.current = slots;

  const refreshHistory = async () => {
    try {
      const response = await fetch(`${API_BASE}/chats`, { headers: authHeaders() });
      if (response.status === 401 || response.status === 403) {
        logout();
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      setHistory(mapChatSummaries(data.chats || []));
    } catch {
      // Keep the current sidebar if the list call fails.
    }
  };

  useEffect(() => {
    refreshHistory();
  }, []);

  const resetComposer = () => {
    setAgentStatus('');
    setError('');
    setIsLoading(false);
  };

  const handleNewChat = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    sessionIdRef.current = '';
    setActiveChatId('');
    setMessages([WELCOME_MESSAGE]);
    setSlots({});
    resetComposer();
  };

  const handleSelectChat = async (id) => {
    if (!id || id === sessionIdRef.current) {
      setHistoryOpen(window.innerWidth >= 900);
      return;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    try {
      const response = await fetch(`${API_BASE}/chats/${id}`, { headers: authHeaders() });
      if (response.status === 401 || response.status === 403) {
        logout();
        return;
      }
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      const data = await response.json();
      sessionIdRef.current = id;
      setActiveChatId(id);
      setMessages(messagesFromExport(data));
      setSlots(data.slots || {});
      resetComposer();
      if (window.innerWidth < 900) setHistoryOpen(false);
    } catch {
      setError('Could not load that chat.');
    }
  };

  const handleDeleteChat = async (id) => {
    try {
      const response = await fetch(`${API_BASE}/chats/${id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (response.status === 401 || response.status === 403) {
        logout();
        return;
      }
    } catch {
      // Continue with local removal if the API is briefly unavailable.
    }
    setHistory((current) => current.filter((item) => item.id !== id));
    if (sessionIdRef.current === id) {
      handleNewChat();
    }
  };

  const handleSend = async (text) => {
    setError('');
    setAgentStatus('Thinking...');
    setIsLoading(true);
    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
    };
    const withUser = [...messagesRef.current, userMessage];
    setMessages(withUser);

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;
    let requestFailed = false;
    let completed = false;
    let latestMessages = withUser;
    let latestSlots = slotsRef.current;

    try {
      await fetchEventSource(API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify({
          message: text,
          session_id: sessionIdRef.current || undefined,
        }),
        signal,
        openWhenHidden: true,

        async onopen(response) {
          const contentType = response.headers.get('content-type') || '';
          if (response.status === 401 || response.status === 403) {
            logout();
            throw new Error('Please sign in again.');
          }
          if (response.ok && contentType.includes('text/event-stream')) {
            return;
          }
          throw new Error(`Server connection error. Status: ${response.status}`);
        },

        onmessage(event) {
          try {
            const data = event.data ? JSON.parse(event.data) : {};
            if (event.event === 'session' && data.session_id) {
              sessionIdRef.current = data.session_id;
              setActiveChatId(data.session_id);
            } else if (event.event === 'slots') {
              latestSlots = data;
              setSlots(data);
            } else if (event.event === 'message' && data.content) {
              latestMessages = [
                ...latestMessages,
                {
                  id: `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`,
                  role: 'assistant',
                  content: data.content,
                },
              ];
              setMessages(latestMessages);
            } else if (event.event === 'status') {
              setAgentStatus(data.message || 'Working...');
            } else if (event.event === 'final_report') {
              completed = true;
              latestMessages = [
                ...latestMessages,
                {
                  id: `itinerary-${Date.now()}`,
                  role: 'itinerary',
                  reportData: {
                    markdown: data.markdown_report,
                    map: data.map_html,
                  },
                },
              ];
              setMessages(latestMessages);
              setAgentStatus('');
              setIsLoading(false);
              refreshHistory();
            } else if (event.event === 'error') {
              completed = true;
              setError(data.message || 'An error occurred.');
              setIsLoading(false);
              abortControllerRef.current?.abort();
            }
          } catch (parseError) {
            console.log('Message parse error', parseError);
          }
        },

        onclose() {
          completed = true;
          setIsLoading(false);
          setAgentStatus('');
          refreshHistory();
        },

        onerror(err) {
          if (signal.aborted || completed) {
            throw err;
          }
          requestFailed = true;
          setError('Connection lost. Please try again.');
          setIsLoading(false);
          throw err;
        },
      });
    } catch (err) {
      if (!signal.aborted && !requestFailed && !completed) {
        setError(err.message || 'Failed to connect to server.');
        setIsLoading(false);
      }
    }
  };

  return (
    <div className="App app-shell">
      {page === 'chat' && (
        <ChatHistorySidebar
          chats={history}
          activeId={activeChatId}
          open={historyOpen}
          userEmail={user?.email}
          onClose={() => setHistoryOpen(false)}
          onSelect={handleSelectChat}
          onNewChat={handleNewChat}
          onDelete={handleDeleteChat}
        />
      )}
      <div className={`main-container chat-layout${page === 'agents' ? ' metrics-layout' : ''}`}>
        <Header
          page={page}
          onPageChange={setPage}
          onNewChat={handleNewChat}
          onToggleHistory={() => setHistoryOpen((value) => !value)}
          historyOpen={historyOpen}
          userEmail={user?.email}
          onLogout={logout}
        />
        {page === 'chat' ? (
          <ChatWindow
            messages={messages}
            slots={slots}
            isLoading={isLoading}
            agentStatus={agentStatus}
            error={error}
            onSend={handleSend}
          />
        ) : (
          <AgentMonitor />
        )}
      </div>
    </div>
  );
}

function App() {
  const { user, ready } = useAuth();

  if (!ready) {
    return (
      <div className="login-screen">
        <p className="boot-status">Loading…</p>
      </div>
    );
  }

  if (!user) {
    return <LoginScreen />;
  }

  return <ChatApp />;
}

export default App;
