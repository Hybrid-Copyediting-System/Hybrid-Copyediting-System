<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useTheme } from "vuetify";
import type { CheckReport, ProgressEvent } from "./types";
import {
  checkDocumentStreaming,
  downloadAnnotated,
  extractErrorMessage,
  healthCheck,
} from "./api";
import {
  BLOB_REVOKE_DELAY_MS,
  HEALTH_RETRY_BASE_MS,
  HEALTH_RETRY_MAX_ATTEMPTS,
} from "./constants";
import FileUploader from "./components/FileUploader.vue";
import ProgressIndicator from "./components/ProgressIndicator.vue";
import ReportSummary from "./components/ReportSummary.vue";
import ReportCategory from "./components/ReportCategory.vue";

type AppState = "idle" | "loading" | "report" | "error";

const state = ref<AppState>("idle");
const report = ref<CheckReport | null>(null);
const lastFile = ref<File | null>(null);
const annotatedLoading = ref(false);
const errorMessage = ref("");
const uploadError = ref("");
const downloadError = ref("");
const backendReady = ref(false);
const progressEvent = ref<ProgressEvent | null>(null);
const theme = useTheme();

onMounted(() => {
  // Fire-and-forget health probe with linear backoff so the UI mounts
  // immediately and the warning banner clears once the backend responds.
  let attempt = 0;
  const checkHealth = async () => {
    backendReady.value = await healthCheck();
    if (!backendReady.value && attempt < HEALTH_RETRY_MAX_ATTEMPTS) {
      attempt += 1;
      setTimeout(checkHealth, HEALTH_RETRY_BASE_MS * attempt);
    }
  };
  void checkHealth();
});

function onValidationError(message: string) {
  uploadError.value = message;
}

async function onFileSelected(file: File) {
  state.value = "loading";
  errorMessage.value = "";
  uploadError.value = "";
  downloadError.value = "";
  progressEvent.value = null;
  lastFile.value = file;
  try {
    report.value = await checkDocumentStreaming(file, (evt) => {
      progressEvent.value = evt;
    });
    state.value = "report";
  } catch (err: unknown) {
    state.value = "error";
    errorMessage.value = extractErrorMessage(
      err,
      "Could not connect to backend. Is the server running?",
    );
  }
}

function reset() {
  state.value = "idle";
  report.value = null;
  lastFile.value = null;
  errorMessage.value = "";
  uploadError.value = "";
  downloadError.value = "";
  progressEvent.value = null;
}

async function downloadAnnotatedDocx() {
  if (!lastFile.value || !report.value) return;
  annotatedLoading.value = true;
  downloadError.value = "";
  let objUrl: string | null = null;
  let succeeded = false;
  try {
    const blob = await downloadAnnotated(lastFile.value, report.value ?? undefined);
    const stem = report.value.file_name.replace(/\.docx$/i, "");
    const a = document.createElement("a");
    objUrl = URL.createObjectURL(blob);
    a.href = objUrl;
    a.download = `${stem}.annotated.docx`;
    a.click();
    succeeded = true;
  } catch (err: unknown) {
    downloadError.value = extractErrorMessage(
      err,
      "Could not generate annotated copy.",
    );
  } finally {
    annotatedLoading.value = false;
    if (objUrl) {
      // On success, defer revocation so the download has time to start.
      // On failure, revoke immediately so the blob URL doesn't leak.
      const url = objUrl;
      if (succeeded) {
        setTimeout(() => URL.revokeObjectURL(url), BLOB_REVOKE_DELAY_MS);
      } else {
        URL.revokeObjectURL(url);
      }
    }
  }
}

function downloadJson() {
  if (!report.value) return;
  const blob = new Blob([JSON.stringify(report.value, null, 2)], {
    type: "application/json",
  });
  const a = document.createElement("a");
  const objUrl = URL.createObjectURL(blob);
  a.href = objUrl;
  a.download = `${report.value.file_name}-report.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(objUrl), BLOB_REVOKE_DELAY_MS);
}

function toggleTheme() {
  theme.global.name.value =
    theme.global.name.value === "light" ? "dark" : "light";
}

function getCategories(r: CheckReport): string[] {
  return [...new Set(r.results.map((item) => item.category))];
}
</script>

<template>
  <v-app>
    <v-app-bar color="primary" density="compact">
      <v-app-bar-title>ET&S Format Checker</v-app-bar-title>
      <v-spacer />
      <v-btn icon @click="toggleTheme">
        <v-icon>mdi-theme-light-dark</v-icon>
      </v-btn>
    </v-app-bar>

    <v-main>
      <v-container class="py-8" style="max-width: 900px">
        <!-- Backend not ready warning -->
        <v-alert
          v-if="!backendReady && state === 'idle'"
          type="warning"
          variant="tonal"
          class="mb-4"
        >
          Backend not detected. Make sure the server is running on port 8080.
        </v-alert>

        <!-- Idle: upload -->
        <div v-if="state === 'idle'">
          <v-alert
            v-if="uploadError"
            type="error"
            variant="tonal"
            closable
            class="mb-4"
            @click:close="uploadError = ''"
          >
            {{ uploadError }}
          </v-alert>
          <FileUploader
            @file-selected="onFileSelected"
            @validation-error="onValidationError"
          />
          <v-card variant="outlined" class="mt-4 pa-4">
            <v-card-text class="text-body-2 text-medium-emphasis">
              <strong>Tip:</strong> If your document was created with Zotero or Mendeley,
              use <em>File → Convert Bibliography to Plain Text</em> in Word before uploading.
              Only <code>.docx</code> files are accepted.
            </v-card-text>
          </v-card>
        </div>

        <!-- Loading with real-time progress -->
        <ProgressIndicator v-if="state === 'loading'" :progress="progressEvent" />

        <!-- Error -->
        <div v-if="state === 'error'">
          <v-alert type="error" variant="tonal" class="mb-4">
            {{ errorMessage }}
          </v-alert>
          <v-btn color="primary" variant="outlined" @click="reset">
            <v-icon start>mdi-arrow-left</v-icon>
            Try another file
          </v-btn>
        </div>

        <!-- Report -->
        <div v-if="state === 'report' && report">
          <div class="d-flex align-center mb-4">
            <v-btn color="primary" variant="text" @click="reset">
              <v-icon start>mdi-arrow-left</v-icon>
              Check another file
            </v-btn>
            <v-spacer />
            <v-btn
              color="primary"
              variant="outlined"
              class="mr-2"
              :loading="annotatedLoading"
              :disabled="!lastFile || !report"
              @click="downloadAnnotatedDocx"
            >
              <v-icon start>mdi-file-document-edit-outline</v-icon>
              Download annotated .docx
            </v-btn>
            <v-btn color="primary" variant="outlined" @click="downloadJson">
              <v-icon start>mdi-download</v-icon>
              Download JSON
            </v-btn>
          </div>

          <v-alert
            v-if="downloadError"
            type="error"
            variant="tonal"
            closable
            class="mb-4"
            @click:close="downloadError = ''"
          >
            {{ downloadError }}
          </v-alert>

          <ReportSummary :summary="report.summary" :file-name="report.file_name" />

          <div class="mt-6">
            <ReportCategory
              v-for="cat in getCategories(report)"
              :key="cat"
              :category="cat"
              :results="report.results.filter((r) => r.category === cat)"
            />
          </div>
        </div>
      </v-container>
    </v-main>
  </v-app>
</template>
