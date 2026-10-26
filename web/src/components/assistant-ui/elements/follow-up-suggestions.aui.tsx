"use client";

import { AuiIf, useAuiState, ThreadPrimitive } from "@assistant-ui/react";
import { useCallback, useContext, useEffect, useRef, useState, type FC } from "react";

import { FallbackChipsContext } from "@/components/chat/chat-storage";

type Item = { prompt: string; title?: string | undefined; label?: string | undefined };

const FollowupSuggestionsRow: FC<{ suggestions: readonly Item[] }> = ({ suggestions }) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const rtlRef = useRef<boolean | null>(null);
  const [fades, setFades] = useState({ left: false, right: false });

  const updateFades = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const maxScroll = el.scrollWidth - el.clientWidth;
    // scrollLeft runs 0..-max in RTL; normalize to hidden width per physical edge.
    const fromStart = Math.abs(el.scrollLeft);
    // getComputedStyle forces a style recalc per scroll event; direction is stable, read it once.
    const rtl = (rtlRef.current ??= getComputedStyle(el).direction === "rtl");
    const [left, right] = rtl
      ? [maxScroll - fromStart, fromStart]
      : [fromStart, maxScroll - fromStart];
    setFades((prev) => {
      const next = { left: left > 1, right: right > 1 };
      return prev.left === next.left && prev.right === next.right ? prev : next;
    });
  }, []);

  useEffect(() => {
    updateFades();
    const el = scrollRef.current;
    if (!el?.firstElementChild) return undefined;
    const observer = new ResizeObserver(updateFades);
    observer.observe(el);
    observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, [updateFades]);

  const maskImage = `linear-gradient(to right, ${
    fades.left ? "transparent, black 2rem" : "black"
  }, ${fades.right ? "black calc(100% - 2rem), transparent" : "black"})`;

  return (
    <div
      ref={scrollRef}
      onScroll={updateFades}
      // overflow-x clips both axes; py-1/-my-1 gives focus rings vertical room without changing outer height.
      className="aui-thread-followup-suggestions -my-1 w-full [scrollbar-width:none] overflow-x-auto py-1 [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden"
      style={{ maskImage, WebkitMaskImage: maskImage }}
    >
      <div className="mx-auto flex min-h-8 w-max items-center gap-2 px-0.5">
        {suggestions.map((suggestion, idx) => (
          <ThreadPrimitive.Suggestion
            key={idx}
            className="aui-thread-followup-suggestion border-foreground/10 hover:bg-foreground/[0.03] hover:border-foreground/25 rounded-md border px-2.5 py-1 text-sm whitespace-nowrap transition-colors ease-in motion-reduce:transition-none"
            prompt={suggestion.prompt}
            send
          >
            {suggestion.title ?? suggestion.prompt}
            {suggestion.label && (
              <span className="aui-thread-followup-suggestion-label text-muted-foreground ms-1">
                {suggestion.label}
              </span>
            )}
          </ThreadPrimitive.Suggestion>
        ))}
      </div>
    </div>
  );
};

/**
 * 回复下方的快捷按钮。运行时里没有建议时（开场白、从本地恢复的对话还没经过一次回复），
 * 用 ChatProvider 给的兜底按钮。
 */
export const ThreadFollowupSuggestions: FC = () => {
  const runtime = useAuiState((s) => s.thread.suggestions);
  const fallback = useContext(FallbackChipsContext);
  const items: readonly Item[] = runtime.length > 0 ? runtime : fallback.map((prompt) => ({ prompt }));
  return (
    <AuiIf condition={(s) => !s.thread.isEmpty && !s.thread.isRunning}>
      {items.length > 0 && <FollowupSuggestionsRow suggestions={items} />}
    </AuiIf>
  );
};
