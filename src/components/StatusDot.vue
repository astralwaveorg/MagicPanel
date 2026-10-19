<template>
  <span class="mp-status">
    <span class="mp-dot" :class="kind"></span>
    <span>{{ text }}</span>
  </span>
</template>

<script setup>
defineProps({
  kind: { type: String, default: 'muted' }, // ok / warn / danger / muted
  text: { type: String, required: true },
})
</script>
