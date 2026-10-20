<template>
  <div class="mp-multi-select">
    <div class="mp-multi-select-main">
      <slot />
    </div>
    <el-button link type="primary" size="small" :disabled="!hasValue"
               @click="$emit('clear')">清空</el-button>
  </div>
</template>

<script setup>
defineProps({
  // 是否有已选内容（没有就禁用清空按钮）
  hasValue: { type: Boolean, default: false },
})
defineEmits(['clear'])
</script>

<style scoped>
.mp-multi-select {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.mp-multi-select-main {
  flex: 1;
  min-width: 0;
}
</style>
