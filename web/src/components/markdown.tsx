import type { ComponentProps } from "react"
import ReactMarkdown, { type ExtraProps } from "react-markdown"
import remarkBreaks from "remark-breaks"
import remarkGfm from "remark-gfm"

type HastNode = { type: string; value?: string; children?: HastNode[] }

function textOf(node?: HastNode): string {
  if (!node) return ""
  return node.type === "text" ? node.value ?? "" : (node.children ?? []).map(textOf).join("")
}

// 表格自动分列时长文字那列会把短格子挤成一个字一行（「待确认」竖着排），所以短格子不换行
const SHORT_CELL = 8
const cell = (Tag: "td" | "th") =>
  function Cell({ node, ...props }: ComponentProps<typeof Tag> & ExtraProps) {
    const short = textOf(node as HastNode | undefined).trim().length <= SHORT_CELL
    return <Tag {...props} className={short ? "whitespace-nowrap" : undefined} />
  }
const components = { td: cell("td"), th: cell("th") }

/** 渲染 PRD、差距报告等 Markdown 文档。样式见 index.css 的 .doc。
 *  引擎写的「> 第一行\n> 第二行」是想分行显示的，所以换行照原样保留（remark-breaks）。 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="doc">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={components}>{text}</ReactMarkdown>
    </div>
  )
}
