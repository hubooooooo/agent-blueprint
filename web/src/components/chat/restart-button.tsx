import { useAuiState } from "@assistant-ui/react"
import { RotateCcwIcon } from "lucide-react"

import { useChatControls } from "@/components/chat/chat-storage"
import { Button } from "@/components/ui/button"

/** 对话里有用户发过的话、而且没在回复时才显示。 */
export function RestartButton({ label = "重新开始" }: { label?: string }) {
  const { restart } = useChatControls()
  const visible = useAuiState((s) => !s.thread.isRunning && s.thread.messages.some((m) => m.role === "user"))
  if (!visible) return null
  return (
    <Button
      variant="ghost"
      size="sm"
      className="text-muted-foreground"
      onClick={() => {
        if (confirm("清空这段对话，从头开始？")) restart()
      }}
    >
      <RotateCcwIcon /> {label}
    </Button>
  )
}
