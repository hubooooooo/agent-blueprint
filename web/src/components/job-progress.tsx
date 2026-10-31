import { CheckIcon, LoaderCircleIcon, XIcon } from "lucide-react"
import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { api, type Job } from "@/lib/api"
import { cn } from "@/lib/utils"

export type Stage = { mark: string; label: string; desc: string }

export const PLAN_STAGES: Stage[] = [
  { mark: "①", label: "需求拆解", desc: "把想法拆成目标、用户、核心闭环等硬事实" },
  { mark: "②", label: "领域建模", desc: "对应到工具、知识、观察、行动、权限五要素" },
  { mark: "③", label: "组件选型", desc: "按固定规则决定 17 个组件选哪些，不调模型" },
  { mark: "④", label: "架构设计", desc: "工具清单、系统提示词、七层架构" },
  { mark: "⑤", label: "独立审稿", desc: "换个视角挑方案里的矛盾，不通过就打回重写一次" },
  { mark: "⑥", label: "整理待确认问题", desc: "改成大白话、合并重复、把最关键的排前面" },
  { mark: "⑦", label: "整理需求文档", desc: "把你说过的、答过的、新加的，写进需求文档各节" },
]

/** 检查外部项目的四步，日志格式见 blueprint/reverse.py 的 run_audit。 */
export const AUDIT_STAGES: Stage[] = [
  { mark: "①", label: "盘点项目", desc: "列出文件、依赖和入口，只在本机做，不调模型" },
  { mark: "②", label: "读代码", desc: "agent 读代码，反推这个项目在做什么，逐个核实 17 个组件" },
  { mark: "③", label: "对照打分", desc: "按固定规则算出它应该有什么，和现在的代码对照" },
  { mark: "④", label: "独立复核", desc: "换个视角，挑出报告里站不住的判断" },
]

type Wording = { running: string; failed: string; done: string; hint: string; resume: string }

const PLAN_WORDING: Wording = {
  running: "正在推导方案",
  failed: "推导中断",
  done: "推导完成",
  hint: "大约需要 2–5 分钟。可以先去做别的，关掉这个页面也不影响；只要别关启动界面的那个终端窗口。",
  resume: "继续推导",
}

export const AUDIT_WORDING: Wording = {
  running: "正在检查",
  failed: "检查中断",
  done: "检查完成",
  hint: "大约需要 3–8 分钟，项目越大越久。可以先去做别的，关掉这个页面也不影响；只要别关启动界面的那个终端窗口。",
  resume: "继续检查",
}

type StageState = "todo" | "active" | "done" | "failed"

/** 从任务日志推出每个阶段的状态。日志格式见 blueprint/pipeline.py 的 StageRunner.run。
 *  agent 每调一次工具记一行「· 读 xxx」，进行中的阶段把最新一行显示出来，看得到它在干什么。 */
function stageStates(job: Job, stages: Stage[]) {
  let current = -1
  let rewrite = false
  let activity = ""
  for (const line of job.logs) {
    const idx = stages.findIndex((s) => line.includes(s.mark))
    if (idx >= 0 && (line.includes("▶") || line.includes("↻"))) {
      if (idx > current) activity = ""
      current = Math.max(current, idx)
    }
    if (line.includes("按审稿意见重写")) rewrite = true
    if (line.trim().startsWith("· ")) activity = line.trim().slice(2)
  }
  return stages.map((s, i) => {
    let state: StageState = "todo"
    if (job.status === "done" || i < current) state = "done"
    else if (i === current) state = job.status === "failed" ? "failed" : "active"
    return { ...s, state, note: rewrite && i >= 3 ? "第 2 版" : "", activity: state === "active" ? activity : "" }
  })
}

function duration(sec: number) {
  sec = Math.max(0, Math.round(sec))
  return sec < 60 ? `${sec} 秒` : `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`
}

/** 轮询一个任务直到结束；结束时回调一次。 */
export function useJob(initial: Job | null, onFinish?: (job: Job) => void) {
  const [job, setJob] = useState(initial)
  const id = initial?.id

  useEffect(() => setJob(initial), [initial])

  useEffect(() => {
    if (!id || job?.status !== "running") return
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const fresh = await api.job(id)
        if (cancelled) return
        setJob(fresh)
        if (fresh.status !== "running") onFinish?.(fresh)
      } catch {
        if (!cancelled) setJob((j) => (j ? { ...j } : j)) // 网络抖动：触发下一轮重试
      }
    }, 1500)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [id, job, onFinish])

  return job
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(t)
  }, [active])
  return now
}

export function JobProgress({
  job,
  onResume,
  compact = false,
  stages = PLAN_STAGES,
  wording = PLAN_WORDING,
}: {
  job: Job
  onResume?: () => void
  compact?: boolean
  stages?: Stage[]
  wording?: Wording
}) {
  const running = job.status === "running"
  const now = useNow(running)
  const elapsed = (job.finished ?? now) - job.started
  const title = running ? wording.running : job.status === "failed" ? wording.failed : wording.done

  return (
    <div className={cn(!compact && "rounded-lg border bg-card p-5")}>
      <div className="flex items-baseline justify-between gap-3">
        <h3 className={cn("font-medium", compact ? "text-sm" : "text-base")}>
          {title}
          {running && <span className="shimmer ms-1">…</span>}
        </h3>
        <span className="font-mono text-xs text-muted-foreground">{duration(elapsed)}</span>
      </div>
      {running && !compact && (
        <p className="mt-1 text-sm text-muted-foreground">{wording.hint}</p>
      )}

      <ol className="mt-3">
        {stageStates(job, stages).map((s, i) => (
          <li
            key={s.mark}
            className={cn(
              "flex items-center gap-3 border-t border-dashed py-2 first:border-t-0",
              s.state === "todo" && "text-muted-foreground",
            )}
          >
            <span
              className={cn(
                "grid size-5 shrink-0 place-items-center rounded-full border",
                s.state === "done" && "border-ok bg-ok text-background",
                s.state === "failed" && "border-destructive bg-destructive text-background",
                s.state === "active" && "border-foreground",
              )}
            >
              {s.state === "done" && <CheckIcon className="size-3" />}
              {s.state === "failed" && <XIcon className="size-3" />}
              {s.state === "active" && <LoaderCircleIcon className="size-3 animate-spin" />}
            </span>
            <span className="w-6 font-mono text-xs text-muted-foreground">0{i + 1}</span>
            <div className="min-w-0 flex-1">
              <div className={cn("text-sm", s.state === "active" && "font-medium")}>{s.label}</div>
              {!compact && (
                <div className={cn("text-xs text-muted-foreground", s.activity && "truncate font-mono")} title={s.activity || undefined}>
                  {s.activity || s.desc}
                </div>
              )}
            </div>
            {s.note && <span className="font-mono text-xs text-muted-foreground">{s.note}</span>}
          </li>
        ))}
      </ol>

      {job.status === "failed" && (
        <div className="mt-3 rounded-md bg-destructive/8 p-3 text-sm">
          <p className="text-destructive">{job.error}</p>
          {onResume && (
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={onResume}>{wording.resume}</Button>
              <Button size="sm" variant="outline" nativeButton={false} render={<a href="#/settings" />}>
                检查模型设置
              </Button>
            </div>
          )}
        </div>
      )}

      {!compact && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-xs text-muted-foreground">详细日志</summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {job.logs.join("\n") || "（还没有输出）"}
          </pre>
        </details>
      )}
    </div>
  )
}
