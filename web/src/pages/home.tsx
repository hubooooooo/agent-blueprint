import { ArrowRightIcon, PlusIcon } from "lucide-react"

import { Chip, ModeCallouts, Screen, ScrollBody, TopBar, timeAgo, useShell } from "@/components/common"
import { Button } from "@/components/ui/button"
import { productHref } from "@/lib/route"

const STEPS = [
  ["说出想法", "一句话就行。我会分三轮问你：给谁用、怎么用、什么不能做。"],
  ["引擎推导方案", "需求拆解、组件选型、架构和提示词，最后还有一轮独立审稿。"],
  ["回答问题，再迭代", "方案会列出还没想清楚的问题，在对话里一题一题答，答完自动重新推导。"],
]

const newButton = (
  <Button size="sm" nativeButton={false} render={<a href="#/new" />}>
    <PlusIcon /> 新建产品
  </Button>
)

export function HomePage() {
  const { products } = useShell()
  if (!products) return <Screen><TopBar title="我的产品" /></Screen>

  if (!products.length) {
    return (
      <Screen>
        <TopBar title="我的产品" />
        <ScrollBody className="max-w-xl py-16">
          <ModeCallouts />
          <h1 className="text-xl font-semibold tracking-tight">把一个想法，推导成能做的 Agent 方案</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            不用懂技术，也不用会写需求文档。像聊天一样说清楚你想做什么，剩下的交给引擎。
          </p>
          <ol className="mt-6 divide-y rounded-lg border bg-card">
            {STEPS.map(([title, desc], i) => (
              <li key={title} className="flex gap-3 px-4 py-3">
                <span className="pt-0.5 font-mono text-xs text-muted-foreground">0{i + 1}</span>
                <div>
                  <div className="text-sm font-medium">{title}</div>
                  <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>
                </div>
              </li>
            ))}
          </ol>
          <Button className="mt-6" nativeButton={false} render={<a href="#/new" />}>
            开始一个新产品 <ArrowRightIcon />
          </Button>
        </ScrollBody>
      </Screen>
    )
  }

  return (
    <Screen>
      <TopBar
        title={<>我的产品 <span className="font-mono text-xs font-normal text-muted-foreground">{products.length}</span></>}
        actions={newButton}
      />
      <ScrollBody>
        <ModeCallouts />
        <div className="overflow-hidden rounded-lg border bg-card">
          <div className="grid grid-cols-[1fr_auto] gap-4 border-b px-4 py-2 font-mono text-xs tracking-wide text-muted-foreground sm:grid-cols-[3rem_1fr_10rem_6rem]">
            <span className="hidden sm:block">版本</span>
            <span>产品</span>
            <span className="hidden sm:block">状态</span>
            <span className="text-right">更新</span>
          </div>
          {products.map((p) => (
            <a
              key={p.slug}
              href={productHref(p.slug)}
              className="grid grid-cols-[1fr_auto] items-center gap-4 border-b px-4 py-2.5 text-sm transition-colors last:border-b-0 hover:bg-muted/50 sm:grid-cols-[3rem_1fr_10rem_6rem]"
            >
              <span className="hidden font-mono text-xs text-muted-foreground sm:block">V{p.version}</span>
              <span className="min-w-0 truncate font-medium">{p.name}</span>
              <span className="hidden sm:block">
                {!p.has_plan ? (
                  <Chip>还没有方案</Chip>
                ) : p.unknowns ? (
                  <Chip tone="ask">{p.unknowns} 个待确认问题</Chip>
                ) : (
                  <Chip tone="ok">方案已生成</Chip>
                )}
              </span>
              <span className="text-right text-xs text-muted-foreground">{timeAgo(p.updated)}</span>
            </a>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">每个产品一个文件夹，需求文档、方案、迭代记录都在引擎目录的 out/ 下。</p>
      </ScrollBody>
    </Screen>
  )
}
