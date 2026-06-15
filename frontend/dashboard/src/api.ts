import type { PageResult } from "./types";

export async function api<T = unknown>(url: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(options.headers ?? {}),
      },
      ...options,
    });
  } catch (error) {
    throw errorWithCause(networkErrorMessage(error), error);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return null as T;
  }
  return response.json() as Promise<T>;
}

function networkErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || "");
  if (message.toLowerCase().includes("failed to fetch")) {
    return "Dashboard backend is unreachable. Check that the full runtime is running at the current address, then retry.";
  }
  return message || "Dashboard backend is unreachable. Check the runtime and retry.";
}

function errorWithCause(message: string, cause: unknown): Error {
  const error = new Error(message) as Error & { cause?: unknown };
  error.cause = cause;
  return error;
}

export function pageCount(total: number, pageSize: number): number {
  return Math.max(1, Math.ceil(total / pageSize));
}

export function asPageResult<T>(payload: PageResult<T>): PageResult<T> {
  return {
    items: payload.items ?? [],
    total: payload.total ?? 0,
    page: payload.page,
    page_size: payload.page_size,
  };
}
