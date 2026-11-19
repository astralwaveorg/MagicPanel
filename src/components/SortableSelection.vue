<template>
  <ol v-if="modelValue.length" ref="list" class="mp-selected-order" :aria-label="label">
    <li v-for="(value, index) in modelValue" :key="value" class="mp-order-item">
      <span class="mp-order-handle" aria-hidden="true" title="拖动排序">⠿</span>
      <span class="mp-order-label">{{ labels[value] ?? value }}</span>
      <el-button text size="small" :disabled="index === 0"
                 :aria-label="'上移 ' + (labels[value] ?? value)" @click="move(index, index - 1)">↑</el-button>
      <el-button text size="small" :disabled="index === modelValue.length - 1"
                 :aria-label="'下移 ' + (labels[value] ?? value)" @click="move(index, index + 1)">↓</el-button>
    </li>
  </ol>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import Sortable from 'sortablejs'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  labels: { type: Object, default: () => ({}) },
  label: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])
const list = ref(null)
let sorter

function move(from, to) {
  if (from == null || to == null || from === to || from < 0 || to < 0
      || from >= props.modelValue.length || to >= props.modelValue.length) return
  const next = props.modelValue.slice()
  next.splice(to, 0, next.splice(from, 1)[0])
  emit('update:modelValue', next)
}

function destroy() {
  sorter?.destroy()
  sorter = null
}

watch(list, (element) => {
  destroy()
  if (!element) return
  sorter = Sortable.create(element, {
    handle: '.mp-order-handle',
    animation: 120,
    delay: 180,
    delayOnTouchOnly: true,
    touchStartThreshold: 8,
    ghostClass: 'mp-drag-ghost',
    onEnd({ oldIndex, newIndex, item, from }) {
      if (oldIndex == null || newIndex == null || oldIndex === newIndex) return
      // 先恢复 Vue 当前的 DOM 顺序，再交给渲染器更新。
      item.remove()
      from.insertBefore(item, from.children[oldIndex] ?? null)
      move(oldIndex, newIndex)
    },
  })
}, { flush: 'post' })
onBeforeUnmount(destroy)
</script>

<style scoped>
.mp-selected-order { width: 100%; margin: 8px 0 0; padding: 0; list-style: none; }
.mp-order-item {
  display: flex; align-items: center; gap: 4px; min-height: 30px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.mp-order-handle { cursor: grab; padding: 0 8px 0 3px; color: var(--mp-text-secondary); font-size: 17px; }
.mp-order-label { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.mp-order-item :deep(.el-button) { margin: 0; padding: 0 8px; }
</style>
