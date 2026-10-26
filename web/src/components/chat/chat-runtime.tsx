import {
  AssistantRuntimeProvider,
  AuiConfig,
  Suggestions,
  Tools,
  useLocalRuntime,
  type ChatModelAdapter,
  type SuggestionAdapter,
  type ThreadMessage,
  type ThreadMessageLike,
  type Toolkit,
  type ToolCallMessagePart,
} from "@assistant-ui/react"
import { useMemo, useRef, type ReactNode } from "react"

import { streamChat } from "@/lib/api"

/** 只把文字发给服务端；卡片（tool-call）是网页自己的事，服务端不需要。 */
function toWire(messages: readonly ThreadMessage[]) {
  return messages.map((m) => ({
    role: m.role,
    text: m.content.flatMap((p) => (p.type === "text" ? [p.text] : [])).join("\n"),
  }))
}

/**
 * 把一段对话接到服务端的 NDJSON 接口上（blueprint/chat.py）。
 *
 * - 文字逐段显示；服务端发来的快捷按钮在回复结束后出现在输入框上方。
 * - 服务端要求确认（tool 事件）时弹出卡片并暂停对话；用户在卡片上点了确认，对话就结束，不再请求服务端。
 */
export function ChatProvider({
  endpoint,
  toolkit,
  initialMessages,
  starters,
  children,
}: {
  endpoint: string
  toolkit: Toolkit
  initialMessages?: ThreadMessageLike[]
  starters?: string[]
  children: ReactNode
}) {
  const followUps = useRef<string[]>([])

  const adapter = useMemo<ChatModelAdapter>(
    () => ({
      async *run({ messages, abortSignal, unstable_getMessage }) {
        const answered = unstable_getMessage().content.some(
          (p) => p.type === "tool-call" && p.result !== undefined,
        )
        if (answered) return

        followUps.current = []
        let text = ""
        const tools: ToolCallMessagePart[] = []
        const content = () => [...(text ? [{ type: "text" as const, text }] : []), ...tools]

        for await (const event of streamChat(endpoint, toWire(messages), abortSignal)) {
          if (event.type === "text") {
            text += event.delta
            yield { content: content() }
          } else if (event.type === "tool") {
            tools.push({
              type: "tool-call",
              toolCallId: `${event.name}-${tools.length}-${Date.now()}`,
              toolName: event.name,
              args: event.args as ToolCallMessagePart["args"],
              argsText: JSON.stringify(event.args),
            })
            yield { content: content() }
          } else if (event.type === "suggestions") {
            followUps.current = event.items
          } else if (event.type === "error") {
            throw new Error(event.message)
          }
        }
        if (tools.length) {
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
      {children}
    </AssistantRuntimeProvider>
  )
}
