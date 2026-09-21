import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Ảnh trong report là URL ngoài (CDN Booking.com) có chữ ký. Chữ ký sai/hết hạn,
 * hoặc mạng chặn CDN, thì <img> mặc định hiện biểu tượng "ảnh vỡ" kèm alt text —
 * đúng lỗi đã thấy ở mục "Thông tin khách sạn".
 *
 * Ảnh lỗi thì bỏ hẳn thẻ ảnh: phần chữ (tên khách sạn, giá, đánh giá) vẫn nguyên.
 * Phía server đã loại URL hỏng trước khi ghi report (app/domain/photos.py), nên
 * nhánh này chỉ còn dùng cho lỗi mạng tạm thời ở trình duyệt.
 */
function MarkdownImage({ src, alt }) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return null;
  }

  return (
    <img
      src={src}
      alt={alt || ''}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => {
        console.warn('Không tải được ảnh trong report:', src);
        setFailed(true);
      }}
    />
  );
}

function MarkdownContent({ content, className = 'markdown-content' }) {
  if (!content) return null;

  return (
    <div className={className}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ img: MarkdownImage }}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

export default MarkdownContent;
