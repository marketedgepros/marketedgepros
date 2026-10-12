import { useEffect, useRef, useState } from "react";
import {
  catalogErrorMessage,
  loadCatalog,
  routeCatalogId,
} from "../services/programCatalogViewService.js";
import useAuthStore from "../store/authStore";

export default function useProgramCatalog(routeId = null) {
  const scope = useAuthStore((state) =>
    JSON.stringify([
      state.isAuthenticated,
      state.user?.id ?? null,
      state.user?.tenant_id ?? null,
    ]),
  );
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({
    key: undefined,
    loading: true,
    data: null,
    error: "",
  });
  const request = useRef(0);
  const key = `${scope}:${routeId === null ? "list" : `program:${routeId}`}`;
  const currentKey = useRef(key);
  currentKey.current = key;
  useEffect(() => {
    const controller = new AbortController();
    const requestId = ++request.current;
    setResult({ key, loading: true, data: null, error: "" });
    (async () => {
      try {
        const programId = routeId === null ? null : routeCatalogId(routeId);
        const data = await loadCatalog({
          programId,
          signal: controller.signal,
        });
        if (
          !controller.signal.aborted &&
          request.current === requestId &&
          currentKey.current === key
        )
          setResult({ key, loading: false, data, error: "" });
      } catch (error) {
        if (
          !controller.signal.aborted &&
          request.current === requestId &&
          currentKey.current === key
        )
          setResult({
            key,
            loading: false,
            data: null,
            error: catalogErrorMessage(error),
          });
      }
    })();
    return () => controller.abort();
  }, [key, attempt, routeId]);
  const current =
    result.key === key ? result : { loading: true, data: null, error: "" };
  return { ...current, retry: () => setAttempt((value) => value + 1) };
}
