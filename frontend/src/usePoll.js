import { useEffect, useRef } from "react";

// Calls fetcher(id, signal) every `interval` ms until isDone(data) is true or `id` changes / the page unmounts.
// Timers and the in-flight request are cleaned up. A network error is reported and polling continues.
export function usePoll(id, { fetcher, isDone, onData, onError, interval = 1500 }) {
  const latest = useRef({});
  latest.current = { fetcher, isDone, onData, onError };

  useEffect(() => {
    if (!id) return undefined;
    let stopped = false;
    let timer = null;
    const controller = new AbortController();

    const tick = async () => {
      try {
        const data = await latest.current.fetcher(id, controller.signal);
        if (stopped) return;
        latest.current.onData(data);
        if (latest.current.isDone(data)) return;
      } catch (e) {
        if (e.name === "AbortError" || stopped) return;
        latest.current.onError?.(e);
      }
      timer = setTimeout(tick, interval);
    };
    tick();

    return () => {
      stopped = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [id, interval]);
}
