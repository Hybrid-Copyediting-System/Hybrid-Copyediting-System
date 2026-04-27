import axios from "axios";
import type { CheckReport } from "./types";

export async function checkDocument(file: File): Promise<CheckReport> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await axios.post<CheckReport>("/api/check", fd);
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
