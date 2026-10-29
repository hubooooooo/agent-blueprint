import { ArrowRightIcon, FolderOpenIcon, FolderSearchIcon, RefreshCwIcon, ScaleIcon, ScanSearchIcon } from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { toast } from "sonner"

import { Callout, Chip, ModeCallouts, READING, Screen, ScrollBody, TopBar, timeAgo, useSettings, useShell } from "@/components/common"
import { AUDIT_STAGES, AUDIT_WORDING, JobProgress, useJob } from "@/components/job-progress"
import { Markdown } from "@/components/markdown"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, type AuditDetail, type AuditMode, type AuditSummary, type Job } from "@/lib/api"
import { auditHref } from "@/lib/route"

/** 删掉表头含 header 的那张表的最后一列。 */
function dropLastColumn(md: string, header: string) {
  let inTable = false
  return md
    .split("\n")
    .map((line) => {
      if (line.startsWith("|") && line.includes(`| ${header} |`)) inTable = true
      else if (!line.startsWith("|")) inTable = false
      return inTable ? line.replace(/\|[^|]*\|\s*$/, "|") : line
    })
    .join("\n")
}

/** 报告文件终端和网页共用，网页上做三处删减：大标题和「一句话判定」上面的摘要卡片已经有了；
 *  「去哪看」是引擎里组件教程的路径，给用命令行的开发者看的，网页上点不开，还会把表格挤窄。 */
function reportBody(report: string) {
  const body = report.replace(/^# .*\n+/, "").replace(/## 一句话判定\n[\s\S]*?(?=\n## )/, "")
  return dropLastColumn(body, "去哪看")
}

const pct = (x: number | null) => (x == null ? "" : `${Math.round(x * 100)}%`)

function verdictTone(a: AuditSummary) {
  if (a.completion == null) return "muted" as const
  return a.completion >= 0.8 ? ("ok" as const) : a.completion >= 0.3 ? ("warn" as const) : ("bad" as const)
}

const startButton = (
  <Button size="sm" nativeButton={false} render={<a href="#/audits/new" />}>
    <ScanSearchIcon /> 检查一个项目
  </Button>
)

// -- 列表 --------------------------------------------------------------------

export function AuditsPage() {
  const { audits } = useShell()
  if (!audits) return <Screen><TopBar title="检查过的项目" /></Screen>

  if (!audits.length) {
    return (
      <Screen>
        <TopBar title="检查过的项目" />
        <ScrollBody className="max-w-xl py-16">
          <ModeCallouts />
          <h1 className="text-xl font-semibold tracking-tight">看看一个已有的 Agent 项目还差什么</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            选一个项目文件夹，引擎让 agent 读代码，告诉你它离一个靠谱的 Agent 还差哪些机制，并反推一份它本该有的需求文档。
          </p>
          <Button className="mt-6" nativeButton={false} render={<a href="#/audits/new" />}>
            检查一个项目 <ArrowRightIcon />
          </Button>
        </ScrollBody>
      </Screen>
    )
  }

  return (
    <Screen>
      <TopBar
        title={<>检查过的项目 <span className="font-mono text-xs font-normal text-muted-foreground">{audits.length}</span></>}
        actions={startButton}
      />
      <ScrollBody>
        <ModeCallouts />
        <div className="overflow-hidden rounded-lg border bg-card">
          <div className="grid grid-cols-[1fr_auto] gap-4 border-b px-4 py-2 font-mono text-xs tracking-wide text-muted-foreground sm:grid-cols-[1fr_12rem_4rem_6rem]">
            <span>项目</span>
            <span className="hidden sm:block">判定</span>
            <span className="hidden text-right sm:block">覆盖率</span>
            <span className="text-right">更新</span>
          </div>
          {audits.map((a) => (
            <a
              key={a.slug}
              href={auditHref(a.slug)}
              className="grid grid-cols-[1fr_auto] items-center gap-4 border-b px-4 py-2.5 text-sm transition-colors last:border-b-0 hover:bg-muted/50 sm:grid-cols-[1fr_12rem_4rem_6rem]"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{a.name}</span>
                <span className="block truncate font-mono text-xs text-muted-foreground" title={a.root}>{a.root}</span>
              </span>
              <span className="hidden sm:block">
                {a.finished ? <Chip tone={verdictTone(a)}>{a.verdict || "已检查"}</Chip> : <Chip>没跑完</Chip>}
              </span>
              <span className="hidden text-right font-mono text-xs sm:block">{pct(a.completion)}</span>
              <span className="text-right text-xs text-muted-foreground">{timeAgo(a.updated)}</span>
            </a>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          检查结果在引擎目录的 out/audit-项目名/ 下；在终端里用 blueprint audit 检查过的项目也会列在这里。
        </p>
      </ScrollBody>
    </Screen>
  )
}

// -- 新建 --------------------------------------------------------------------

const NOTES = [
  ["只读，不改你的代码", "也不会运行它。agent 只能读这个文件夹里的文件。"],
  ["代码会发给你配置的模型服务商", "agent 读到的代码会随请求发出去；.env 和私钥文件不读。"],
  ["大约 3–8 分钟", "最多调用模型 40 次。中途断了可以接着跑，已完成的步骤不重复花钱。"],
]

export function NewAuditPage() {
  const { settings } = useSettings()
  const { reloadAudits } = useShell()
  const [path, setPath] = useState("")
  const [picking, setPicking] = useState(false)
  const [starting, setStarting] = useState(false)

  const pick = async () => {
    setPicking(true)
    try {
      const { path: chosen } = await api.pickFolder()
      if (chosen) setPath(chosen)
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setPicking(false)
    }
  }

  const start = async () => {
    setStarting(true)
    try {
      const { slug } = await api.createAudit(path)
      await reloadAudits()
      location.hash = auditHref(slug)
    } catch (err) {
      toast.error((err as Error).message)
      setStarting(false)
    }
  }

  return (
    <Screen>
      <TopBar title="检查一个项目" />
      <ScrollBody className="max-w-2xl">
        <ModeCallouts />
        <h1 className="text-xl font-semibold tracking-tight">检查一个已有的 Agent 项目</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          选一个项目文件夹，引擎会让 agent 读代码，看它离一个靠谱的 Agent 还差哪些机制，写一份差距报告，再反推一份它本该有的需求文档。
        </p>

        <div className="mt-6 rounded-lg border bg-card p-4">
          <div className="text-sm font-medium">项目文件夹</div>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <Button variant="outline" onClick={pick} disabled={picking || starting} className="shrink-0">
              <FolderSearchIcon /> {picking ? "在弹出的窗口里选…" : "选择文件夹…"}
            </Button>
            <Input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="或者把文件夹路径粘贴到这里"
              className="font-mono text-xs"
              spellCheck={false}
            />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            粘贴路径：在 Finder 里按住 Option 键右键文件夹，选「将…拷贝为路径名称」。
          </p>
        </div>

        <ul className="mt-4 divide-y rounded-lg border bg-card">
          {NOTES.map(([title, desc]) => (
            <li key={title} className="px-4 py-2.5">
              <div className="text-sm">{title}</div>
              <p className="text-xs text-muted-foreground">{desc}</p>
            </li>
          ))}
        </ul>

        <Button className="mt-6" onClick={start} disabled={!path.trim() || starting || !settings.configured}>
          {starting ? "正在开始…" : "开始检查"} <ArrowRightIcon />
        </Button>
      </ScrollBody>
    </Screen>
  )
}

// -- 报告 --------------------------------------------------------------------

export function AuditPage({ slug, tab }: { slug: string; tab: string }) {
  const { reloadAudits } = useShell()
  const [audit, setAudit] = useState<AuditDetail | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      setAudit(await api.audit(slug))
      setError("")
    } catch (err) {
      setError((err as Error).message)
    }
    reloadAudits()
  }, [slug, reloadAudits])

  useEffect(() => {
    setAudit(null)
    load()
  }, [load])

  if (error) {
    return (
      <Screen>
        <TopBar title="检查结果" />
        <div className="mx-auto mt-10 max-w-xl px-4 text-sm text-destructive">{error}</div>
      </Screen>
    )
  }
  if (!audit) return <Screen><TopBar title="检查结果" /></Screen>
  return <AuditView audit={audit} tab={tab} reload={load} />
}

function AuditView({ audit, tab, reload }: { audit: AuditDetail; tab: string; reload: () => Promise<void> }) {
  const { settings } = useSettings()
  const [confirmRejudge, setConfirmRejudge] = useState(false)
  const onFinish = useCallback(
    (job: Job) => {
      if (job.status === "done") toast.success("检查完成，报告已更新")
      reload()
    },
    [reload],
  )
  const job = useJob(audit.job, onFinish)
  const running = job?.status === "running"

  const run = async (mode: AuditMode) => {
    setConfirmRejudge(false)
    try {
      await api.rerunAudit(audit.slug, mode)
      await reload()
    } catch (err) {
      toast.error((err as Error).message)
    }
  }

  const blocked = running || !settings.configured
  const bar = (
    <TopBar
      title={
        <>
          <span className="min-w-0 truncate sm:max-w-[50%] sm:shrink-0">{audit.name}</span>
          <span className="hidden min-w-0 truncate font-mono text-xs font-normal text-muted-foreground sm:inline" title={audit.root}>
            {audit.root}
          </span>
        </>
      }
      actions={
        <>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => api.revealAudit(audit.slug).catch((e: Error) => toast.error(e.message))}
            title={audit.path}
          >
            <FolderOpenIcon /> <span className="hidden sm:inline">打开文件夹</span>
          </Button>
          {audit.finished && (
            <>
              <Button variant="outline" size="sm" disabled={blocked} onClick={() => setConfirmRejudge(true)}>
                <ScaleIcon /> <span className="hidden sm:inline">重新判断</span>
              </Button>
              <Button size="sm" disabled={blocked} onClick={() => run("recheck")} title="代码改过之后再查一次">
                <RefreshCwIcon /> <span className="hidden sm:inline">重新检查</span>
              </Button>
            </>
          )}
        </>
      }
    />
  )

  const progress =
    job && job.status !== "done" ? (
      <div className="mb-6">
        <JobProgress job={job} onResume={() => run("resume")} stages={AUDIT_STAGES} wording={AUDIT_WORDING} />
      </div>
    ) : null
  const active = tab === "prd" ? "prd" : "report"

  return (
    <Screen>
      {bar}
      <ScrollBody className={READING}>
        <ModeCallouts />
        {progress}
        {!audit.finished && !job && (
          <Callout
            title="上次检查没跑完"
            action={<Button onClick={() => run("resume")} disabled={!settings.configured}>继续检查</Button>}
          >
            接着上次中断的地方跑，已完成的步骤不会重复调用模型。
          </Callout>
        )}
        {audit.finished && (
          <>
            {running && <Callout title="下面还是上一次的报告">这次检查完成后会自动刷新。</Callout>}
            <Summary audit={audit} />
            <div className="mt-6 border-b">
              <Tabs value={active} onValueChange={(v) => (location.hash = auditHref(audit.slug, String(v)))}>
                <TabsList variant="line" className="h-10">
                  <TabsTrigger value="report" className="px-2.5">差距报告</TabsTrigger>
                  <TabsTrigger value="prd" className="px-2.5">本该有的需求文档</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <div className="mt-5">
              {active === "report" ? (
                <Markdown text={reportBody(audit.report)} />
              ) : (
                <>
                  <p className="mb-4 text-sm text-muted-foreground">
                    按代码反推出来的需求文档：这个项目如果从头写需求，大概应该写成这样。缺的机制按差距报告补进去了。
                  </p>
                  <Markdown text={audit.suggested_prd} />
                </>
              )}
            </div>
          </>
        )}
      </ScrollBody>

      <Dialog open={confirmRejudge} onOpenChange={setConfirmRejudge}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重新判断这个项目该有什么？</DialogTitle>
            <DialogDescription>
              「重新检查」会沿用上次对「这个项目该有哪些机制」的判断，结果只随代码变化。重新判断会让模型从头再判断一次，
              结果可能和上次有一两处不同。项目本身的定位变了（比如加了新功能）时再用它。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmRejudge(false)}>取消</Button>
            <Button onClick={() => run("rejudge")}>重新判断</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Screen>
  )
}

function Summary({ audit }: { audit: AuditDetail }) {
  const facts = [
    audit.mode === "agent" ? `agent 读了 ${audit.files_seen} 个文件` : "快速扫描（按关键词判断，可能误判）",
    audit.features_from ? `「该有什么」沿用 ${audit.features_from} 那次的判断` : "",
    audit.calls ? `调用模型 ${audit.calls} 次` : "",
    timeAgo(audit.updated),
  ].filter(Boolean)
  return (
    <div className="rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-lg font-semibold tracking-tight">{audit.verdict || "已检查"}</h2>
        <span className="text-sm text-muted-foreground">必选组件信号覆盖率 {pct(audit.completion)}</span>
      </div>
      {audit.title && audit.title !== audit.name && <p className="mt-1 text-sm text-muted-foreground">{audit.title}</p>}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {audit.missing > 0 && <Chip tone="bad">缺 {audit.missing} 项</Chip>}
        {audit.weak > 0 && <Chip tone="warn">弱 {audit.weak} 项</Chip>}
        {!audit.missing && !audit.weak && <Chip tone="ok">该有的都有</Chip>}
      </div>
      {audit.mode !== "agent" && audit.mode_note && (
        <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">没用上 agent：{audit.mode_note}</p>
      )}
      <p className="mt-3 text-xs text-muted-foreground">{facts.join(" · ")}</p>
    </div>
  )
}
