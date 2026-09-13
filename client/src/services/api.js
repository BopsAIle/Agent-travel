export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export function formatApiError(detail) {
  if (!detail) return 'Request failed';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || item).join(' ');
  }
  return 'Request failed';
}

export async function readError(response) {
  try {
    const data = await response.json();
    return formatApiError(data.detail || data.message);
  } catch {
    return `Request failed (${response.status})`;
  }
}
