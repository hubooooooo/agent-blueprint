import { createContext, useContext, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import type { Decision, Settings } from "@/lib/api"
import { cn } from "@/lib/utils"

export const SettingsContext = createContext<{ settings: Settings; reload: () => Promise<void> } | null>(null)

export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error("SettingsContext missing")
  return ctx
}

/** 小号等宽标签，assistant-ui 风格的分节标题。 */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("font-mono text-xs tracking-wider text-muted-foreground uppercase", className)}>
      {children}
    </div>
  )
}

export function PageHeader({
  crumb,
  title,
  sub,
  actions,
}: {
  crumb?: ReactNode
  title: ReactNode
  sub?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {crumb && <div className="mb-2 text-sm text-muted-foreground">{crumb}</div>}
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-2 max-w-2xl text-muted-foreground">{sub}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  )
}

export function Callout({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: "info" | "warn" | "bad"
  title: ReactNode
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div
      className={cn(
        "mb-6 rounded-lg border px-4 py-3",
        tone === "warn" && "border-warn/30 bg-warn-soft",
        tone === "bad" && "border-destructive/30 bg-destructive/8",
        tone === "info" && "bg-muted",
      )}
    >
      <div className="text-sm font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted-foreground">{children}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

/** 没配模型 / 离线演示时的提示；各页面顶部共用。 */
export function ModeCallouts() {
  const { settings } = useSettings()
  if (settings.mock) {
    return (
      <Callout tone="warn" title="离线演示模式">
        不调用模型，回复和方案都是按关键词拼出来的占位内容，用来看看流程长什么样，不能用于真实决策。
      </Callout>
    )
  }
  if (!settings.configured) {
    return (
      <Callout
        tone="warn"
        title="第一步：配置模型"
        action={<Button nativeButton={false} render={<a href="#/settings" />}>去配置</Button>}
      >
        引擎要靠大模型来对话和推导方案。推荐 DeepSeek，便宜、国内可直连，充值几块钱就能用很久。
      </Callout>
    )
  }
  return null
}

export const DECISIONS: { key: Decision; tone: "ok" | "warn" | "ask" | "muted"; hint: string }[] = [
  { key: "必选", tone: "ok", hint: "第一版就要做" },
  { key: "二期", tone: "warn", hint: "以后再做" },
  { key: "待确认", tone: "ask", hint: "取决于你对待确认问题的回答" },
  { key: "放弃", tone: "muted", hint: "这个产品用不上" },
]

const TONE = {
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  ask: "bg-ask-soft text-ask",
  muted: "bg-muted text-muted-foreground",
  bad: "bg-destructive/10 text-destructive",
  ink: "bg-foreground text-background",
} as const

export function Chip({ tone = "muted", children, className }: { tone?: keyof typeof TONE; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-5 items-center rounded-full px-2 text-xs font-medium whitespace-nowrap", TONE[tone], className)}>
      {children}
    </span>
  )
}

export function timeAgo(ts: number) {
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 60) return "刚刚"
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}
