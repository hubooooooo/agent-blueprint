import type { ReactNode } from "react"

import { Thread } from "@/components/assistant-ui/elements/thread.aui"
import { RestartButton } from "@/components/chat/restart-button"

/** 产品页里的对话：顶上一条说明和「重新开始」，对话铺满剩下的高度。要放在 ChatProvider 里面。 */
export function ChatPane({ hint, top, placeholder }: { hint: ReactNode; top?: ReactNode; placeholder: string }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-10 shrink-0 items-center justify-between gap-3 border-b px-4 py-1.5 text-xs text-muted-foreground">
        <span className="min-w-0">{hint}</span>
        <RestartButton />
      </div>
      {top}
      <div className="min-h-0 flex-1">
        <Thread autoFocus={false} placeholder={placeholder} />
      </div>
    </div>
  )
}
