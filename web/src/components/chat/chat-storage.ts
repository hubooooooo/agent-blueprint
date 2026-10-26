import type { ExportedMessageRepository } from "@assistant-ui/react"
import { createContext, useContext } from "react"

// 对话存在浏览器本地：切换标签、刷新页面都能接着聊。卡片一确认（流程走完）就删掉，不留用完的对话。
// localStorage 在隐私模式等情况下可能不可用，所有读写都包在 try 里，失败就当没存过。

const PREFIX = "ab:chat:"

export type SavedChat = { thread: ExportedMessageRepository; chips: string[] }

function reviveDates(thread: ExportedMessageRepository): ExportedMessageRepository {
  for (const item of thread.messages) {
    const msg = item.message as { createdAt: Date | string }
    if (typeof msg.createdAt === "string") msg.createdAt = new Date(msg.createdAt)
  }
  return thread
}

export function loadChat(key: string): SavedChat | null {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (!raw) return null
    const data = JSON.parse(raw) as SavedChat
    return data.thread?.messages?.length ? { thread: reviveDates(data.thread), chips: data.chips ?? [] } : null
  } catch {
    return null
  }
}

export function saveChat(key: string, data: SavedChat) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(data))
  } catch {
    /* 存不了就算了，只是少了「接着聊」 */
  }
}

export function clearChat(key: string) {
  try {
    localStorage.removeItem(PREFIX + key)
  } catch {
    /* 同上 */
  }
}

/** 同一前缀下除了 keep 以外的记录都删掉（方案换了，旧问题的对话就没用了）。 */
export function clearChatsExcept(prefix: string, keep: string) {
  try {
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith(PREFIX + prefix) && k !== PREFIX + keep) localStorage.removeItem(k)
    }
  } catch {
    /* 同上 */
  }
}

/** 一组字符串的短指纹，用来区分「哪一版方案的问题」。 */
export function fingerprint(items: readonly string[]) {
  let h = 5381
  for (const ch of items.join("\u0000")) h = ((h << 5) + h + ch.charCodeAt(0)) | 0
  return (h >>> 0).toString(36)
}

/** 回复下方快捷按钮的兜底：开场白、或从本地恢复的对话，还没经过一次回复，运行时里没有建议。 */
export const FallbackChipsContext = createContext<readonly string[]>([])

export const ChatControlsContext = createContext<{ restart: () => void } | null>(null)

export function useChatControls() {
  const ctx = useContext(ChatControlsContext)
  if (!ctx) throw new Error("ChatControlsContext missing")
  return ctx
}
