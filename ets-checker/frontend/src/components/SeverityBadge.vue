<script setup lang="ts">
defineProps<{
  severity: "error" | "warning" | "info";
}>();

const colorMap = {
  error: "error",
  warning: "warning",
  info: "info",
};

const iconMap = {
  error: "mdi-close-circle",
  warning: "mdi-alert",
  info: "mdi-information",
};
</script>

<template>
  <v-chip :color="colorMap[severity]" variant="tonal" size="small">
    <v-icon start size="small">{{ iconMap[severity] }}</v-icon>
    {{ severity }}
  </v-chip>
</template>
