// 与 blueprint/web/server.py、blueprint/web/views.py 的返回结构一一对应。

export type Provider = { key: string; name: string; model: string; key_page: string }

export type Settings = {
  mock: boolean
  configured: boolean
  provider: string
  model: string
  key_masked: string
  providers: Provider[]
}

export type ProductSummary = {
  slug: string
  name: string
  version: number
  has_plan: boolean
  unknowns: number
  review_ok: boolean
  pending_versions: string[]
  updated: number
}

export type Job = {
  id: string
  kind: string
  slug: string
  status: "running" | "done" | "failed"
  logs: string[]
  log_count: number
  error: string
  started: number
  finished: number | null
}

export type Decision = "必选" | "二期" | "待确认" | "放弃"

export type Component = {
  id: string
  name: string
  decision: Decision
  reason: string
  feature: string
  domain: string
  one_liner: string
  when: string
}

export type Tool = {
  name: string
  input: string
  output: string
  side_effect: string
  permission: "allow" | "ask" | "deny"
  layer: string
}

export type Plan = {
  title: string
  one_liner: string
  runner: string
  unknowns: string[]
  facts: { key: string; label: string; value: string; status: string }[]
  elements: { key: string; label: string; items: string[] }[]
  components: Component[]
  layers: { num: string; name: string; question: string; detail: string }[]
  tool_list: Tool[]
  system_prompt: string
  context_memory_strategy: string
  security_and_degradation: string[]
  observability: { logs?: string[]; metrics?: string[]; trajectory?: string }
  tech_stack_and_deployment: string
  review: {
    ok?: boolean
    score?: number
    summary?: string
    issues?: { section?: string; problem?: string; severity?: "high" | "medium" | "low" }[]
  }
  design_attempts: number
  budget: { calls?: number; input_tokens?: number; output_tokens?: number }
}

export type ProductDetail = ProductSummary & {
  path: string
  plan: Plan | null
  job: Job | null
  answer_intro: string
}

export class ApiError extends Error {}

async function request<T>(path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  } catch {
    throw new ApiError("连不上引擎。启动界面的那个终端窗口是不是被关掉了？重新双击启动文件即可。")
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(data.error || `请求失败（${res.status}）`)
  return data as T
}

const enc = encodeURIComponent

export const api = {
  settings: () => request<Settings>("/api/settings"),
  saveSettings: (body: { provider: string; api_key: string; model: string }) =>
    request<{ ok: boolean; message: string }>("/api/settings", body),
  products: () => request<{ products: ProductSummary[] }>("/api/products"),
  product: (slug: string) => request<ProductDetail>(`/api/products/${enc(slug)}`),
  createProduct: (name: string, idea: string) =>
    request<{ slug: string; job: Job }>("/api/products", { name, idea }),
  startPlan: (slug: string) => request<{ job: Job }>(`/api/products/${enc(slug)}/plan`, {}),
  saveAnswers: (slug: string, answers: { question: string; answer: string }[]) =>
    request<{ job: Job }>(`/api/products/${enc(slug)}/answers`, { answers }),
  reveal: (slug: string) => request<{ ok: boolean }>(`/api/products/${enc(slug)}/reveal`, {}),
  job: (id: string) => request<Job>(`/api/jobs/${enc(id)}`),
}

export const chatEndpoints = {
  intake: "/api/chat/intake",
  answers: (slug: string) => `/api/products/${enc(slug)}/chat`,
}

export type ChatEvent =
  | { type: "text"; delta: string }
  | { type: "tool"; name: string; args: Record<string, unknown> }
  | { type: "suggestions"; items: string[] }
  | { type: "error"; message: string }
  | { type: "done" }

/** 读服务端逐行推送的 JSON 事件（NDJSON）。 */
export async function* streamChat(
  endpoint: string,
  messages: { role: string; text: string }[],
  signal: AbortSignal,
): AsyncGenerator<ChatEvent> {
  let res: Response
  try {
    res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
      signal,
    })
  } catch (err) {
    if (signal.aborted) throw err
    throw new ApiError("连不上引擎。启动界面的那个终端窗口是不是被关掉了？")
  }
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}))
    throw new ApiError(data.error || `请求失败（${res.status}）`)
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let nl: number
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (line) yield JSON.parse(line) as ChatEvent
    }
  }
}
