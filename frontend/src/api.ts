export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const timeout = AbortSignal.timeout(25000);
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(
      "网络连接中断或请求超时。请查看最新状态；已提交的操作不会自动重试。",
      0,
    );
  }
  const result = (await response.json().catch(() => null)) as {
    detail?: unknown;
  } | null;
  if (!response.ok) {
    const detail =
      typeof result?.detail === "string"
        ? result.detail
        : `请求失败（${response.status}），请检查输入或重新登录。`;
    throw new ApiError(detail, response.status);
  }
  return result as T;
}

export function errorText(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "操作未完成，请重新检查当前状态。";
}

export function evidenceUrl(game: string, id: string): string {
  return `/api/games/${encodeURIComponent(game)}/evidence/${encodeURIComponent(id)}`;
}
