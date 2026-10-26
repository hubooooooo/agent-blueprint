import { ArrowRightIcon, CopyIcon, DownloadIcon } from "lucide-react"
import { useState, type ReactNode } from "react"
import { toast } from "sonner"

import { Chip, DECISIONS, Eyebrow } from "@/components/common"
import { Button } from "@/components/ui/button"
import { handoffUrl, type Plan, type Question } from "@/lib/api"
import { cn } from "@/lib/utils"

// 方案的五个标签页，数据来自 blueprint/web/views.py 的 plan_view。

function Section({ title, aside, children, className }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("border-t pt-6 pb-10", className)}>
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  )
}

function ReviewChip({ review }: { review: Plan["review"] }) {
  const score = review.score != null ? ` · ${review.score} 分` : ""
  return review.ok ? <Chip tone="ok">审稿通过{score}</Chip> : <Chip tone="warn">审稿未通过{score}</Chip>
}

/** 细线表格：等宽表头，assistant-ui 的「登记簿」样式。 */
function Ledger({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="-mx-4 overflow-x-auto sm:mx-0">
      <table className="w-full min-w-[36rem] border-collapse text-sm">
        <thead>
          <tr className="border-b">
            {head.map((h) => (
              <th key={h} className="px-3 py-2 text-left font-mono text-xs font-normal tracking-wide text-muted-foreground uppercase first:ps-4 sm:first:ps-0">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b last:border-b-0">
              {r.map((c, j) => (
                <td key={j} className="px-3 py-2.5 align-top first:ps-4 sm:first:ps-0">{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 组件类问题末尾的「（关系到组件 s07 技能加载）」拆出来，做成小标签。 */
function QuestionText({ q }: { q: Question }) {
  const m = q.text.match(/^(.*)（关系到组件 (.+)）$/)
  return (
    <span title={q.original === q.text ? undefined : `原问题：${q.original}`}>
      {m ? m[1] : q.text}
      {m && <span className="ms-2 inline-block font-mono text-xs whitespace-nowrap text-muted-foreground">{m[2]}</span>}
    </span>
  )
}

function NextStep({ plan, slug }: { plan: Plan; slug: string }) {
  const left = plan.questions.length
  return (
    <Section title="下一步：交给会写代码的人">
      <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-3 text-sm leading-relaxed">
          <p>
            方案定下来以后，导出一个<strong>交接包</strong>（zip 文件），发给帮你做产品的开发者。里面有需求文档、方案、还没定下来的问题，以及第一版要用到的组件的参考代码。
          </p>
          <p className="text-muted-foreground">
            对方如果用 Claude Code、Cursor 这类 AI 编程工具，解压后把「给AI编程工具的提示词.md」里的话交给它，它会先读需求、把不清楚的地方问你，再按方案写代码。
          </p>
          {left > 0 && (
            <p className="rounded-md bg-ask-soft px-3 py-2 text-ask">
              还有 {left} 个问题没回答。建议先答完再导出；也可以先导出，开发者会把这些问题带回来问你。
            </p>
          )}
        </div>
        <div className="rounded-lg border bg-card p-4">
          <Eyebrow>交接包</Eyebrow>
          <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
            <li>交接说明.md · 从这里开始</li>
            <li>给AI编程工具的提示词.md</li>
            <li>PRD.md · 方案.md · 迭代记录.md</li>
            <li>参考组件/ · {plan.components.filter((c) => c.decision === "必选").length} 个必选组件</li>
          </ul>
          <Button className="mt-4 w-full" size="lg" nativeButton={false} render={<a href={handoffUrl(slug)} download />}>
            <DownloadIcon /> 导出交接包
          </Button>
          <p className="mt-2 text-xs text-muted-foreground">
            方案每更新一次，记得重新导出。
          </p>
        </div>
      </div>
    </Section>
  )
}

const SHOW_FIRST = 8

/** 关键问题（priority 1）排在最前、带标签；超过 8 个时其余的折起来，免得一眼看过去吓人。 */
function QuestionList({ questions }: { questions: Question[] }) {
  const [all, setAll] = useState(false)
  const shown = all ? questions : questions.slice(0, SHOW_FIRST)
  const key = questions.filter((q) => q.priority === 1).length
  return (
    <>
      {key > 0 && (
        <p className="mb-2 text-sm">
          其中 <span className="font-medium">{key} 个关键问题</span> 排在最前面：不回答就没法动手，或者会让方案大改。
        </p>
      )}
      <ol>
        {shown.map((q, i) => (
          <li key={i} className="flex gap-4 border-t py-3 first:border-t-0">
            <span className="pt-0.5 font-mono text-xs text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
            <span className="min-w-0 flex-1">
              {q.priority === 1 && <Chip tone="ink" className="me-2 align-[1px]">关键</Chip>}
              <QuestionText q={q} />
            </span>
          </li>
        ))}
      </ol>
      {questions.length > SHOW_FIRST && (
        <Button variant="ghost" size="sm" className="mt-1 text-muted-foreground" onClick={() => setAll(!all)}>
          {all ? "收起" : `还有 ${questions.length - SHOW_FIRST} 个问题，展开`}
        </Button>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------

export function OverviewTab({ plan, slug, onAnswer }: { plan: Plan; slug: string; onAnswer: () => void }) {
  const counts = Object.fromEntries(DECISIONS.map((d) => [d.key, plan.components.filter((c) => c.decision === d.key).length]))
  return (
    <div>
      <div className="pb-10">
        <div className="flex flex-wrap items-center gap-3">
          <Eyebrow>产品定位</Eyebrow>
          <ReviewChip review={plan.review} />
        </div>
        <p className="mt-3 max-w-3xl text-xl leading-relaxed">{plan.one_liner || plan.title}</p>
        <div className="mt-8 grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-4">
          {DECISIONS.map((d) => (
            <div key={d.key} className="bg-background px-4 py-3">
              <div className={cn("font-mono text-3xl", d.tone === "ok" && "text-ok", d.tone === "warn" && "text-warn", d.tone === "ask" && "text-ask", d.tone === "muted" && "text-muted-foreground")}>
                {String(counts[d.key]).padStart(2, "0")}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">{d.key}组件</div>
            </div>
          ))}
        </div>
      </div>

      <Section
        title={`待确认问题（${plan.questions.length}）`}
        aside={plan.questions.length ? <Button onClick={onAnswer}>开始回答 <ArrowRightIcon /></Button> : null}
      >
        {plan.questions.length ? (
          <>
            <p className="-mt-2 mb-4 text-sm text-muted-foreground">
              答不上来的就是风险点。点「开始回答」在对话里一题一题过，拿不准的可以让 AI 给你几个方向；答完自动重新推导。
            </p>
            <QuestionList questions={plan.questions} />
          </>
        ) : (
          <p className="text-muted-foreground">没有需要你回答的问题了。</p>
        )}
        {plan.dev_items.length > 0 && (
          <details className="mt-6 rounded-lg border px-4 py-3">
            <summary className="cursor-pointer text-sm">
              交给开发者的技术备注 <span className="font-mono text-xs text-muted-foreground">{plan.dev_items.length}</span>
              <span className="ms-2 text-muted-foreground">· 你不用回答，交接包里会带给开发者</span>
            </summary>
            <ol className="mt-3 space-y-2 text-sm text-muted-foreground">
              {plan.dev_items.map((q, i) => (
                <li key={i} className="flex gap-3">
                  <span className="font-mono text-xs">{String(i + 1).padStart(2, "0")}</span>
                  <span title={q.original}>{q.text}</span>
                </li>
              ))}
            </ol>
          </details>
        )}
      </Section>

      <NextStep plan={plan} slug={slug} />

      <Section title="需求拆解">
        <Ledger
          head={["维度", "结论", "状态"]}
          rows={plan.facts.map((f) => [
            <span className="font-medium whitespace-nowrap">{f.label}</span>,
            f.value || <span className="text-muted-foreground">（空）</span>,
            <Chip tone={f.status === "明确" ? "ok" : "ask"}>{f.status}</Chip>,
          ])}
        />
      </Section>
    </div>
  )
}

const BORDER = { ok: "border-l-ok", warn: "border-l-warn", ask: "border-l-ask", muted: "border-l-border" } as const

export function ComponentsTab({ plan }: { plan: Plan }) {
  return (
    <div>
      <p className="mb-8 max-w-3xl text-muted-foreground">
        引擎内置 17 个 Harness 组件。选不选由固定规则决定：模型只判断需求有没有某个特征，同样的判断永远得到同样的选型。原则是只选需要的。
      </p>
      {DECISIONS.map((d) => {
        const items = plan.components.filter((c) => c.decision === d.key)
        if (!items.length) return null
        return (
          <Section
            key={d.key}
            title={<span className="flex items-center gap-2"><Chip tone={d.tone}>{d.key}</Chip><span className="font-mono text-sm text-muted-foreground">{items.length}</span></span>}
            aside={<span className="text-sm text-muted-foreground">{d.hint}</span>}
            className="pb-8"
          >
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((c) => (
                <div key={c.id} className={cn("rounded-md border border-l-2 bg-card px-4 py-3", BORDER[d.tone])}>
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-xs text-muted-foreground">{c.id}</span>
                    <span className={cn("font-medium", d.tone === "muted" && "text-muted-foreground")}>{c.name}</span>
                    <span className="ms-auto text-xs text-muted-foreground">{c.domain}</span>
                  </div>
                  <p className="mt-1.5 text-sm text-muted-foreground">{c.reason}</p>
                </div>
              ))}
            </div>
          </Section>
        )
      })}
    </div>
  )
}

const PERMISSION = { allow: ["直接执行", "ok"], ask: ["需人确认", "warn"], deny: ["禁止", "bad"] } as const

export function ArchitectureTab({ plan }: { plan: Plan }) {
  return (
    <div>
      <Section title="七层架构" className="border-t-0 pt-0">
        <div className="overflow-hidden rounded-lg border">
          {plan.layers.map((l) => (
            <div
              key={l.num}
              className={cn("grid gap-1 border-b px-4 py-3 last:border-b-0 sm:grid-cols-[12rem_1fr] sm:gap-6", l.num === "③" && "bg-muted/60")}
            >
              <div>
                <div className="font-medium">{l.num} {l.name}</div>
                <div className="text-xs text-muted-foreground">{l.question}</div>
              </div>
              <div className="text-sm sm:self-center">{l.detail}</div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="工具清单" aside={<span className="font-mono text-sm text-muted-foreground">{plan.tool_list.length}</span>}>
        {plan.tool_list.length ? (
          <Ledger
            head={["工具", "输入", "输出", "副作用", "权限", "层"]}
            rows={plan.tool_list.map((t) => {
              const [label, tone] = PERMISSION[t.permission] ?? [t.permission, "muted"]
              return [
                <code className="font-mono text-xs">{t.name}</code>,
                t.input,
                t.output,
                t.side_effect,
                <Chip tone={tone}>{label}</Chip>,
                t.layer,
              ]
            })}
          />
        ) : (
          <p className="text-muted-foreground">（没有生成工具清单）</p>
        )}
      </Section>

      <Section title="五要素">
        <Ledger
          head={["要素", "内容"]}
          rows={plan.elements.map((e) => [
            <span className="font-medium whitespace-nowrap">{e.label}</span>,
            e.items.length ? e.items.join("；") : <span className="text-muted-foreground">（待补充）</span>,
          ])}
        />
      </Section>
    </div>
  )
}

export function PromptTab({ plan }: { plan: Plan }) {
  const obs = plan.observability
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(plan.system_prompt)
      toast.success("已复制系统提示词")
    } catch {
      toast.error("复制失败，请手动选中复制")
    }
  }
  return (
    <div>
      <Section
        title="系统提示词草案"
        className="border-t-0 pt-0"
        aside={plan.system_prompt ? <Button variant="outline" size="sm" onClick={copy}><CopyIcon /> 复制</Button> : null}
      >
        <pre className="max-h-[32rem] overflow-auto rounded-lg bg-muted p-5 font-mono text-[13px] leading-relaxed whitespace-pre-wrap">
          {plan.system_prompt || "（空）"}
        </pre>
      </Section>
      <Section title="上下文与记忆策略">
        <p className="leading-relaxed whitespace-pre-wrap">{plan.context_memory_strategy || "（空）"}</p>
      </Section>
      <Section title="安全边界与降级策略">
        <ul className="space-y-2">
          {plan.security_and_degradation.map((s, i) => (
            <li key={i} className="flex gap-3"><span className="text-muted-foreground">—</span>{s}</li>
          ))}
        </ul>
      </Section>
      <Section title="可观测性">
        <Ledger
          head={["类别", "内容"]}
          rows={[
            ["日志", (obs.logs ?? []).join("；")],
            ["指标", (obs.metrics ?? []).join("；")],
            ["轨迹", obs.trajectory ?? ""],
          ]}
        />
      </Section>
      <Section title="技术栈与部署形态">
        <p className="leading-relaxed whitespace-pre-wrap">{plan.tech_stack_and_deployment || "（空）"}</p>
      </Section>
    </div>
  )
}

const SEVERITY = { high: ["严重", "bad"], medium: ["中等", "warn"], low: ["轻微", "muted"] } as const

export function ReviewTab({ plan }: { plan: Plan }) {
  const r = plan.review
  return (
    <div>
      <Section title={<span className="flex items-center gap-3">独立审稿 <ReviewChip review={r} /></span>} className="border-t-0 pt-0">
        <p className="max-w-3xl leading-relaxed">{r.summary}</p>
        <p className="mt-4 max-w-3xl text-sm text-muted-foreground">
          审稿经常给出「未通过」，这是设计如此：审稿就是要把方案里的矛盾挑出来，这些意见就是你下一轮要想清楚的问题。
        </p>
      </Section>
      {r.issues?.length ? (
        <Section title="意见" aside={<span className="font-mono text-sm text-muted-foreground">{r.issues.length}</span>}>
          <ol>
            {r.issues.map((i, n) => {
              const [label, tone] = SEVERITY[i.severity ?? "low"] ?? ["意见", "muted"]
              return (
                <li key={n} className="grid gap-2 border-t py-3 first:border-t-0 sm:grid-cols-[4rem_1fr]">
                  <div><Chip tone={tone}>{label}</Chip></div>
                  <div>
                    <div className="font-medium">{i.section}</div>
                    <div className="text-sm text-muted-foreground">{i.problem}</div>
                  </div>
                </li>
              )
            })}
          </ol>
        </Section>
      ) : null}
    </div>
  )
}
