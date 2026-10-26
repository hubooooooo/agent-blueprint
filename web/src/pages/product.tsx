import { useAui } from "@assistant-ui/react"
import { DownloadIcon, FolderOpenIcon } from "lucide-react"
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react"
import { toast } from "sonner"

import { ChatPane } from "@/components/chat/chat-pane"
import { ChatProvider } from "@/components/chat/chat-runtime"
import { clearChatsExcept, fingerprint } from "@/components/chat/chat-storage"
import { answersToolkit, reviseToolkit } from "@/components/chat/tool-cards"
import { Callout, ModeCallouts, Screen, ScrollBody, TopBar, useSettings, useShell } from "@/components/common"
import { JobProgress, useJob } from "@/components/job-progress"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, chatEndpoints, handoffUrl, type Job, type ProductDetail, type Usage } from "@/lib/api"
import { productHref } from "@/lib/route"
import { cn } from "@/lib/utils"
import { HistoryTab } from "@/pages/product-history"
import { PlayTab, reviseSeedKey } from "@/pages/product-play"
import { ArchitectureTab, ComponentsTab, OverviewTab, PromptTab, ReviewTab } from "@/pages/product-plan"

export function ProductPage({ slug, tab }: { slug: string; tab: string }) {
  const { reloadProducts } = useShell()
  const [product, setProduct] = useState<ProductDetail | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      setProduct(await api.product(slug))
      setError("")
    } catch (err) {
      setError((err as Error).message)
    }
    reloadProducts() // 侧边栏的待确认问题数跟着变
  }, [slug, reloadProducts])

  useEffect(() => {
    setProduct(null)
    load()
  }, [load])

  if (error) {
    return (
      <Screen>
        <TopBar title={slug} />
        <div className="mx-auto mt-10 max-w-xl px-4 text-sm text-destructive">{error}</div>
      </Screen>
    )
  }
  if (!product) return <Screen><TopBar title={slug} /></Screen>
  return <ProductView product={product} tab={tab} reload={load} />
}

function ProductView({ product, tab, reload }: { product: ProductDetail; tab: string; reload: () => Promise<void> }) {
  const { settings } = useSettings()
  const onFinish = useCallback(
    (job: Job) => {
      if (job.status === "done" && job.kind === "revise" && job.result) {
        const n = job.result.diff.length
        toast.success(`已升到 V${job.result.new_version}，${n ? `组件选型变了 ${n} 处` : "组件选型没有变化"}`)
        location.hash = productHref(product.slug, "history") // 看这一轮改了什么
      } else if (job.status === "done") {
        toast.success("方案已更新")
      }
      reload()
    },
    [reload, product.slug],
  )
  const job = useJob(product.job, onFinish)
  const plan = product.plan

  const startPlan = async () => {
    try {
      await api.startPlan(product.slug)
      await reload()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const bar = (
    <TopBar
      title={
        <>
          <span className="truncate">{product.name}</span>
          <span className="font-mono text-xs font-normal text-muted-foreground">V{product.version}</span>
        </>
      }
      actions={
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => api.reveal(product.slug).catch((e: Error) => toast.error(e.message))}
            title={product.path}
          >
            <FolderOpenIcon /> <span className="hidden sm:inline">打开文件夹</span>
          </Button>
          {plan && (
            <Button size="sm" nativeButton={false} render={<a href={handoffUrl(product.slug)} download />}>
              <DownloadIcon /> <span className="hidden sm:inline">导出交接包</span>
            </Button>
          )}
        </>
      }
    />
  )

  const progress = job && job.status !== "done" ? <JobProgress job={job} onResume={startPlan} /> : null

  if (!plan) {
    return (
      <Screen>
        {bar}
        <ScrollBody className="max-w-3xl">
          <ModeCallouts />
          {progress}
          {!job && (
            <Callout
              title="还没有方案"
              action={<Button onClick={startPlan} disabled={!settings.configured}>生成方案</Button>}
            >
              上次推导可能被中断了。重新推导时，已完成的阶段不会重复调用模型。
            </Callout>
          )}
        </ScrollBody>
      </Screen>
    )
  }

  return (
    <Screen>
      {bar}
      <PlanTabs product={product} tab={tab} reload={reload} running={job?.status === "running"} progress={progress} />
    </Screen>
  )
}

// 概览单独放最前；能对话的三项归一组，方案的细节归一组
const NAV: { group?: string; items: [string, string][] }[] = [
  { items: [["overview", "概览"]] },
  { group: "对话", items: [["answers", "回答问题"], ["play", "试玩"], ["revise", "加新需求"]] },
  { group: "方案", items: [["components", "组件选型"], ["architecture", "架构与工具"], ["prompt", "提示词与策略"], ["review", "审稿意见"]] },
  { group: "记录", items: [["history", "版本历史"]] },
]
const TABS = NAV.flatMap((g) => g.items)
const CHAT_TABS = new Set(["answers", "play", "revise"])

function PlanTabs({
  product,
  tab,
  reload,
  running,
  progress,
}: {
  product: ProductDetail
  tab: string
  reload: () => Promise<void>
  running: boolean
  progress: ReactNode
}) {
  const plan = product.plan!
  const active = TABS.some(([k]) => k === tab) ? tab : "overview"
  const go = (key: string) => {
    location.hash = productHref(product.slug, key)
  }
  const counts: Record<string, number> = {
    answers: plan.unknowns.length,
    architecture: plan.tool_list.length,
    review: plan.review.issues?.length ?? 0,
  }
  const count = (key: string) =>
    counts[key] ? <span className="ms-auto ps-2 font-mono text-xs font-normal text-muted-foreground">{counts[key]}</span> : null

  let body: ReactNode
  if (active === "answers") body = <AnswersTab product={product} reload={reload} running={running} />
  else if (active === "play") body = <PlayTab product={product} />
  else if (active === "revise") body = <RevisionTab product={product} reload={reload} running={running} />
  else {
    body = (
      <ScrollBody>
        <ModeCallouts />
        {progress && <div className="mb-6">{progress}</div>}
        {running && <Callout title="下面还是上一版方案">新方案推导完成后会自动刷新。</Callout>}
        {active === "overview" && <OverviewTab plan={plan} slug={product.slug} onAnswer={() => go("answers")} onComponents={() => go("components")} />}
        {active === "components" && <ComponentsTab plan={plan} />}
        {active === "architecture" && <ArchitectureTab plan={plan} />}
        {active === "prompt" && <PromptTab plan={plan} />}
        {active === "review" && <ReviewTab plan={plan} />}
        {active === "history" && (
          <HistoryTab
            slug={product.slug}
            names={Object.fromEntries(plan.components.map((c) => [c.id, c.name]))}
            refreshKey={`${product.version}:${product.updated}`}
          />
        )}
        <UsageFooter product={product} className="mt-10 text-center lg:hidden" />
      </ScrollBody>
    )
  }

  return (
    <div className="flex min-h-0 flex-1">
      <nav className="hidden w-44 shrink-0 flex-col border-e lg:flex">
        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
          {NAV.map((g, i) => (
            <div key={i} className={cn(i > 0 && "mt-4")}>
              {g.group && <div className="mb-1 px-2 font-mono text-xs tracking-wider text-muted-foreground">{g.group}</div>}
              {g.items.map(([key, label]) => (
                <a
                  key={key}
                  href={productHref(product.slug, key)}
                  className={cn(
                    "flex h-8 items-center rounded-md px-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                    active === key && "bg-muted font-medium text-foreground",
                  )}
                >
                  {label}
                  {count(key)}
                </a>
              ))}
            </div>
          ))}
        </div>
        <UsageFooter product={product} stacked className="border-t px-4 py-3" />
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="shrink-0 overflow-x-auto border-b px-2 lg:hidden">
          <Tabs value={active} onValueChange={(v) => go(String(v))}>
            <TabsList variant="line" className="h-10">
              {TABS.map(([key, label]) => (
                <TabsTrigger key={key} value={key} className="px-2.5">
                  {label}
                  {counts[key] ? <span className="ms-1 font-mono text-xs text-muted-foreground">{counts[key]}</span> : null}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </div>
        {running && CHAT_TABS.has(active) && (
          <div className="shrink-0 border-b bg-muted/50 px-4 py-2 text-xs text-muted-foreground">
            正在推导新方案，进度在
            <a href={productHref(product.slug)} className="mx-1 text-link hover:underline">概览</a>
            里看。
          </div>
        )}
        {body}
      </div>
    </div>
  )
}

/** 模型用量：左栏底部竖排成几行，窄屏时在内容最下面排成一行。 */
function UsageFooter({ product, stacked = false, className }: { product: ProductDetail; stacked?: boolean; className?: string }) {
  const plan = product.plan!
  const { total, chat } = product.usage
  const n = (x: number) => x.toLocaleString("zh-CN")
  // 早于用量记录建的产品没有累计数，只能显示最近一轮推导
  const { budget } = plan
  const [label, u]: [string, Usage] = total.calls
    ? ["累计", total]
    : ["最近一轮推导", { calls: budget.calls ?? 0, input_tokens: budget.input_tokens ?? 0, output_tokens: budget.output_tokens ?? 0 }]
  if (!u.calls) return null
  const tokens = stacked
    ? [`输入 ${n(u.input_tokens)} tokens`, `输出 ${n(u.output_tokens)} tokens`]
    : [`输入 ${n(u.input_tokens)} / 输出 ${n(u.output_tokens)} tokens`]
  const parts = [
    plan.runner === "mock" ? "离线演示" : "真实模型",
    `${label}调用 ${u.calls} 次`,
    ...tokens,
    `设计稿 ${plan.design_attempts} 版`,
  ]
  return (
    <div
      className={cn("text-xs leading-relaxed text-muted-foreground", className)}
      title={total.calls ? `其中对话 ${chat.calls} 次；新建产品时的三轮对话不计在内` : undefined}
    >
      {stacked ? parts.map((t) => <div key={t}>{t}</div>) : parts.join(" · ")}
    </div>
  )
}

/** 不能对话时（没配模型、正在推导）占位的提示。 */
function ChatBlocked({ children }: { children: ReactNode }) {
  return <ScrollBody className="max-w-3xl">{children}</ScrollBody>
}

function RevisionTab({ product, reload, running }: { product: ProductDetail; reload: () => Promise<void>; running: boolean }) {
  const { settings } = useSettings()
  const next = product.version + 1
  const toolkit = useMemo(() => reviseToolkit(product.slug, next, () => void reload()), [product.slug, next, reload])
  const initialMessages = useMemo(
    () => [{
      role: "assistant" as const,
      content:
        `想加什么新功能、改什么规则？直接说就行，比如「每周日晚上给家长发一份本周小结」。\n\n` +
        `我最多再问你一个问题，然后整理成一份草稿给你确认。确认后需求文档升到 V${next}，方案按新需求重新推导，没变的部分不重复花钱。`,
    }],
    [next],
  )

  if (!settings.configured) return <ChatBlocked><ModeCallouts /></ChatBlocked>
  if (running) return <ChatBlocked><Callout title="正在推导">等这一轮推导完成，再加新需求。</Callout></ChatBlocked>
  return (
    <ChatProvider
      key={`revise:${product.version}`}
      endpoint={chatEndpoints.revise(product.slug)}
      toolkit={toolkit}
      storageKey={`revise:${product.slug}:v${product.version}`}
      initialMessages={initialMessages}
    >
      <SeedComposer slug={product.slug} />
      <ChatPane hint={`当前是 V${product.version}。加的新需求会记进版本历史，随时能回看。`} placeholder="说说新需求…" />
    </ChatProvider>
  )
}

/** 从「试玩」带过来的「这里不对」放进输入框，用户可以再改，发送后照常走加新需求的对话。 */
function SeedComposer({ slug }: { slug: string }) {
  const aui = useAui()
  useEffect(() => {
    let seed: string | null = null
    try {
      seed = sessionStorage.getItem(reviseSeedKey(slug))
      sessionStorage.removeItem(reviseSeedKey(slug))
    } catch {
      /* 读不到就是空输入框 */
    }
    if (seed) aui.composer.setText(seed)
  }, [aui, slug])
  return null
}

// 与 blueprint/chat.py 的 HELP / SKIP 一致：服务端按原文识别这两个按钮
const OPENING_CHIPS = ["帮我想想", "跳过这题"]

function AnswersTab({ product, reload, running }: { product: ProductDetail; reload: () => Promise<void>; running: boolean }) {
  const { settings } = useSettings()
  const questions = product.plan!.unknowns
  const toolkit = useMemo(() => answersToolkit(product.slug, () => void reload()), [product.slug, reload])
  const initialMessages = useMemo(
    () => [{ role: "assistant" as const, content: product.answer_intro }],
    [product.answer_intro],
  )
  // 同一版问题共用一段对话；方案一变（问题变了）就换新的，旧的删掉
  const prefix = `answers:${product.slug}:`
  const storageKey = prefix + fingerprint(questions)
  useEffect(() => clearChatsExcept(prefix, storageKey), [prefix, storageKey])

  if (!questions.length) {
    return <ChatBlocked><Callout title="没有待确认的问题">方案里的信息很完整，不需要再补充。</Callout></ChatBlocked>
  }
  if (!settings.configured) return <ChatBlocked><ModeCallouts /></ChatBlocked>
  if (running) {
    return <ChatBlocked><Callout title="正在按你的回答重新推导">推导完成后，这里会换成新方案里的问题。</Callout></ChatBlocked>
  }
  return (
    <ChatProvider
      key={storageKey}
      endpoint={chatEndpoints.answers(product.slug)}
      toolkit={toolkit}
      storageKey={storageKey}
      initialMessages={initialMessages}
      initialChips={OPENING_CHIPS}
    >
      <ChatPane hint="回答会自动保存在这台电脑的浏览器里，切走再回来可以接着答。" placeholder="输入你的回答…" />
    </ChatProvider>
  )
}
