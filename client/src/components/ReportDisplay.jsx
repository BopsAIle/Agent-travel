import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './ReportDisplay.css';

function ReportDisplay({ isLoading, error, reportData, agentStatus, embedded = false }) {

  if (!embedded && isLoading) {
    return (
      <div className="report-status-container">
        <div className="loading-spinner"></div>
        <p className="status-text">{agentStatus || "AI Agent is thinking..."}</p>
      </div>
    );
  }

  if (!embedded && error) {
    return (
      <div className="report-error-container">
        <h3>⚠️ Planning Error</h3>
        <p>{error}</p>
      </div>
    );
  }

  if (!reportData || (!reportData.markdown && !reportData.map && !reportData.issues?.length)) {
    return null;
  }

  return (
    <div className={`report-display-container${embedded ? ' embedded' : ''}`}>
      {reportData.success === false && reportData.issues?.length > 0 && (
        <div className="report-error-container">
          <h3>⚠️ Kế hoạch chưa hoàn tất</h3>
          <ul>
            {reportData.issues.map((issue, index) => (
              <li key={`${index}-${issue}`}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
      
      {reportData.markdown && (
        <div className="markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {reportData.markdown}
          </ReactMarkdown>
        </div>
      )}

      {reportData.map && (
        <div className="map-section">
          <h2>Trip Map</h2>
          <p style={{ color: '#666', marginBottom: '10px' }}>
            Click the pins for details.
          </p>
          
          <div className="map-wrapper">
            <iframe
              title="Trip Map"
              srcDoc={reportData.map} 
              style={{
                width: '100%',
                height: '500px',
                border: 'none',
                borderRadius: '12px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
              }}
              scrolling="no" 
            />
          </div>
        </div>
      )}
      
    </div>
  );
}

export default ReportDisplay;
