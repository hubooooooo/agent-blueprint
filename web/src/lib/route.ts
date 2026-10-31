import { useEffect, useState } from "react"

export type Route =
  | { page: "home" }
  | { page: "new" }
  | { page: "settings" }
  | { page: "product"; slug: string; tab: string }
  | { page: "audits" }
  | { page: "audit-new" }
  | { page: "audit"; slug: string; tab: string }

/** 用 hash 路由：服务端只需要托管一个 index.html。 */
export function parseRoute(hash: string): Route {
  if (hash === "#/new") return { page: "new" }
  if (hash === "#/settings") return { page: "settings" }
  if (hash === "#/audits") return { page: "audits" }
  if (hash === "#/audits/new") return { page: "audit-new" }
  const a = hash.match(/^#\/a\/([^?]+)(?:\?tab=(\w+))?$/)
  if (a) return { page: "audit", slug: decodeURIComponent(a[1]), tab: a[2] ?? "report" }
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

export function auditHref(slug: string, tab = "report") {
  return `#/a/${encodeURIComponent(slug)}${tab === "report" ? "" : `?tab=${tab}`}`
}

export function productHref(slug: string, tab = "overview") {
  return `#/p/${encodeURIComponent(slug)}${tab === "overview" ? "" : `?tab=${tab}`}`
}
