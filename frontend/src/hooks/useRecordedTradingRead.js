import { useEffect, useState } from 'react';

/** A read is published only for the exact rendered identity/query. No polling. */
export default function useRecordedTradingRead(requestKey, load) {
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState({ key: requestKey, value: null, loading: true, error: false });
  useEffect(() => {
    let closed = false;
    const controller = new AbortController();
    setState({ key: requestKey, value: null, loading: true, error: false });
    Promise.resolve().then(() => load(controller.signal)).then((value) => {
      if (!closed && !controller.signal.aborted) setState({ key: requestKey, value, loading: false, error: false });
    }).catch(() => {
      if (!closed && !controller.signal.aborted) setState({ key: requestKey, value: null, loading: false, error: true });
    });
    return () => { closed = true; controller.abort(); };
  }, [requestKey, load, retry]);
  // Effects run after render: never publish a previous query while cleanup starts.
  const current = state.key === requestKey ? state : { value: null, loading: true, error: false };
  return { ...current, retry: () => setRetry((value) => value + 1) };
}
