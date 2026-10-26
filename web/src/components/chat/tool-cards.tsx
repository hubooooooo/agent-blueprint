import type { Toolkit, ToolCallMessagePartProps } from "@assistant-ui/react"
import { ArrowRightIcon } from "lucide-react"
import { useState } from "react"

import { JobProgress, useJob } from "@/components/job-progress"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { api, type Job } from "@/lib/api"

// 服务端（blueprint/chat.py）发来 tool 事件时，对话里弹出这些卡片。卡片是 human tool：
// 用户在卡片上确认后调用 addResult，对话随之结束；之后卡片原地变成推导进度。

const CARD = "my-3 rounded-lg border bg-card p-4"

type StartedResult = { slug: string; job: Job }

// ---------------------------------------------------------------------------
// 新建产品：确认需求草稿
// ---------------------------------------------------------------------------

type ProductArgs = { name: string; idea: string }

function ConfirmProductCard({ args, result, status, addResult }: ToolCallMessagePartProps<ProductArgs, StartedResult>) {
  const [name, setName] = useState(args.name ?? "")
  const [idea, setIdea] = useState(args.idea ?? "")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  if (result) return <StartedCard result={result} title={`「${name}」`} />

  const waiting = status.type === "requires-action"
  const submit = async () => {
    if (!name.trim() || !idea.trim()) return setError("产品名和需求都要有内容。")
    setBusy(true)
    setError("")
    try {
      addResult(await api.createProduct(name, idea))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <div className={CARD}>
      <div className="mb-3 font-mono text-xs tracking-wide text-muted-foreground uppercase">需求草稿</div>
      <label className="mb-1 block text-sm font-medium" htmlFor="draft-name">产品名</label>
      <Input id="draft-name" value={name} onChange={(e) => setName(e.target.value)} disabled={!waiting || busy} maxLength={40} />
      <label className="mt-3 mb-1 block text-sm font-medium" htmlFor="draft-idea">需求</label>
      <Textarea
        id="draft-idea"
        value={idea}
        onChange={(e) => setIdea(e.target.value)}
        disabled={!waiting || busy}
        className="min-h-56 font-normal leading-relaxed"
      />
      <p className="mt-2 text-xs text-muted-foreground">
        「还没想清楚」里的问题不用现在回答，方案生成后会列成待确认问题，到时候再一题一题过。
      </p>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
      {waiting && (
        <Button className="mt-3" size="lg" onClick={submit} disabled={busy}>
          {busy ? "正在创建…" : "开始推导方案"}
        </Button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 回答待确认问题：确认回答汇总
// ---------------------------------------------------------------------------

type AnswersArgs = { answers: { question: string; answer: string }[] }

function makeConfirmAnswersCard(slug: string, onStarted: () => void) {
  return function ConfirmAnswersCard({ args, result, status, addResult }: ToolCallMessagePartProps<AnswersArgs, StartedResult>) {
    const [answers, setAnswers] = useState(args.answers ?? [])
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState("")

    if (result) return <StartedCard result={result} title="回答已写进需求文档" />

    const waiting = status.type === "requires-action"
    const submit = async () => {
      setBusy(true)
      setError("")
      try {
        const res = await api.saveAnswers(slug, answers)
        addResult({ slug, job: res.job })
        onStarted() // 产品页顶部接手显示进度，推导完自动换成新方案
      } catch (err) {
        setError((err as Error).message)
        setBusy(false)
      }
    }

    return (
      <div className={CARD}>
        <div className="mb-3 font-mono text-xs tracking-wide text-muted-foreground uppercase">
          回答汇总 · {answers.length} 条
        </div>
        <ol className="space-y-3">
          {answers.map((a, i) => (
            <li key={i}>
              <div className="flex gap-2 text-sm">
                <span className="font-mono text-xs leading-5 text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                <span className="text-muted-foreground">{a.question}</span>
              </div>
              <Textarea
                value={a.answer}
                disabled={!waiting || busy}
                onChange={(e) => setAnswers(answers.map((x, j) => (j === i ? { ...x, answer: e.target.value } : x)))}
                className="mt-1 min-h-10"
              />
            </li>
          ))}
        </ol>
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        {waiting && (
          <Button className="mt-4" size="lg" onClick={submit} disabled={busy}>
            {busy ? "正在保存…" : "保存并重新推导方案"}
          </Button>
        )}
      </div>
    )
  }
}

// ---------------------------------------------------------------------------
// 加新需求：确认需求变更草稿
// ---------------------------------------------------------------------------

type RevisionArgs = { title: string; requirement: string }

function makeConfirmRevisionCard(slug: string, nextVersion: number, onStarted: () => void) {
  return function ConfirmRevisionCard({ args, result, status, addResult }: ToolCallMessagePartProps<RevisionArgs, StartedResult>) {
    const [title, setTitle] = useState(args.title ?? "")
    const [requirement, setRequirement] = useState(args.requirement ?? "")
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState("")

    if (result) return <StartedCard result={result} title={`已升到 V${nextVersion}：${title}`} />

    const waiting = status.type === "requires-action"
    const submit = async () => {
      if (!requirement.trim()) return setError("新需求不能为空。")
      setBusy(true)
      setError("")
      try {
        const res = await api.startRevise(slug, title, requirement)
        addResult({ slug, job: res.job })
        onStarted() // 产品页顶部接手显示进度，推导完跳到「版本历史」看选型变化
      } catch (err) {
        setError((err as Error).message)
        setBusy(false)
      }
    }

    return (
      <div className={CARD}>
        <div className="mb-3 font-mono text-xs tracking-wide text-muted-foreground uppercase">需求变更草稿 · V{nextVersion}</div>
        <label className="mb-1 block text-sm font-medium" htmlFor="rev-title">一句话标题</label>
        <Input id="rev-title" value={title} onChange={(e) => setTitle(e.target.value)} disabled={!waiting || busy} maxLength={40} />
        <label className="mt-3 mb-1 block text-sm font-medium" htmlFor="rev-body">新需求</label>
        <Textarea
          id="rev-body"
          value={requirement}
          onChange={(e) => setRequirement(e.target.value)}
          disabled={!waiting || busy}
          className="min-h-48 leading-relaxed"
        />
        <p className="mt-2 text-xs text-muted-foreground">
          确认后，需求文档升到 V{nextVersion}（旧版本会留一份），方案按新需求重新推导；没变的部分沿用上次的结果，不重复花钱。
        </p>
        {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        {waiting && (
          <Button className="mt-3" size="lg" onClick={submit} disabled={busy}>
            {busy ? "正在升级…" : `升到 V${nextVersion} 并重新推导`}
          </Button>
        )}
      </div>
    )
  }
}

// ---------------------------------------------------------------------------

function StartedCard({ result, title }: { result: StartedResult; title: string }) {
  const job = useJob(result.job)
  if (!job) return null
  return (
    <div className={CARD}>
      <div className="mb-1 text-sm font-medium">{title}</div>
      <JobProgress job={job} compact />
      {job.status === "failed" && (
        <p className="mt-2 text-sm text-muted-foreground">到产品页点「继续推导」可以从断点接着跑。</p>
      )}
      <Button
        className="mt-3"
        variant={job.status === "done" ? "default" : "outline"}
        nativeButton={false}
        render={<a href={`#/p/${encodeURIComponent(result.slug)}`} />}
      >
        {job.status === "done" ? "查看方案" : "打开产品页"} <ArrowRightIcon />
      </Button>
    </div>
  )
}

const ANY_OBJECT = { type: "object" } as const

export const intakeToolkit: Toolkit = {
  confirm_product: { type: "human", parameters: ANY_OBJECT, render: ConfirmProductCard },
}

export function reviseToolkit(slug: string, nextVersion: number, onStarted: () => void): Toolkit {
  return {
    confirm_revision: { type: "human", parameters: ANY_OBJECT, render: makeConfirmRevisionCard(slug, nextVersion, onStarted) },
  }
}

export function answersToolkit(slug: string, onStarted: () => void): Toolkit {
  return {
    confirm_answers: { type: "human", parameters: ANY_OBJECT, render: makeConfirmAnswersCard(slug, onStarted) },
  }
}
