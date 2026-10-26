import { Thread } from "@/components/assistant-ui/elements/thread.aui"
import { ChatProvider } from "@/components/chat/chat-runtime"
import { useChatControls } from "@/components/chat/chat-storage"
import { RestartButton } from "@/components/chat/restart-button"
import { intakeToolkit } from "@/components/chat/tool-cards"
import { Eyebrow, ModeCallouts, useSettings } from "@/components/common"
import { Button } from "@/components/ui/button"
import { chatEndpoints } from "@/lib/api"

const STARTERS = [
  "家长拍一张玩具合影，AI 生成可以亲子一起演的剧情脚本",
  "每天早上整理我的邮箱，挑出要回复的，帮我起草回复",
  "帮小店老板回答顾客在微信上问的常见问题",
]

function Welcome() {
  return (
    <div className="mb-8 px-2">
      <Eyebrow>新建产品</Eyebrow>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">你想做一个什么样的 Agent？</h1>
      <p className="mt-3 text-muted-foreground">
        一句话就行。我会再问你三轮：给谁用、怎么用、什么不能做，然后整理成需求，交给引擎推导方案。说不清的地方直接说不知道。
      </p>
    </div>
  )
}

// 产品建好后对话就结束了；再往下聊不会改到已建的产品，所以把输入框换成「再建一个」
function Finished() {
  const { restart } = useChatControls()
  return (
    <div className="flex flex-wrap items-center justify-center gap-3 py-2 text-sm text-muted-foreground">
      这个产品已经开始推导。
      <Button variant="outline" size="sm" onClick={restart}>
        再新建一个产品
      </Button>
    </div>
  )
}

export function NewProductPage() {
  const { settings } = useSettings()
  if (!settings.configured) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
        <ModeCallouts />
      </div>
    )
  }
  return (
    <div className="flex h-[calc(100svh-3.5rem)] flex-col">
      {settings.mock && (
        <div className="mx-auto w-full max-w-[44rem] px-4 pt-4">
          <ModeCallouts />
        </div>
      )}
      <ChatProvider endpoint={chatEndpoints.intake} toolkit={intakeToolkit} starters={STARTERS} storageKey="intake">
        <div className="mx-auto flex w-full max-w-[44rem] justify-end px-4 pt-2">
          <RestartButton label="重新开始新产品" />
        </div>
        <div className="min-h-0 flex-1">
          <Thread components={{ Welcome, Finished }} placeholder="说说你的想法…" />
        </div>
      </ChatProvider>
    </div>
  )
}
