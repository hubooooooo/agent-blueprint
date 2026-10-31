import { useState, type ReactNode } from "react"

import { cn } from "@/lib/utils"

// 模型写的长字段（技术栈、上下文策略……）常是一整段，里面有【小标题】和 ①②③。
// 这里按这些记号拆开显示；没有记号的就是普通段落。

type Block = { title: string; lead: string; items: string[] }

const TITLE = /【([^】]{1,24})】/
const NUMBERED = /(?=[①-⑳])/

export function splitRich(text: string): Block[] {
  const parts = text.split(TITLE)
  const blocks: Block[] = []
  // split 带捕获组：[开头, 标题1, 正文1, 标题2, 正文2, …]
  for (let i = 0; i < parts.length; i += 2) {
    const title = i === 0 ? "" : parts[i - 1]
    const body = parts[i].trim()
    if (!title && !body) continue
    const pieces = body.split(NUMBERED)
    const numbered = pieces.filter((p) => /^[①-⑳]/.test(p))
    if (numbered.length >= 2) {
      const lead = /^[①-⑳]/.test(pieces[0]) ? "" : pieces[0].trim()
      blocks.push({ title, lead, items: numbered.map((p) => p.trim()) })
    } else {
      blocks.push({ title, lead: body, items: [] })
    }
  }
  return blocks
}

/** 一条条的内容：模型给的是列表，就按列表显示，不拼成一段。 */
export function Bullets({ items, className }: { items: ReactNode[]; className?: string }) {
  return (
    <ul className={cn("space-y-1.5", className)}>
      {items.map((s, i) => (
        <li key={i} className="flex gap-2.5">
          <span className="shrink-0 text-muted-foreground">—</span>
          <span className="min-w-0 wrap-anywhere">{s}</span>
        </li>
      ))}
    </ul>
  )
}

export function RichText({ text, className }: { text: string; className?: string }) {
  if (!text.trim()) return <p className={cn("text-muted-foreground", className)}>（空）</p>
  return (
    <div className={cn("space-y-3", className)}>
      {splitRich(text).map((b, i) => (
        <div key={i}>
          {b.title && <div className="mb-1 font-medium">{b.title}</div>}
          {b.lead && <p className="wrap-anywhere whitespace-pre-line">{b.lead}</p>}
          {b.items.length > 0 && (
            <ul className={cn("space-y-1", b.lead && "mt-1.5")}>
              {b.items.map((item, j) => (
                <li key={j} className="flex gap-2">
                  <span className="shrink-0 text-muted-foreground">{item[0]}</span>
                  <span className="min-w-0 wrap-anywhere">{item.slice(1).trim()}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}

/** 特别长的一段先只显示前几行，点了再展开。 */
export function Clamp({ text, lines = 3, limit = 140 }: { text: string; lines?: number; limit?: number }) {
  const [open, setOpen] = useState(false)
  if (text.length <= limit) return <span className="wrap-anywhere">{text}</span>
  return (
    <div>
      {open ? (
        <RichText text={text} />
      ) : (
        <p className="wrap-anywhere" style={{ display: "-webkit-box", WebkitLineClamp: lines, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
          {text}
        </p>
      )}
      <button type="button" onClick={() => setOpen(!open)} className="mt-1 text-xs text-link hover:underline">
        {open ? "收起" : "展开全文"}
      </button>
    </div>
  )
}
