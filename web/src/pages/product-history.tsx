import { ArrowRightIcon, FileTextIcon } from "lucide-react"
import { useEffect, useState, type ReactNode } from "react"

import { Callout, Chip, Eyebrow } from "@/components/common"
import { Markdown } from "@/components/markdown"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { api, type History, type HistoryEntry } from "@/lib/api"
import { cn } from "@/lib/utils"

// 迭代记录.md 是给 AI 编程工具和命令行用户写的，这里只挑对提出想法的人有用的信息，换成好懂的说法。

const KIND: Record<string, string> = {
  建立工作区: "建立产品",
  方案推导: "推导方案",
  新需求: "加新需求",
  回答待确认问题: "回答问题",
  验证: "检查代码骨架",
}

// 这些行是命令行步骤或给 AI 的提醒，网页用户用不上
// 「待确认：N 条」只数需求拆解里的未知项，和页面上的待确认问题数（含组件问题、已分流）对不上，不显示
const HIDDEN = ["`blueprint", "人工验证结论", "等 AI 消化", "骨架待办", "下一步", "快速模式", "本轮未重推", "报告：", "待确认："]

const DECISION_TONE = { 必选: "ok", 二期: "warn", 待确认: "ask", 放弃: "muted" } as const

function decisionChip(d: string) {
  return <Chip tone={DECISION_TONE[d as keyof typeof DECISION_TONE] ?? "muted"}>{d}</Chip>
}

function describe(line: string, names: Record<string, string>): ReactNode {
  if (HIDDEN.some((h) => line.includes(h))) return null
  const label = (id: string) => `${id} ${names[id] ?? ""}`.trim()
  let m: RegExpMatchArray | null
  if ((m = line.match(/^(?:新需求|原始需求)：(.+)$/))) {
    const text = m[1].replace(/^#+\s*/, "")
    // 旧记录里可能只记到了「### 一句话想法」这样的标题，没有正文可显示
    return /^(一句话想法|要加什么或改什么)$/.test(text) ? null : <p className="font-medium">{text}</p>
  }
  if (line.startsWith("选型变化：无")) return <p className="text-muted-foreground">组件选型没有变化</p>
  if ((m = line.match(/^重新判断：(.+)；其余沿用 (V\d+) 的判断$/))) {
    return (
      <p className="text-muted-foreground">
        {m[1] === "无" ? "新需求没涉及已有组件的判断" : `这次只重新判断了：${m[1]}`}；其余沿用 {m[2]} 的判断，避免和新需求无关的选型跟着变。
      </p>
    )
  }
  if ((m = line.match(/^选型变化：(.+)$/))) {
    const changes = m[1].split("；").map((c) => c.trim().match(/^(s\d\d) (\S+) → (\S+)$/)).filter(Boolean) as RegExpMatchArray[]
    return (
      <div>
        <div className="mb-1.5 text-muted-foreground">组件选型变了 {changes.length} 处：</div>
        <ul className="space-y-1">
          {changes.map((c) => (
            <li key={c[1]} className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">{c[1]}</span>
              <span>{names[c[1]] ?? ""}</span>
              {decisionChip(c[2])}
              <ArrowRightIcon className="size-3 text-muted-foreground" />
              {decisionChip(c[3])}
            </li>
          ))}
        </ul>
      </div>
    )
  }
  if ((m = line.match(/^必选组件：(.+)$/))) {
    return <p className="text-muted-foreground">第一版要做：{m[1].split("、").map(label).join("、")}</p>
  }
  if ((m = line.match(/^方案：.*审稿(通过|未完全通过)/))) {
    return <p className="text-muted-foreground">{m[1] === "通过" ? "独立审稿通过" : "独立审稿提了意见，见「审稿意见」"}</p>
  }
  if ((m = line.match(/^PRD：(V\d+) → (V\d+)/))) return <p className="text-muted-foreground">需求文档 {m[1]} → {m[2]}</p>
  if ((m = line.match(/^回答了 (\d+) 个问题/))) return <p className="text-muted-foreground">回答了 {m[1]} 个问题，写进了需求文档</p>
  if ((m = line.match(/^对照 PRD (V\d+) 检查 skeleton\/：(.+)$/))) return <p className="text-muted-foreground">对照 {m[1]} 检查代码骨架：{m[2]}</p>
  if (line.startsWith("⚠️")) return <p className="text-muted-foreground">{line}</p>
  return null
}

function Entry({ entry, names, onOpen }: { entry: HistoryEntry; names: Record<string, string>; onOpen?: () => void }) {
  const kind = KIND[entry.title] ?? entry.title
  const body = entry.lines
    .map((l) => describe(l, names))
    .filter(Boolean)
    .map((node, i) => <div key={i}>{node}</div>)
  return (
    <li className="grid gap-x-6 gap-y-2 border-t py-4 first:border-t-0 sm:grid-cols-[9rem_1fr]">
      <div className="flex items-baseline gap-3 sm:flex-col sm:gap-1">
        <span className="font-mono text-xs text-muted-foreground">{entry.date}</span>
        {entry.version != null && <span className="font-mono text-sm">V{entry.version}</span>}
      </div>
      <div className="min-w-0 space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-medium">{kind}</span>
          {onOpen && (
            <Button variant="ghost" size="sm" className="-my-1 text-muted-foreground" onClick={onOpen}>
              <FileTextIcon /> 看当时的需求文档
            </Button>
          )}
        </div>
        {body}
      </div>
    </li>
  )
}

export function HistoryTab({ slug, names, refreshKey }: { slug: string; names: Record<string, string>; refreshKey: string }) {
  const [history, setHistory] = useState<History | null>(null)
  const [error, setError] = useState("")
  const [doc, setDoc] = useState<{ version: number; text: string; current: boolean } | null>(null)

  useEffect(() => {
    api.history(slug).then(setHistory, (e: Error) => setError(e.message))
  }, [slug, refreshKey])

  const open = async (version?: number) => {
    try {
      setDoc(await api.prd(slug, version))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (error) return <Callout tone="bad" title="读不到版本历史">{error}</Callout>
  if (!history) return null

  // 每个版本只在「引入它」的那条记录上放「看当时的需求文档」
  const available = new Set([...history.snapshots, history.current])
  const shown = new Set<number>()
  const entries = [...history.log].reverse()
  const openerFor = (e: HistoryEntry) => {
    if (e.version == null || shown.has(e.version) || !available.has(e.version)) return undefined
    if (!["建立工作区", "新需求"].includes(e.title)) return undefined
    shown.add(e.version)
    return () => open(e.version === history.current ? undefined : e.version!)
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-2 text-sm">
          <span className="text-muted-foreground">当前版本</span>
          <span className="font-mono font-medium">V{history.current}</span>
        </div>
        <Button variant="outline" size="sm" onClick={() => open()}>
          <FileTextIcon /> 看当前的需求文档
        </Button>
      </div>

      {history.versions.length > 1 && (
        <section className="mb-8">
          <Eyebrow className="mb-3">版本记录</Eyebrow>
          <div className="divide-y rounded-lg border">
            {[...history.versions].reverse().map((v) => (
              <div key={v.version} className={cn("flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-2.5 text-sm", v.version === history.current && "bg-muted/50")}>
                <span className="w-8 font-mono">V{v.version}</span>
                <span className="font-mono text-xs text-muted-foreground">{v.date}</span>
                <span className="min-w-0 flex-1">{v.change}</span>
                <span className="text-xs text-muted-foreground">{v.source}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <Eyebrow className="mb-1">每一轮做了什么</Eyebrow>
      <ol>
        {entries.map((e, i) => (
          <Entry key={i} entry={e} names={names} onOpen={openerFor(e)} />
        ))}
      </ol>

      <Dialog open={!!doc} onOpenChange={(o) => !o && setDoc(null)}>
        <DialogContent className="max-h-[85svh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>需求文档 V{doc?.version}{doc?.current ? "（当前）" : ""}</DialogTitle>
          </DialogHeader>
          {doc && <Markdown text={doc.text} />}
        </DialogContent>
      </Dialog>
    </div>
  )
}
