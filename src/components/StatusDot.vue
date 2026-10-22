<template>
  <span class="mp-status" :title="tip || ''">
    <span class="mp-dot" :class="kind"></span>
    <span>{{ text }}</span>
  </span>
</template>

<script setup>
defineProps({
  kind: { type: String, default: 'muted' }, // ok / warn / danger / muted
  text: { type: String, required: true },
  tip: { type: String, default: '' },        // 悬停提示
})
</script>
