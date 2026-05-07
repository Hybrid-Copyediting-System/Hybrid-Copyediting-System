import axios from "axios";
import type { CheckReport, ProgressEvent } from "./types";

/**
 * Error type for HTTP/SSE failures originating in this module.
 *
 * Carries a user-facing detail string. extractErrorMessage handles both
 * APIError instances (the SSE path) and axios errors (the JSON path),
 * so callers don't need to branch on which transport was used.
 */
export class APIError extends Error {
  constructor(public detail: string) {
    super(detail);
    this.name = "APIError";
  }
}

export function extractErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof APIError) {
    return err.detail || fallback;
  }
  if (
    typeof err === "object" &&
    err !== null &&
    "response" in err &&
    typeof (err as Record<string, unknown>).response === "object"
  ) {
    const resp = (err as { response: { data?: { detail?: string } } }).response;
    return resp.data?.detail || fallback;
  }
  return fallback;
}

/**
 * POST the file to /api/check/stream, parse the SSE response, and call onProgress
 * for each progress event. Resolves with the final CheckReport on "complete".
 *
 * Uses fetch + manual SSE parsing because EventSource only supports GET.
 */
export async function checkDocumentStreaming(
  file: File,
  onProgress: (event: ProgressEvent) => void,
): Promise<CheckReport> {
  const fd = new FormData();
  fd.append("file", file);

  const response = await fetch("/api/check/stream", {
    method: "POST",
    body: fd,
  });

  if (!response.ok || !response.body) {
    let detail = "Server error";
    try {
      const data = (await response.json()) as { detail?: string };
      detail = data.detail ?? detail;
    } catch { /* ignore */ }
    throw new APIError(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let malformedEvents = 0;
  const MAX_MALFORMED = 5;

  return new Promise<CheckReport>((resolve, reject) => {
    async function pump() {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            reject(new APIError("Stream ended unexpectedly"));
            return;
          }

          buffer += decoder.decode(value, { stream: true });
          // SSE messages are separated by double newlines
          const parts = buffer.split("\n\n");
          buffer = parts.pop() ?? "";

          for (const chunk of parts) {
            if (!chunk.trim()) continue;

            let eventType = "message";
            const dataLines: string[] = [];

            for (const line of chunk.split("\n")) {
              if (line.startsWith("event: ")) {
                eventType = line.slice(7).trim();
              } else if (line.startsWith("data: ")) {
                dataLines.push(line.slice(6));
              }
            }

            const dataStr = dataLines.join("\n");

            if (!dataStr) continue;

            let data: unknown;
            try {
              data = JSON.parse(dataStr);
            } catch {
              malformedEvents += 1;
              if (malformedEvents > MAX_MALFORMED) {
                reject(new APIError("Server stream sent malformed events"));
                return;
              }
              continue;
            }

            if (eventType === "progress") {
              onProgress(data as ProgressEvent);
            } else if (eventType === "complete") {
              resolve(data as CheckReport);
              return;
            } else if (eventType === "error") {
              const msg = (data as { message?: string }).message ?? "Unknown error";
              reject(new APIError(msg));
              return;
            }
          }
        }
      } catch (err) {
        reject(err);
      }
    }

    pump();
  });
}

export async function downloadAnnotated(file: File, report?: CheckReport): Promise<Blob> {
  const fd = new FormData();
  fd.append("file", file);
  if (report) {
    fd.append("report_json", JSON.stringify(report));
  }
  const r = await axios.post<Blob>("/api/check/annotated", fd, {
    responseType: "blob",
  });
  return r.data;
}

export async function healthCheck(): Promise<boolean> {
  try {
    const r = await axios.get("/api/health");
    return r.data?.status === "ok";
  } catch {
    return false;
  }
}
