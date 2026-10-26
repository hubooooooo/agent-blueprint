import { useEffect, useState } from "react"

export type Route =
  | { page: "home" }
  | { page: "new" }
  | { page: "settings" }
  | { page: "product"; slug: string; tab: string }

/** 用 hash 路由：服务端只需要托管一个 index.html。 */
export function parseRoute(hash: string): Route {
  if (hash === "#/new") return { page: "new" }
  if (hash === "#/settings") return { page: "settings" }
  const m = hash.match(/^#\/p\/([^?]+)(?:\?tab=(\w+))?$/)
  if (m) return { page: "product", slug: decodeURIComponent(m[1]), tab: m[2] ?? "overview" }
  return { page: "home" }
}

export function useRoute() {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const onChange = () => setHash(location.hash)
    addEventListener("hashchange", onChange)
    return () => removeEventListener("hashchange", onChange)
  }, [])
  return parseRoute(hash)
}

export function productHref(slug: string, tab = "overview") {
  return `#/p/${encodeURIComponent(slug)}${tab === "overview" ? "" : `?tab=${tab}`}`
}
