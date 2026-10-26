import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import App from "./App.tsx"
import "./index.css"

// 旧浏览器的提示由 index.html 直接写好，这里不再挂载界面
if (!(window as { __blueprintUnsupported?: boolean }).__blueprintUnsupported) createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
