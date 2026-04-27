<script setup lang="ts">
</script>

<template>
  <v-card variant="outlined" class="pa-12">
    <v-card-text class="d-flex flex-column align-center">
      <v-progress-circular
        indeterminate
        color="primary"
        size="64"
        width="6"
        class="mb-4"
      />
      <div class="text-h6">Checking document...</div>
      <div class="text-body-2 text-medium-emphasis mt-1">
        This usually takes 2–10 seconds
      </div>
    </v-card-text>
  </v-card>
</template>
