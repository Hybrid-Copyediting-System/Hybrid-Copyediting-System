<script setup lang="ts">
import { ref } from "vue";

const emit = defineEmits<{
  (e: "file-selected", file: File): void;
}>();

const isDragging = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

function validateAndEmit(file: File) {
  const name = file.name.toLowerCase();
  if (name.endsWith(".doc") && !name.endsWith(".docx")) {
    alert(
      "ET&S MVP only accepts .docx files.\nOpen in Word and use Save As → .docx."
    );
    return;
  }
  if (!name.endsWith(".docx")) {
    alert("Please upload a .docx file.");
    return;
  }
  emit("file-selected", file);
}

function onDrop(e: DragEvent) {
  isDragging.value = false;
  const files = e.dataTransfer?.files;
  if (files && files.length > 0) {
    validateAndEmit(files[0]);
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files && input.files.length > 0) {
    validateAndEmit(input.files[0]);
  }
}

function triggerFileInput() {
  fileInput.value?.click();
}
</script>

<template>
  <v-card
    :class="['drop-zone', { 'drop-zone--active': isDragging }]"
    variant="outlined"
    @dragover.prevent="isDragging = true"
    @dragleave.prevent="isDragging = false"
    @drop.prevent="onDrop"
    @click="triggerFileInput"
    style="cursor: pointer"
  >
    <v-card-text class="d-flex flex-column align-center justify-center pa-12">
      <v-icon size="64" color="primary" class="mb-4">
        mdi-file-document-outline
      </v-icon>
      <div class="text-h6 mb-2">Drop your .docx file here</div>
      <div class="text-body-2 text-medium-emphasis">
        or click to browse
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".docx"
        style="display: none"
        @change="onFileChange"
      />
    </v-card-text>
  </v-card>
</template>

<style scoped>
.drop-zone {
  border: 2px dashed rgb(var(--v-theme-primary));
  transition: all 0.2s;
}
.drop-zone--active {
  background: rgba(var(--v-theme-primary), 0.08);
  border-color: rgb(var(--v-theme-primary));
}
.drop-zone:hover {
  background: rgba(var(--v-theme-primary), 0.04);
}
</style>
