import axios from "axios";
import type { CheckReport } from "./types";

export function extractErrorMessage(err: unknown, fallback: string): string {
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

export type ProgressEvent =
  | { phase: "parsing"; message: string }
  | { phase: "rule"; rule_id: string; name: string; step: number; total_steps: number; message: string }
  | { phase: "links_start"; step: number; total_steps: number; message: string }
  | { phase: "links"; done: number; total: number; step: number; total_steps: number; message: string };

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
    throw Object.assign(new Error(detail), { response: { data: { detail } } });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  return new Promise<CheckReport>((resolve, reject) => {
    async function pump() {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            const msg = "Stream ended unexpectedly";
            reject(Object.assign(new Error(msg), { response: { data: { detail: msg } } }));
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
              continue;
            }

            if (eventType === "progress") {
              onProgress(data as ProgressEvent);
            } else if (eventType === "complete") {
              resolve(data as CheckReport);
              return;
            } else if (eventType === "error") {
              const msg = (data as { message?: string }).message ?? "Unknown error";
              reject(Object.assign(new Error(msg), { response: { data: { detail: msg } } }));
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

export async function checkDocument(file: File): Promise<CheckReport> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await axios.post<CheckReport>("/api/check", fd);
  return r.data;
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
