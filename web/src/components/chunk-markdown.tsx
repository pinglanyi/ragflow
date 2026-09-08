import DOMPurify from 'dompurify';
import Markdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import { MarkdownRemarkPluginsLite } from '@/constants/markdown-remark-plugins';

export function ChunkMarkdown({ content }: { content: string }) {
  return <div className="overflow-x-auto whitespace-normal [&_table]:border-collapse [&_th]:border [&_td]:border [&_th]:p-2 [&_td]:p-2 [&_th]:text-left">
    <Markdown remarkPlugins={MarkdownRemarkPluginsLite} rehypePlugins={[rehypeRaw]}>
      {DOMPurify.sanitize(content)}
    </Markdown>
  </div>;
}
