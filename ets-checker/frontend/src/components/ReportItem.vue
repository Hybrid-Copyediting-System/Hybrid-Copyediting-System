<script setup lang="ts">
import type { CheckResult } from "../types";
import SeverityBadge from "./SeverityBadge.vue";

defineProps<{
  result: CheckResult;
}>();
</script>

<template>
  <v-card variant="flat" class="mb-2">
    <v-card-text class="pa-3">
      <div class="d-flex align-center ga-2 mb-1">
        <v-icon
          :color="result.status === 'pass' ? 'success' : 'error'"
          size="small"
        >
          {{ result.status === "pass" ? "mdi-check-circle" : "mdi-close-circle" }}
        </v-icon>
        <span class="text-body-1 font-weight-medium">{{ result.name }}</span>
        <SeverityBadge v-if="result.status === 'fail'" :severity="result.severity" />
        <v-chip v-else color="success" variant="tonal" size="small">pass</v-chip>
        <span class="text-caption text-medium-emphasis ml-auto">
          {{ result.rule_id }}
        </span>
      </div>

      <div v-if="result.details.length > 0" class="mt-2">
        <div
          v-for="(d, i) in result.details"
          :key="i"
          class="detail-item pa-2 rounded mb-1"
        >
          <div class="text-body-2">
            <v-icon size="x-small" class="mr-1">mdi-map-marker</v-icon>
            <span class="text-medium-emphasis">{{ d.location }}</span>
            &mdash; {{ d.message }}
          </div>
          <div v-if="d.expected != null || d.actual != null" class="mt-1 text-caption">
            <span v-if="d.expected != null" class="mr-3">
              <strong>Expected:</strong> {{ d.expected }}
            </span>
            <span v-if="d.actual != null">
              <strong>Actual:</strong> {{ d.actual }}
            </span>
          </div>
          <div v-if="d.excerpt" class="mt-1">
            <code class="text-caption">{{ d.excerpt }}</code>
          </div>
        </div>
      </div>
    </v-card-text>
  </v-card>
</template>

<style scoped>
.detail-item {
  background: rgba(var(--v-theme-on-surface), 0.04);
}
</style>
