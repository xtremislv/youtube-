import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Small, dependency-free replacement for the "fetch on mount, stash the
 * result in state, ignore the error" shape that used to be hand-rolled
 * separately in App() (fetchChannels/fetchCohorts/fetchSystemStatus/
 * fetchScraperSettings all did `fn().then(setX).catch(() => {})`) and again
 * in TopicSearchView's initial load. Consolidating them here means there's
 * one implementation of "don't apply a response that arrived after this
 * effect re-ran or the component unmounted" instead of each call site
 * getting it right (or not) independently — see ChannelStatCard's own
 * hand-written `cancelled` flag for the pattern this generalizes.
 *
 * Deliberately minimal: no caching, no retry/backoff, no dedup across
 * hook instances. It exists to remove duplication between call sites that
 * were already this simple, not to become a general-purpose data layer.
 *
 * `error` is captured (as a string, matching how every existing call site
 * already turned a caught error into a message) but nothing currently
 * reads it for the call sites this replaces — those all silently ignored
 * fetch failures before, and still do; the field is there for a call site
 * that wants it, not a behavior change for the ones that don't.
 */
export function useAsync<T>(fetchFn: () => Promise<T>, deps: React.DependencyList, initialValue: T) {
  const [data, setData] = useState<T>(initialValue);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  // Keeps the effect below from needing `fetchFn` itself in its dependency
  // array — callers pass a fresh function reference on every render (e.g.
  // `() => fetchLatestTopicSearch()`), and depending on that directly would
  // refetch every render regardless of `deps`.
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFnRef
      .current()
      .then(result => {
        if (cancelled) return;
        setData(result);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Something went wrong — please try again.");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadTick]);

  const reload = useCallback(() => setReloadTick(t => t + 1), []);

  return { data, setData, loading, error, reload } as const;
}
