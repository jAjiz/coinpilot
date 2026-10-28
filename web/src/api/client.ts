import createClient from "openapi-fetch";
import type { paths } from "./schema";

const REFRESH_PATH = "/api/auth/refresh";

let refreshInFlight: Promise<boolean> | null = null;
const sessionEndedListeners = new Set<() => void>();

export function onSessionEnded(listener: () => void): () => void {
  sessionEndedListeners.add(listener);
  return () => {
    sessionEndedListeners.delete(listener);
  };
}

async function refresh(): Promise<boolean> {
  try {
    const response = await fetch(
      new URL(REFRESH_PATH, window.location.origin),
      { method: "POST", credentials: "same-origin" },
    );
    return response.ok;
  } catch {
    return false;
  }
}

const REFRESH_LOCK = "coinpilot-refresh";

// Other tabs share the cookie, so a Web Lock keeps their refreshes apart too: a
// tab that waited sends the token the first one rotated in, not the spent one.
function lockedRefresh(): Promise<boolean> {
  if (typeof navigator === "undefined" || !navigator.locks) return refresh();
  return navigator.locks.request(REFRESH_LOCK, refresh);
}

// Two refreshes with the same token end the sign-in, so exactly one may be in
// flight: the first request that needs it creates it, the rest await it.
function sharedRefresh(): Promise<boolean> {
  refreshInFlight ??= lockedRefresh()
    .then((ok) => {
      if (!ok) sessionEndedListeners.forEach((listener) => listener());
      return ok;
    })
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

export async function fetchWithRefresh(request: Request): Promise<Response> {
  const retry = request.clone();
  const response = await fetch(request);
  if (
    response.status !== 401 ||
    new URL(request.url).pathname === REFRESH_PATH
  ) {
    return response;
  }
  if (!(await sharedRefresh())) return response;
  return fetch(retry);
}

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: fetchWithRefresh,
});

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly body: unknown;

  constructor(status: number, detail: string, body: unknown) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

function detailOf(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msg = (detail[0] as { msg?: unknown } | undefined)?.msg;
    if (typeof msg === "string") return msg;
  }
  return fallback;
}

// The platform's 503s for Kraken all begin with "kraken" and record nothing
// (spec §7); its other 503, the database being down, keeps its own detail.
function isKrakenDown(error: ApiError): boolean {
  return error.status === 503 && error.detail.startsWith("kraken");
}

export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "The connection failed.";
  if (isKrakenDown(error)) return "Kraken didn't answer; nothing was changed.";
  return error.detail;
}

export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      detailOf(
        error,
        response.statusText || `The platform answered ${response.status}.`,
      ),
      error,
    );
  }
  return data as T;
}

// The detail api/evaluation.py answers with while another evaluation of the
// account runs. Keep it identical to the platform's text.
const BUSY_DETAIL =
  "an evaluation of this account is already running; try again shortly";

export function operationError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409 && error.detail === BUSY_DETAIL) {
      return "An operation is already running; try again in a moment.";
    }
  }
  return describeError(error);
}
