<template>
  <div class="mp-empty">
    <strong>{{ reason }}</strong>
    <div v-if="next">{{ next }}</div>
  </div>
</template>

<script setup>
defineProps({
  reason: { type: String, required: true },
  next: { type: String, default: '' },
})
</script>
