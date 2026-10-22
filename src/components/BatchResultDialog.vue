<template>
  <el-dialog
    :model-value="visible"
    :title="title"
    width="min(600px, 94vw)"
    @update:model-value="$emit('update:visible', $event)"
  >
    <el-alert
      :title="summary"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />
    <el-table :data="items" size="small" max-height="320">
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column prop="reason" label="未处理原因" min-width="240" />
    </el-table>
    <template #footer>
      <el-button type="primary" @click="$emit('update:visible', false)">知道了</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
defineProps({
  visible: Boolean,
  title: { type: String, default: '部分项目未处理' },
  summary: { type: String, default: '' },
  items: { type: Array, default: () => [] },
})
defineEmits(['update:visible'])
</script>
