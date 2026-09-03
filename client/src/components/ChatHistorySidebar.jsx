import { FaPlus, FaTrash, FaComments } from 'react-icons/fa';

function formatTime(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function ChatHistorySidebar({
  chats,
  activeId,
  open,
  userEmail,
  onClose,
  onSelect,
  onNewChat,
  onDelete,
}) {
  return (
    <>
      {open && <button type="button" className="history-backdrop" aria-label="Close history" onClick={onClose} />}
      <aside className={`history-sidebar${open ? ' open' : ''}`} aria-label="Chat history">
        <div className="history-sidebar-header">
          <div className="history-title">
            <FaComments />
            <span>Lịch sử chat</span>
          </div>
          <button type="button" className="history-new-button" onClick={onNewChat}>
            <FaPlus />
            <span>Chat mới</span>
          </button>
        </div>

        <div className="history-list">
          {chats.length === 0 && (
            <p className="history-empty">Chưa có cuộc trò chuyện nào. Bắt đầu chat để lưu tại đây.</p>
          )}
          {chats.map((chat) => (
            <div
              key={chat.id}
              className={`history-item${chat.id === activeId ? ' active' : ''}`}
            >
              <button
                type="button"
                className="history-item-main"
                onClick={() => onSelect(chat.id)}
              >
                <span className="history-item-title">{chat.title || 'New chat'}</span>
                <span className="history-item-time">{formatTime(chat.updatedAt)}</span>
              </button>
              <button
                type="button"
                className="history-item-delete"
                aria-label="Delete chat"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(chat.id);
                }}
              >
                <FaTrash />
              </button>
            </div>
          ))}
        </div>
        {userEmail && (
          <div className="history-user-footer">
            <span>{userEmail}</span>
          </div>
        )}
      </aside>
    </>
  );
}

export default ChatHistorySidebar;
