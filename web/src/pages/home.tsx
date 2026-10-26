import { ArrowRightIcon, PlusIcon } from "lucide-react"
import { useEffect, useState } from "react"

import { Chip, Eyebrow, ModeCallouts, PageHeader, timeAgo } from "@/components/common"
import { Button } from "@/components/ui/button"
import { api, type ProductSummary } from "@/lib/api"
import { productHref } from "@/lib/route"

const STEPS = [
  ["说出想法", "一句话就行。我会分三轮问你：给谁用、怎么用、什么不能做。"],
  ["引擎推导方案", "需求拆解、组件选型、架构和提示词，最后还有一轮独立审稿。"],
  ["回答问题，再迭代", "方案会列出还没想清楚的问题，在对话里一题一题答，答完自动重新推导。"],
]

export function HomePage() {
  const [products, setProducts] = useState<ProductSummary[] | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    api.products().then((r) => setProducts(r.products), (e: Error) => setError(e.message))
  }, [])

  if (error) return <div className="mx-auto mt-10 max-w-xl px-4 text-sm text-destructive">{error}</div>
  if (!products) return null

  if (!products.length) {
    return (
      <div className="mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
        <ModeCallouts />
        <h1 className="max-w-3xl text-4xl leading-[1.1] font-semibold tracking-tight sm:text-6xl">
          把一个想法，
          <br />
          推导成能做的 Agent 方案。
        </h1>
        <p className="mt-5 max-w-xl text-lg text-muted-foreground">
          不用懂技术，也不用会写需求文档。像聊天一样说清楚你想做什么，剩下的交给引擎。
        </p>
        <Button size="lg" className="mt-8 h-10 px-4" nativeButton={false} render={<a href="#/new" />}>
          开始一个新产品 <ArrowRightIcon />
        </Button>

        <div className="mt-20 grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3">
          {STEPS.map(([title, desc], i) => (
            <div key={title} className="bg-background p-5">
              <div className="font-mono text-xs text-muted-foreground">0{i + 1}</div>
              <div className="mt-3 font-medium">{title}</div>
              <p className="mt-1 text-sm text-muted-foreground">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6">
      <ModeCallouts />
      <PageHeader
        title="我的产品"
        sub="每个产品一个文件夹：需求文档、方案、迭代记录都在里面，随时可以接着做。"
        actions={
          <Button size="lg" nativeButton={false} render={<a href="#/new" />}>
            <PlusIcon /> 新建产品
          </Button>
        }
      />
      <div className="divide-y rounded-lg border bg-card">
        {products.map((p) => (
          <a
            key={p.slug}
            href={productHref(p.slug)}
            className="group flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4 transition-colors hover:bg-muted/50"
          >
            <span className="font-mono text-xs text-muted-foreground">V{p.version}</span>
            <span className="min-w-0 flex-1 truncate font-medium">{p.name}</span>
            <span className="flex gap-2">
              {!p.has_plan ? (
                <Chip>还没有方案</Chip>
              ) : p.unknowns ? (
                <Chip tone="ask">{p.unknowns} 个待确认问题</Chip>
              ) : (
                <Chip tone="ok">方案已生成</Chip>
              )}
            </span>
            <span className="w-20 text-right text-xs text-muted-foreground">{timeAgo(p.updated)}</span>
            <ArrowRightIcon className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
          </a>
        ))}
      </div>
      <Eyebrow className="mt-4">共 {products.length} 个产品 · 文件在引擎目录的 out/ 下</Eyebrow>
    </div>
  )
}
