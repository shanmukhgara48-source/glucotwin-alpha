export async function api<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${path}`, { signal });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.success) throw new Error(payload?.error || `API request failed (${response.status}). Check that the GlucoTwin backend is running.`);
  return payload.data as T;
}
