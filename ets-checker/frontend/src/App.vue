<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useTheme } from "vuetify";
import type { CheckReport } from "./types";
import { checkDocument, healthCheck } from "./api";
import FileUploader from "./components/FileUploader.vue";
import ProgressIndicator from "./components/ProgressIndicator.vue";
import ReportSummary from "./components/ReportSummary.vue";
import ReportCategory from "./components/ReportCategory.vue";

type AppState = "idle" | "loading" | "report" | "error";

const state = ref<AppState>("idle");
const report = ref<CheckReport | null>(null);
const errorMessage = ref("");
const backendReady = ref(false);
const theme = useTheme();

onMounted(async () => {
  backendReady.value = await healthCheck();
});

async function onFileSelected(file: File) {
  state.value = "loading";
  errorMessage.value = "";
  try {
    report.value = await checkDocument(file);
    state.value = "report";
  } catch (err: unknown) {
    state.value = "error";
    if (
      typeof err === "object" &&
      err !== null &&
      "response" in err &&
      typeof (err as Record<string, unknown>).response === "object"
    ) {
      const resp = (err as { response: { data?: { detail?: string } } }).response;
      errorMessage.value = resp.data?.detail || "Unknown error";
    } else {
      errorMessage.value = "Could not connect to backend. Is the server running?";
    }
  }
}

function reset() {
  state.value = "idle";
  report.value = null;
  errorMessage.value = "";
}

function downloadJson() {
  if (!report.value) return;
  const blob = new Blob([JSON.stringify(report.value, null, 2)], {
    type: "application/json",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${report.value.file_name}-report.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function toggleTheme() {
  theme.global.name.value =
    theme.global.name.value === "light" ? "dark" : "light";
}

function getCategories(r: CheckReport): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of r.results) {
    if (!seen.has(item.category)) {
      seen.add(item.category);
      result.push(item.category);
    }
  }
  return result;
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
          <FileUploader @file-selected="onFileSelected" />
          <v-card variant="outlined" class="mt-4 pa-4">
            <v-card-text class="text-body-2 text-medium-emphasis">
              <strong>Tip:</strong> If your document was created with Zotero or Mendeley,
              use <em>File → Convert Bibliography to Plain Text</em> in Word before uploading.
              Only <code>.docx</code> files are accepted.
            </v-card-text>
          </v-card>
        </div>

        <!-- Loading -->
        <ProgressIndicator v-if="state === 'loading'" />

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
            <v-btn color="primary" variant="outlined" @click="downloadJson">
              <v-icon start>mdi-download</v-icon>
              Download JSON
            </v-btn>
          </div>

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
