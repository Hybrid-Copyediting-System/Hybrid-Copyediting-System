<script setup lang="ts">
import { computed } from "vue";
import type { CheckResult } from "../types";
import ReportItem from "./ReportItem.vue";

const props = defineProps<{
  category: string;
  results: CheckResult[];
}>();

const failCount = computed(() => props.results.filter((r) => r.status === "fail").length);
</script>

<template>
  <v-expansion-panels class="mb-3" variant="accordion">
    <v-expansion-panel>
      <v-expansion-panel-title>
        <div class="d-flex align-center ga-2 w-100">
          <span class="text-subtitle-1 font-weight-medium">{{ category }}</span>
          <v-chip
            v-if="failCount > 0"
            color="error"
            variant="tonal"
            size="small"
          >
            {{ failCount }} {{ failCount === 1 ? "issue" : "issues" }}
          </v-chip>
          <v-chip v-else color="success" variant="tonal" size="small">
            all pass
          </v-chip>
        </div>
      </v-expansion-panel-title>
      <v-expansion-panel-text>
        <ReportItem
          v-for="result in results"
          :key="result.rule_id"
          :result="result"
        />
      </v-expansion-panel-text>
    </v-expansion-panel>
  </v-expansion-panels>
</template>
