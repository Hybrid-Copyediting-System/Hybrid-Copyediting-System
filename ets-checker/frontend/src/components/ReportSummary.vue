<script setup lang="ts">
import type { ReportSummary } from "../types";

defineProps<{
  summary: ReportSummary;
  fileName: string;
}>();
</script>

<template>
  <v-card variant="outlined">
    <v-card-title class="d-flex align-center">
      <v-icon start>mdi-file-document-check-outline</v-icon>
      {{ fileName }}
    </v-card-title>
    <v-card-text>
      <div class="d-flex ga-3 flex-wrap">
        <v-chip color="success" variant="tonal" size="large">
          <v-icon start>mdi-check-circle</v-icon>
          {{ summary.passed }} passed
        </v-chip>
        <v-chip v-if="summary.errors > 0" color="error" variant="tonal" size="large">
          <v-icon start>mdi-close-circle</v-icon>
          {{ summary.errors }} {{ summary.errors === 1 ? "error" : "errors" }}
        </v-chip>
        <v-chip v-if="summary.warnings > 0" color="warning" variant="tonal" size="large">
          <v-icon start>mdi-alert</v-icon>
          {{ summary.warnings }} {{ summary.warnings === 1 ? "warning" : "warnings" }}
        </v-chip>
        <v-chip v-if="summary.info > 0" color="info" variant="tonal" size="large">
          <v-icon start>mdi-information</v-icon>
          {{ summary.info }} info
        </v-chip>
        <v-chip variant="outlined" size="large">
          {{ summary.total_checks }} checks total
        </v-chip>
      </div>
    </v-card-text>
  </v-card>
</template>
