<template>
  <div class="mp-error-state">
    <el-alert type="error" :closable="false" show-icon>
      <template #title>加载失败：{{ error }}</template>
      <div style="margin-top:6px">
        <el-button size="small" @click="$emit('retry')">重试</el-button>
      </div>
    </el-alert>
  </div>
</template>

<script setup>
defineProps({ error: { type: String, default: '' } })
defineEmits(['retry'])
</script>

<style scoped>
.mp-error-state { margin-bottom: 12px; }
</style>
