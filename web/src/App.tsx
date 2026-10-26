import { useCallback, useEffect, useState } from "react"

import { SettingsContext } from "@/components/common"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { api, type Settings } from "@/lib/api"
import { useRoute } from "@/lib/route"
import { cn } from "@/lib/utils"
import { HomePage } from "@/pages/home"
import { NewProductPage } from "@/pages/new-product"
import { ProductPage } from "@/pages/product"
import { SettingsPage } from "@/pages/settings"

function useSystemDarkMode() {
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)")
    const apply = () => document.documentElement.classList.toggle("dark", media.matches)
    apply()
    media.addEventListener("change", apply)
    return () => media.removeEventListener("change", apply)
  }, [])
}

export default function App() {
  useSystemDarkMode()
  const route = useRoute()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [error, setError] = useState("")

  const reload = useCallback(async () => {
    try {
      setSettings(await api.settings())
      setError("")
    } catch (err) {
      setError((err as Error).message)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const nav = route.page === "settings" ? "settings" : route.page === "new" ? "new" : "home"

  return (
    <TooltipProvider>
      <div className="flex min-h-svh flex-col">
        <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4 sm:px-6">
            <a href="#/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span className="grid size-6 place-items-center rounded-md bg-foreground font-mono text-xs text-background">ab</span>
              <span className="hidden sm:inline">Agent Blueprint</span>
            </a>
            <nav className="flex gap-1 text-sm">
              {[
                ["home", "#/", "我的产品"],
                ["new", "#/new", "新建产品"],
                ["settings", "#/settings", "模型设置"],
              ].map(([key, href, label]) => (
                <a
                  key={key}
                  href={href}
                  className={cn(
                    "rounded-md px-2.5 py-1.5 text-muted-foreground transition-colors hover:text-foreground",
                    nav === key && "bg-muted text-foreground",
                  )}
                >
                  {label}
                </a>
              ))}
            </nav>
            {settings && (
              <span className="ms-auto hidden font-mono text-xs text-muted-foreground md:inline">
                {settings.mock ? "离线演示" : settings.configured ? settings.model || "已配置模型" : "未配置模型"}
              </span>
            )}
          </div>
        </header>

        <main className="flex flex-1 flex-col">
          {error && (
            <div className="mx-auto mt-10 max-w-xl px-4 text-center text-sm text-destructive">{error}</div>
          )}
          {settings && (
            <SettingsContext.Provider value={{ settings, reload }}>
              {route.page === "home" && <HomePage />}
              {route.page === "new" && <NewProductPage />}
              {route.page === "settings" && <SettingsPage />}
              {route.page === "product" && <ProductPage slug={route.slug} tab={route.tab} />}
            </SettingsContext.Provider>
          )}
        </main>
      </div>
      <Toaster position="bottom-center" />
    </TooltipProvider>
  )
}
