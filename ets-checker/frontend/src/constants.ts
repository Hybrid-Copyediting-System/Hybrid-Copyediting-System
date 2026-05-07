// Maximum upload size accepted by the backend (also enforced server-side).
export const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024;
export const MAX_FILE_SIZE_LABEL = "50 MB";

// Health-probe linear backoff: each retry waits attempt * HEALTH_RETRY_BASE_MS.
export const HEALTH_RETRY_BASE_MS = 2000;
export const HEALTH_RETRY_MAX_ATTEMPTS = 5;

// Defer revoking object URLs after a successful download so the browser has
// time to start the file save dialog before the URL is invalidated.
export const BLOB_REVOKE_DELAY_MS = 60_000;
