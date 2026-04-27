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

export async function checkDocument(file: File): Promise<CheckReport> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await axios.post<CheckReport>("/api/check", fd);
  return r.data;
}

export async function downloadAnnotated(file: File): Promise<Blob> {
  const fd = new FormData();
  fd.append("file", file);
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
