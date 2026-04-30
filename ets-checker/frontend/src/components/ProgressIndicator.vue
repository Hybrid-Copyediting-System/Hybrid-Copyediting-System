<script setup lang="ts">
import { computed } from "vue";
import type { ProgressEvent } from "../api";

const props = withDefaults(
  defineProps<{ progress?: ProgressEvent | null }>(),
  { progress: null },
);

const stepData = computed(() => {
  const p = props.progress;
  if (!p || p.phase === "parsing") return null;
  return {
    pct: Math.round((p.step / p.total_steps) * 100),
    step: p.step,
    total: p.total_steps,
  };
});

const linkData = computed(() => {
  const p = props.progress;
  if (!p || p.phase !== "links") return null;
  return {
    pct: Math.round((p.done / p.total) * 100),
    done: p.done,
    total: p.total,
  };
});
</script>

<template>
  <v-card variant="outlined" class="pa-8">
    <v-card-text class="d-flex flex-column align-center">

      <!-- Overall rule step progress -->
      <div
        v-if="stepData"
        class="d-flex align-center mb-5"
        style="width: 320px"
      >
        <v-progress-linear
          :model-value="stepData.pct"
          color="primary"
          height="6"
          rounded
          bg-color="surface-variant"
          class="flex-grow-1"
        />
        <span
          class="text-caption text-medium-emphasis ml-3"
          style="white-space: nowrap"
        >
          {{ stepData.step }} / {{ stepData.total }}
        </span>
      </div>

      <!-- Link checking sub-progress -->
      <div
        v-if="linkData"
        class="d-flex align-center mb-5"
        style="width: 320px"
      >
        <v-progress-linear
          :model-value="linkData.pct"
          color="secondary"
          height="6"
          rounded
          bg-color="surface-variant"
          class="flex-grow-1"
        />
        <span
          class="text-caption text-medium-emphasis ml-3"
          style="white-space: nowrap"
        >
          {{ linkData.done }} / {{ linkData.total }} links
        </span>
      </div>

      <!-- Spinner (shown for all phases except active link checking) -->
      <v-progress-circular
        v-if="progress?.phase !== 'links'"
        indeterminate
        color="primary"
        size="56"
        width="5"
        class="mb-4"
      />
      <v-icon v-else color="primary" size="48" class="mb-4">
        mdi-link-variant
      </v-icon>

      <!-- Status message -->
      <div class="text-h6 text-center mt-1">
        {{ progress?.message ?? "Checking document..." }}
      </div>
      <div v-if="!progress" class="text-body-2 text-medium-emphasis mt-1">
        This usually takes 2–10 seconds
      </div>

    </v-card-text>
  </v-card>
</template>
