const TOKEN_KEY = "glucotwin.clinic.token";
let csrfToken = "";
export const setCsrf = (value?: string) => {
  csrfToken = value || "";
};
export const getToken = () => sessionStorage.getItem(TOKEN_KEY);
export const setToken = (token: string | null) =>
  token
    ? sessionStorage.setItem(TOKEN_KEY, token)
    : sessionStorage.removeItem(TOKEN_KEY);
export async function api<T>(
  path: string,
  signal?: AbortSignal,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const response = await fetch(`/api${path}`, {
    credentials: "include",
    ...options,
    signal,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.method && options.method !== "GET" && csrfToken
        ? { "X-CSRF-Token": csrfToken }
        : {}),
      ...options.headers,
    },
  });
  const payload = await response.json().catch(() => null);
  if (response.status === 401 && !path.endsWith("/auth/login") && !path.endsWith("/auth/me"))
    window.dispatchEvent(new Event("glucotwin:session-expired"));
  if (!response.ok || !payload?.success)
    throw new Error(
      payload?.error ||
        `API request failed (${response.status}). Check that the GlucoTwin backend is running.`,
    );
  return payload.data as T;
}
export const post = <T>(path: string, body: unknown, method = "POST") =>
  api<T>(path, undefined, { method, body: JSON.stringify(body) });
export async function download(path: string, filename: string) {
  const response = await fetch(`/api${path}`, {
    credentials: "include",
    headers: {
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.error || `Download failed (${response.status}).`);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
