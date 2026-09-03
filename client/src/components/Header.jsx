import { FaPlaneDeparture, FaPlus, FaBars, FaSignOutAlt, FaChartBar, FaComments } from 'react-icons/fa';

function Header({
  page = 'chat',
  onPageChange,
  onNewChat,
  onToggleHistory,
  userEmail,
  onLogout,
}) {
  const onAgents = page === 'agents';
  return (
    <header className="App-header gradient-header chat-header">
      <div className="header-row">
        <div className="title-container">
          {onToggleHistory && !onAgents && (
            <button
              type="button"
              className="history-toggle"
              onClick={onToggleHistory}
              aria-label="Open chat history"
            >
              <FaBars />
            </button>
          )}
          <FaPlaneDeparture className="plane-icon" />
          <h1>AI Travel Agent</h1>
        </div>
        <div className="header-actions">
          {onPageChange && (
            <button
              type="button"
              className={`new-chat-button${onAgents ? ' nav-active' : ''}`}
              onClick={() => onPageChange(onAgents ? 'chat' : 'agents')}
            >
              {onAgents ? <FaComments /> : <FaChartBar />}
              <span>{onAgents ? 'Chat' : 'Agents'}</span>
            </button>
          )}
          {!onAgents && onNewChat && (
            <button type="button" className="new-chat-button" onClick={onNewChat}>
              <FaPlus />
              <span>New chat</span>
            </button>
          )}
          {userEmail && (
            <div className="header-user">
              <span className="header-user-email">{userEmail}</span>
              <button type="button" className="logout-button" onClick={onLogout}>
                <FaSignOutAlt />
                <span>Log out</span>
              </button>
            </div>
          )}
        </div>
      </div>
      <p>
        {onAgents
          ? 'Live time, token, and estimated API cost for each agent in your trips.'
          : 'Chat about your trip. I will collect the details, plan, and revise with you.'}
      </p>
    </header>
  );
}

export default Header;
