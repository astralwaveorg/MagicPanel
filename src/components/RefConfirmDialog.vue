<template>
  <el-dialog
    :model-value="visible"
    :title="title"
    width="min(560px, 94vw)"
    @update:model-value="$emit('update:visible', $event)"
  >
    <el-alert :title="message" type="warning" :closable="false" show-icon style="margin-bottom: 12px" />

    <div v-if="references.length" class="ref-block">
      <div class="ref-title">被这些配置引用：</div>
      <ul class="ref-list">
        <li v-for="(r, i) in references" :key="`${r.id}-${i}`">
          <span class="ref-name">{{ r.name }}</span>
          <span v-if="r.type" class="ref-tag">{{ r.type }}</span>
          <span v-if="r.extra" class="ref-extra">{{ r.extra }}</span>
        </li>
      </ul>
    </div>

    <div v-if="choices.length" class="choice-block">
      <div class="ref-title">{{ choiceLabel }}</div>
      <el-select :model-value="choiceValue" :placeholder="choicePlaceholder"
                 size="small" style="width:100%" @update:model-value="$emit('update:choiceValue', $event)">
        <el-option v-for="c in choices" :key="c.id" :label="c.label" :value="c.id" />
      </el-select>
    </div>

    <div v-if="warnings.length" class="warn-block">
      <div v-for="(w, i) in warnings" :key="i" class="warn-item">· {{ w }}</div>
    </div>

    <p class="ref-hint">{{ hint }}</p>

    <template #footer>
      <el-button @click="$emit('update:visible', false)">取消</el-button>
      <el-button type="danger" :loading="busy" @click="$emit('confirm')">
        {{ confirmText }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
defineProps({
  visible: Boolean,
  title: { type: String, default: '删除确认' },
  message: { type: String, default: '' },
  references: { type: Array, default: () => [] },
  warnings: { type: Array, default: () => [] },
  hint: { type: String, default: '' },
  confirmText: { type: String, default: '删除并解除关联' },
  busy: Boolean,
  choices: { type: Array, default: () => [] },
  choiceLabel: { type: String, default: '' },
  choicePlaceholder: { type: String, default: '请选择' },
  choiceValue: { type: [Number, String], default: null },
})
defineEmits(['update:visible', 'confirm', 'update:choiceValue'])
</script>

<style scoped>
.ref-block {
  border: 1px solid var(--mp-border);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.ref-title {
  font-size: 12.5px;
  color: var(--mp-text-secondary);
  margin-bottom: 6px;
}
.ref-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  max-height: 220px;
  overflow: auto;
}
.ref-list li { margin-bottom: 4px; }
.ref-name { font-weight: 600; }
.ref-tag {
  margin-left: 6px;
  font-size: 11.5px;
  color: var(--mp-text-secondary);
  border: 1px solid var(--mp-border);
  border-radius: 4px;
  padding: 0 5px;
}
.ref-extra {
  margin-left: 6px;
  font-size: 12px;
  color: var(--mp-text-secondary);
}
.choice-block {
  border: 1px solid var(--mp-border);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.warn-block {
  background: rgba(230, 120, 60, 0.1);
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 10px;
}
.warn-item {
  font-size: 12.5px;
  color: var(--mp-text-secondary);
  line-height: 1.7;
}
.ref-hint {
  margin: 0;
  font-size: 12.5px;
  color: var(--mp-text-secondary);
  line-height: 1.7;
}
</style>
