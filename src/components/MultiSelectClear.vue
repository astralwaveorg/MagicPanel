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
  width: 100%;
  min-width: 0;
}
.mp-multi-select-main {
  flex: 1 1 auto;
  min-width: 0;
  width: 100%;
}
/* 控件本体必须撑满主体，窄屏下 el-select 默认会被压成一个箭头小方块 */
.mp-multi-select-main :deep(.el-select),
.mp-multi-select-main :deep(.el-input) {
  width: 100%;
  min-width: 0;
}
.mp-multi-select > .el-button {
  flex: 0 0 auto;
  white-space: nowrap;
}
</style>
