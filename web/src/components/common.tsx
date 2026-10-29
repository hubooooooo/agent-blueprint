import { MenuIcon } from "lucide-react"
import { createContext, useContext, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import type { AuditSummary, Decision, ProductSummary, Settings } from "@/lib/api"
import { cn } from "@/lib/utils"

export const SettingsContext = createContext<{ settings: Settings; reload: () => Promise<void> } | null>(null)

export function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error("SettingsContext missing")
  return ctx
}

/** 应用外壳：侧边栏里的产品和检查过的项目，以及窄屏下侧边栏的开关。 */
export const ShellContext = createContext<{
  products: ProductSummary[] | null
  reloadProducts: () => Promise<void>
  audits: AuditSummary[] | null
  reloadAudits: () => Promise<void>
  openSidebar: () => void
} | null>(null)

export function useShell() {
  const ctx = useContext(ShellContext)
  if (!ctx) throw new Error("ShellContext missing")
  return ctx
}

/** 每页顶部的窄工具栏：左边标题，右边操作。窄屏时最左边是打开侧边栏的按钮。 */
export function TopBar({ title, actions }: { title: ReactNode; actions?: ReactNode }) {
  const { openSidebar } = useShell()
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3 sm:px-4">
      <Button variant="ghost" size="icon-sm" className="-ms-1 md:hidden" onClick={openSidebar} aria-label="打开菜单">
        <MenuIcon />
      </Button>
      <div className="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium">{title}</div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </header>
  )
}

/** 小号等宽标签，assistant-ui 风格的分节标题。 */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("font-mono text-xs tracking-wider text-muted-foreground uppercase", className)}>
      {children}
    </div>
  )
}

/** 页面骨架：一页占满主区域的高度，顶栏固定，下面的内容自己决定怎么滚动。 */
export function Screen({ children }: { children: ReactNode }) {
  return <div className="flex min-h-0 flex-1 flex-col">{children}</div>
}

/** 以文字为主的页面的内容宽度：正文一行四十多个字，再宽就难读了。 */
export const READING = "max-w-[44rem]"

/** 可滚动的内容区。 */
export function ScrollBody({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className={cn("mx-auto w-full max-w-5xl px-4 py-6 sm:px-6", className)}>{children}</div>
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
        "mb-5 rounded-lg border px-4 py-3",
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
