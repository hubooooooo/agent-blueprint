import { DownloadIcon, FolderOpenIcon } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"

import { Thread } from "@/components/assistant-ui/elements/thread.aui"
import { ChatProvider } from "@/components/chat/chat-runtime"
import { clearChatsExcept, fingerprint } from "@/components/chat/chat-storage"
import { RestartButton } from "@/components/chat/restart-button"
import { answersToolkit, reviseToolkit } from "@/components/chat/tool-cards"
import { Callout, ModeCallouts, PageHeader, useSettings } from "@/components/common"
import { JobProgress, useJob } from "@/components/job-progress"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, chatEndpoints, handoffUrl, type Job, type ProductDetail } from "@/lib/api"
import { productHref } from "@/lib/route"
import { HistoryTab } from "@/pages/product-history"
import { ArchitectureTab, ComponentsTab, OverviewTab, PromptTab, ReviewTab } from "@/pages/product-plan"

export function ProductPage({ slug, tab }: { slug: string; tab: string }) {
  const [product, setProduct] = useState<ProductDetail | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      setProduct(await api.product(slug))
      setError("")
    } catch (err) {
      setError((err as Error).message)
    }
  }, [slug])

  useEffect(() => {
    setProduct(null)
    load()
  }, [load])

  if (error) return <div className="mx-auto mt-10 max-w-xl px-4 text-sm text-destructive">{error}</div>
  if (!product) return null
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

  const header = (
    <PageHeader
      crumb={<><a href="#/" className="hover:text-foreground">我的产品</a> / {product.name}</>}
      title={
        <span className="flex items-baseline gap-3">
          {product.name}
          <span className="font-mono text-base font-normal text-muted-foreground">V{product.version}</span>
        </span>
      }
      actions={
        <>
          <Button
            variant="outline"
            onClick={() => api.reveal(product.slug).catch((e: Error) => toast.error(e.message))}
            title={product.path}
          >
            <FolderOpenIcon /> 打开文件夹
          </Button>
          {plan && (
            <Button nativeButton={false} render={<a href={handoffUrl(product.slug)} download />}>
              <DownloadIcon /> 导出交接包
            </Button>
          )}
        </>
      }
    />
  )

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
      <ModeCallouts />
      {header}

      {job && job.status !== "done" && (
        <div className="mb-8">
          <JobProgress job={job} onResume={startPlan} />
        </div>
      )}

      {!plan && !job && (
        <Callout
          title="还没有方案"
          action={<Button onClick={startPlan} disabled={!settings.configured}>生成方案</Button>}
        >
          上次推导可能被中断了。重新推导时，已完成的阶段不会重复调用模型。
        </Callout>
      )}

      {plan && <PlanTabs product={product} tab={tab} reload={reload} running={job?.status === "running"} />}
    </div>
  )
}

const TABS = [
  ["overview", "概览"],
  ["answers", "回答问题"],
  ["revise", "加新需求"],
  ["history", "版本历史"],
  ["components", "组件选型"],
  ["architecture", "架构与工具"],
  ["prompt", "提示词与策略"],
  ["review", "审稿意见"],
] as const

function PlanTabs({ product, tab, reload, running }: { product: ProductDetail; tab: string; reload: () => Promise<void>; running: boolean }) {
  const plan = product.plan!
  const active = TABS.some(([k]) => k === tab) ? tab : "overview"
  const go = (key: string) => {
    location.hash = productHref(product.slug, key)
  }
  const counts: Record<string, number> = {
    overview: 0,
    answers: plan.unknowns.length,
    architecture: plan.tool_list.length,
    review: plan.review.issues?.length ?? 0,
  }

  return (
    <>
      {running && (
        <Callout title="下面还是上一版方案">新方案推导完成后会自动刷新。</Callout>
      )}
      <Tabs value={active} onValueChange={(v) => go(String(v))}>
        <div className="-mx-4 overflow-x-auto border-b px-4 sm:mx-0 sm:px-0">
          <TabsList variant="line" className="h-10">
            {TABS.map(([key, label]) => (
              <TabsTrigger key={key} value={key} className="px-3">
                {label}
                {counts[key] ? <span className="ms-1 font-mono text-xs text-muted-foreground">{counts[key]}</span> : null}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
      </Tabs>

      <div className="pt-8">
        {active === "overview" && <OverviewTab plan={plan} slug={product.slug} onAnswer={() => go("answers")} />}
        {active === "answers" && <AnswersTab product={product} reload={reload} running={running} />}
        {active === "components" && <ComponentsTab plan={plan} />}
        {active === "architecture" && <ArchitectureTab plan={plan} />}
        {active === "prompt" && <PromptTab plan={plan} />}
        {active === "review" && <ReviewTab plan={plan} />}
        {active === "revise" && <RevisionTab product={product} reload={reload} running={running} />}
        {active === "history" && (
          <HistoryTab
            slug={product.slug}
            names={Object.fromEntries(plan.components.map((c) => [c.id, c.name]))}
            refreshKey={`${product.version}:${product.updated}`}
          />
        )}
      </div>

      {plan.budget.calls ? (
        <p className="mt-12 text-center font-mono text-xs text-muted-foreground">
          {plan.runner === "mock" ? "离线演示" : "真实模型"} · 调用 {plan.budget.calls} 次 · 输入 {plan.budget.input_tokens} / 输出{" "}
          {plan.budget.output_tokens} tokens · 设计稿 {plan.design_attempts} 版
        </p>
      ) : null}
    </>
  )
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

  if (!settings.configured) return <ModeCallouts />
  if (running) return <Callout title="正在推导">等这一轮推导完成，再加新需求。</Callout>
  return (
    <ChatProvider
      key={`revise:${product.version}`}
      endpoint={chatEndpoints.revise(product.slug)}
      toolkit={toolkit}
      storageKey={`revise:${product.slug}:v${product.version}`}
      initialMessages={initialMessages}
    >
      <div className="mx-auto max-w-[46rem]">
        <div className="mb-2 flex min-h-8 items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">当前是 V{product.version}。加的新需求会记进版本历史，随时能回看。</p>
          <RestartButton />
        </div>
        <div className="h-[calc(100svh-24rem)] min-h-[26rem] overflow-hidden rounded-lg border bg-background">
          <Thread autoFocus={false} placeholder="说说新需求…" />
        </div>
      </div>
    </ChatProvider>
  )
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
    return <Callout title="没有待确认的问题">方案里的信息很完整，不需要再补充。</Callout>
  }
  if (!settings.configured) return <ModeCallouts />
  if (running) {
    return <Callout title="正在按你的回答重新推导">推导完成后，这里会换成新方案里的问题。</Callout>
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
      <div className="mx-auto max-w-[46rem]">
        <div className="mb-2 flex min-h-8 items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">回答会自动保存在这台电脑的浏览器里，切走再回来可以接着答。</p>
          <RestartButton />
        </div>
        <div className="h-[calc(100svh-24rem)] min-h-[26rem] overflow-hidden rounded-lg border bg-background">
          <Thread autoFocus={false} placeholder="输入你的回答…" />
        </div>
      </div>
    </ChatProvider>
  )
}
