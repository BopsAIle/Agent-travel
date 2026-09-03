export const WELCOME_MESSAGE = {
  id: 'welcome',
  role: 'assistant',
  content:
    "Hi! Tell me about your trip — where from, where to, and when. / Xin chào! Hãy kể về chuyến đi: đi từ đâu, đến đâu, và khi nào.",
};

export function messagesWithWelcome(messages) {
  if (!messages?.length) return [WELCOME_MESSAGE];
  if (messages[0]?.id === 'welcome') return messages;
  return [WELCOME_MESSAGE, ...messages];
}

export function mapChatSummaries(chats = []) {
  return chats.map((item) => ({
    id: item.session_id,
    title: item.title || 'New chat',
    updatedAt: item.updated_at,
    preview: item.preview,
    slots: item.slots || {},
    hasPlan: item.has_plan,
  }));
}

export function messagesFromExport(data) {
  const raw = Array.isArray(data?.messages) ? data.messages : [];
  const messages = [];
  raw.forEach((item, index) => {
    const role = item.role;
    if (role === 'itinerary') {
      messages.push({
        id: item.id || `itinerary-${index}`,
        role: 'itinerary',
        reportData: item.reportData || {
          markdown: data.markdown_report || '',
          map: data.map_html || null,
        },
      });
      return;
    }
    if ((role === 'user' || role === 'assistant') && item.content) {
      messages.push({
        id: item.id || `${role}-${index}`,
        role,
        content: item.content,
      });
    }
  });
  const hasItinerary = messages.some((item) => item.role === 'itinerary');
  if (!hasItinerary && data?.markdown_report) {
    messages.push({
      id: 'itinerary',
      role: 'itinerary',
      reportData: {
        markdown: data.markdown_report,
        map: data.map_html || null,
      },
    });
  }
  return messagesWithWelcome(messages);
}
