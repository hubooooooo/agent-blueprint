import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

/** 渲染 PRD 等 Markdown 文档。样式见 index.css 的 .doc。 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="doc">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
}
