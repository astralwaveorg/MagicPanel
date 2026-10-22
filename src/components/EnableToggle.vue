<template>
  <el-button
    size="small"
    :type="enabled ? 'success' : ''"
    :plain="enabled"
    :loading="loading"
    :title="enabled ? '点击停用' : '点击启用'"
    @click="$emit('toggle')"
  >
    {{ enabled ? '已启用' : '已停用' }}
  </el-button>
</template>

<script setup>
// 启停开关：按钮上直接写当前状态，点了就切换。
// 绿 = 已启用（启用中会参与抓取、测速与构建），灰 = 已停用。
defineProps({
  enabled: { type: Boolean, default: true },
  loading: { type: Boolean, default: false },
})
defineEmits(['toggle'])
</script>
