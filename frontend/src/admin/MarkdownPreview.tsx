import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function normalizeAssetUrls(markdown: string): string {
  return markdown.replace(/asset:\/\/([0-9a-fA-F-]{36})/g, "/media/$1");
}

export function MarkdownPreview({ markdown }: { markdown: string }) {
  if (!markdown.trim()) {
    return <div className="admin-preview admin-preview-empty">在左侧输入 Markdown 内容后，这里显示预览。</div>;
  }
  return (
    <div className="admin-preview">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {normalizeAssetUrls(markdown)}
      </ReactMarkdown>
    </div>
  );
}
