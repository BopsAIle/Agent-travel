import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { FaPaperPlane } from 'react-icons/fa';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ReportDisplay from './ReportDisplay';

function collapseRepeats(text) {
  if (!text || text.length < 160) return text;
  const match = text.match(/([\s\S]{8,80}?)(?:\s*\1){3,}/);
  if (!match) return text.slice(0, 8000);
  const keep = text.slice(0, match.index + match[1].length).replace(/[ ,;:-]+$/, '');
  return `${keep}…`;
}

function SlotChips({ slots }) {
  if (!slots) return null;

  const chips = [];
  if (slots.origin || slots.destination) {
    chips.push({
      key: 'route',
      label: [slots.origin, slots.destination].filter(Boolean).join(' → '),
    });
  }
  if (slots.start_date || slots.end_date) {
    chips.push({
      key: 'dates',
      label: [slots.start_date, slots.end_date].filter(Boolean).join(' – '),
    });
  }
  if (slots.person) {
    chips.push({
      key: 'people',
      label: `${slots.person} ${Number(slots.person) === 1 ? 'person' : 'people'}`,
    });
  }
  if (slots.budget != null && slots.budget !== '') {
    chips.push({ key: 'budget', label: `€${slots.budget}` });
  }
  if (Array.isArray(slots.interests) && slots.interests.length) {
    chips.push({ key: 'interests', label: slots.interests.join(', ') });
  }

  if (!chips.length) return null;

  return (
    <div className="slot-chips" aria-label="Trip details">
      {chips.map((chip) => (
        <span key={chip.key} className="slot-chip">
          {chip.label}
        </span>
      ))}
    </div>
  );
}

function ChatWindow({
  messages,
  slots,
  isLoading,
  agentStatus,
  error,
  onSend,
}) {
  const [input, setInput] = useState('');
  const bottomRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading, agentStatus, error]);

  const handleSubmit = (event) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || isLoading) return;
    onSend(text);
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(event);
    }
  };

  const handleInput = (event) => {
    setInput(event.target.value);
    const el = event.target;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <div className="chat-window">
      <SlotChips slots={slots} />

      <div className="chat-messages">
        {messages.map((message) => {
          if (message.role === 'itinerary') {
            return (
              <div key={message.id} className="chat-itinerary">
                <ReportDisplay
                  embedded
                  reportData={message.reportData}
                  isLoading={false}
                  error={null}
                  agentStatus=""
                />
              </div>
            );
          }

          return (
            <div
              key={message.id}
              className={`chat-row ${message.role === 'user' ? 'from-user' : 'from-assistant'}`}
            >
              <div className={`chat-bubble ${message.role}`}>
                {message.role === 'assistant' ? (
                  <div className="markdown-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {collapseRepeats(message.content || '')}
                    </ReactMarkdown>
                  </div>
                ) : (
                  message.content
                )}
              </div>
            </div>
          );
        })}

        {isLoading && agentStatus && (
          <div className="chat-row from-assistant">
            <div className="chat-bubble status">
              <span className="status-dot" />
              {agentStatus}
            </div>
          </div>
        )}

        {error && (
          <div className="chat-row from-assistant">
            <div className="chat-bubble error-bubble">{error}</div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <form className="chat-composer" onSubmit={handleSubmit}>
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder="Tell me about your trip..."
          disabled={isLoading}
          aria-label="Message"
        />
        <motion.button
          type="submit"
          className="send-button"
          disabled={isLoading || !input.trim()}
          whileTap={{ scale: 0.95 }}
        >
          <FaPaperPlane />
          <span>Send</span>
        </motion.button>
      </form>
    </div>
  );
}

export default ChatWindow;
