import { PlusIcon, SettingsIcon, XIcon } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { SettingsContext, ShellContext } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { api, type ProductSummary, type Settings } from "@/lib/api"
import { productHref, useRoute, type Route } from "@/lib/route"
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

const itemClass = (active: boolean) =>
  cn(
    "flex h-8 items-center gap-2 rounded-md px-2 text-sm text-sidebar-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
    active && "bg-sidebar-accent font-medium text-sidebar-foreground",
  )

function Sidebar({
  route,
  settings,
  products,
  onNavigate,
}: {
  route: Route
  settings: Settings | null
  products: ProductSummary[] | null
  onNavigate: () => void
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center gap-2 px-4">
        <a href="#/" onClick={onNavigate} className="flex items-center gap-2 text-sm font-semibold tracking-tight">
          <span className="grid size-6 place-items-center rounded-md bg-foreground font-mono text-xs text-background">ab</span>
          Agent Blueprint
        </a>
        <Button variant="ghost" size="icon-sm" className="ms-auto md:hidden" onClick={onNavigate} aria-label="关闭菜单">
          <XIcon />
        </Button>
      </div>

      <div className="px-2 pt-1">
        <a href="#/new" onClick={onNavigate} className={itemClass(route.page === "new")}>
          <PlusIcon className="size-4" /> 新建产品
        </a>
      </div>

      <nav className="mt-4 min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        <a
          href="#/"
          onClick={onNavigate}
          className={cn(
            "mb-1 block px-2 font-mono text-xs tracking-wider text-muted-foreground hover:text-foreground",
            route.page === "home" && "text-foreground",
          )}
        >
          我的产品
        </a>
        {products?.length === 0 && <p className="px-2 py-1 text-xs text-muted-foreground">还没有产品</p>}
        {products?.map((p) => (
          <a
            key={p.slug}
            href={productHref(p.slug)}
            onClick={onNavigate}
            className={itemClass(route.page === "product" && route.slug === p.slug)}
            title={p.name}
          >
            <span className="min-w-0 flex-1 truncate">{p.name}</span>
            {p.has_plan && p.unknowns > 0 && (
              <span className="font-mono text-xs font-normal text-ask" title={`${p.unknowns} 个待确认问题`}>{p.unknowns}</span>
            )}
          </a>
        ))}
      </nav>

      <div className="border-t px-2 py-2">
        <a href="#/settings" onClick={onNavigate} className={cn(itemClass(route.page === "settings"), "h-auto py-1.5")}>
          <SettingsIcon className="size-4 shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="block">模型设置</span>
            {settings && (
              <span className="block truncate font-mono text-xs font-normal text-muted-foreground">
                {settings.mock ? "离线演示" : settings.configured ? settings.model || "已配置模型" : "未配置模型"}
              </span>
            )}
          </span>
        </a>
      </div>
    </div>
  )
}

export default function App() {
  useSystemDarkMode()
  const route = useRoute()
  const [settings, setSettings] = useState<Settings | null>(null)
  const [products, setProducts] = useState<ProductSummary[] | null>(null)
  const [error, setError] = useState("")
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const reload = useCallback(async () => {
    try {
      setSettings(await api.settings())
      setError("")
    } catch (err) {
      setError((err as Error).message)
    }
  }, [])

  const reloadProducts = useCallback(async () => {
    try {
      setProducts((await api.products()).products)
    } catch {
      /* 侧边栏读不到列表不影响当前页面；下次切换页面再试 */
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  // 新建产品、升版本后都会换页面，换页时顺手刷新侧边栏
  const routeKey = route.page === "product" ? `product:${route.slug}` : route.page
  useEffect(() => {
    reloadProducts()
  }, [reloadProducts, routeKey])

  const closeSidebar = () => setSidebarOpen(false)

  return (
    <TooltipProvider>
      <ShellContext.Provider value={{ products, reloadProducts, openSidebar: () => setSidebarOpen(true) }}>
        <div className="flex h-svh overflow-hidden">
          <aside
            className={cn(
              "fixed inset-y-0 start-0 z-40 w-64 border-e bg-sidebar transition-transform md:static md:w-60 md:translate-x-0",
              sidebarOpen ? "translate-x-0" : "-translate-x-full",
            )}
          >
            <Sidebar route={route} settings={settings} products={products} onNavigate={closeSidebar} />
          </aside>
          {sidebarOpen && <div className="fixed inset-0 z-30 bg-foreground/20 md:hidden" onClick={closeSidebar} />}

          <main className="flex min-w-0 flex-1 flex-col">
            {error && <div className="mx-auto mt-10 max-w-xl px-4 text-center text-sm text-destructive">{error}</div>}
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
      </ShellContext.Provider>
      <Toaster position="bottom-center" />
    </TooltipProvider>
  )
}
