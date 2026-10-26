import {
  AssistantRuntimeProvider,
  AuiConfig,
  Suggestions,
  Tools,
  useLocalRuntime,
  type ChatModelAdapter,
  type DataMessagePart,
  type SuggestionAdapter,
  type TextMessagePart,
  type ThreadMessage,
  type ThreadMessageLike,
  type Toolkit,
  type ToolCallMessagePart,
} from "@assistant-ui/react"
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"

import {
  ChatControlsContext,
  clearChat,
  FallbackChipsContext,
  loadChat,
  saveChat,
} from "@/components/chat/chat-storage"
import { streamChat } from "@/lib/api"

/**
 * 只把文字发给服务端；卡片（tool-call）是网页自己的事，服务端不需要。
 * 带 wire 字段的数据卡片（试玩里模拟的动作）按原顺序换成文字一起发回，下一轮模型才知道之前发生了什么。
 */
function toWire(messages: readonly ThreadMessage[]) {
  return messages.map((m) => ({
    role: m.role,
    text: m.content
      .flatMap((p) => {
        if (p.type === "text") return [p.text]
        if (p.type === "data" && typeof p.data?.wire === "string") return [p.data.wire]
        return []
      })
      .join("\n"),
  }))
}

type ChatProviderProps = {
  endpoint: string
  toolkit: Toolkit
  /** 本地保存这段对话用的键；不给就不保存。 */
  storageKey?: string
  initialMessages?: ThreadMessageLike[]
  /** 开场就显示的快捷按钮（开场白由网页直接放入，还没经过一次回复时用）。 */
  initialChips?: string[]
  starters?: string[]
  children: ReactNode
}

/**
 * 把一段对话接到服务端的 NDJSON 接口上（blueprint/chat.py）。
 *
 * - 文字逐段显示；服务端发来的快捷按钮在回复结束后出现在输入框上方。
 * - 服务端要求确认（tool 事件）时弹出卡片并暂停对话；用户在卡片上点了确认，对话就结束，不再请求服务端。
 * - 给了 storageKey 就存在浏览器本地，切走再回来、刷新页面都能接着聊；「重新开始」清空重来。
 */
export function ChatProvider(props: ChatProviderProps) {
  const [generation, setGeneration] = useState(0)
  const controls = useMemo(
    () => ({
      restart: () => {
        if (props.storageKey) clearChat(props.storageKey)
        setGeneration((g) => g + 1)
      },
    }),
    [props.storageKey],
  )
  return (
    <ChatControlsContext.Provider value={controls}>
      <ChatSession key={generation} {...props} />
    </ChatControlsContext.Provider>
  )
}

function ChatSession({ endpoint, toolkit, storageKey, initialMessages, initialChips, starters, children }: ChatProviderProps) {
  const [saved] = useState(() => (storageKey ? loadChat(storageKey) : null))
  const followUps = useRef<string[]>(saved?.chips ?? [])
  // 恢复的对话或开场白还没经过一次回复，运行时里没有建议，先用这组；一开始新的回复就清掉
  const [fallbackChips, setFallbackChips] = useState<readonly string[]>(saved ? saved.chips : (initialChips ?? []))

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_getMessage }) {
        const answered = unstable_getMessage().content.some(
          (p) => p.type === "tool-call" && p.result !== undefined,
        )
        if (answered) return

        setFallbackChips([])
        followUps.current = []
        // 文字、卡片按服务端发来的顺序排；连续的文字并成一段
        const parts: (ToolCallMessagePart | DataMessagePart | TextMessagePart)[] = []
        let tools = 0
        const content = () => parts.map((p) => ({ ...p }))

        for await (const event of streamChat(endpoint, toWire(messages), abortSignal)) {
          if (event.type === "text") {
            const last = parts.at(-1)
            if (last?.type === "text") parts[parts.length - 1] = { ...last, text: last.text + event.delta }
            else parts.push({ type: "text", text: event.delta })
            yield { content: content() }
          } else if (event.type === "tool") {
            tools += 1
            parts.push({
              type: "tool-call",
              toolCallId: `${event.name}-${tools}-${Date.now()}`,
              toolName: event.name,
              args: event.args as ToolCallMessagePart["args"],
              argsText: JSON.stringify(event.args),
            })
            yield { content: content() }
          } else if (event.type === "data") {
            parts.push({ type: "data", name: event.name, data: event.data })
            yield { content: content() }
          } else if (event.type === "suggestions") {
            followUps.current = event.items
          } else if (event.type === "error") {
            throw new Error(event.message)
          }
        }
        if (tools) {
          yield { content: content(), status: { type: "requires-action", reason: "tool-calls" } }
        }
      },
    }),
    [endpoint],
  )

  const suggestion = useMemo<SuggestionAdapter>(
    () => ({ generate: async () => followUps.current.map((prompt) => ({ prompt })) }),
    [],
  )

  const runtime = useLocalRuntime(adapter, {
    initialMessages,
    adapters: { suggestion },
    unstable_humanToolNames: Object.keys(toolkit),
  })

  useEffect(() => {
    if (!storageKey) return
    if (saved) runtime.thread.import(saved.thread)
    return runtime.thread.subscribe(() => {
      const state = runtime.thread.getState()
      if (state.isRunning) return
      const done = state.messages.some((m) =>
        m.content.some((p) => p.type === "tool-call" && p.result !== undefined),
      )
      if (done) clearChat(storageKey)
      else if (state.messages.some((m) => m.role === "user")) {
        saveChat(storageKey, { thread: runtime.thread.export(), chips: followUps.current })
      }
    })
  }, [runtime, storageKey, saved])

  const config = useMemo(
    () =>
      AuiConfig({
        tools: Tools({ toolkit }),
        ...(starters ? { suggestions: Suggestions(starters) } : {}),
      }),
    [toolkit, starters],
  )

  return (
    <AssistantRuntimeProvider runtime={runtime} config={config}>
      <FallbackChipsContext.Provider value={fallbackChips}>{children}</FallbackChipsContext.Provider>
    </AssistantRuntimeProvider>
  )
}
