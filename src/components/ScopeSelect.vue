<template>
  <MultiSelectClear :has-value="display.length" @clear="clear">
    <el-select
      :model-value="display"
      multiple
      style="width:100%"
      :placeholder="placeholder"
      @change="onChange"
    >
      <!-- "包含所有"用一个可读的文案当值：多选框显示的是选中项的值，
           用 "*" 会被原样显示出来，用户看不懂 -->
      <el-option :value="allLabel" :label="allLabel" />
      <el-option v-for="name in options" :key="name" :value="name" :label="name" />
    </el-select>
  </MultiSelectClear>
</template>

<script setup>
import { computed } from 'vue'
import MultiSelectClear from './MultiSelectClear.vue'

// 适用范围多选：对外是接口的值（"*" 表示包含所有），对内换成可读文案。
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  // 可选的具体项（平台名 / 设备名 / 来源名）
  options: { type: Array, default: () => [] },
  // "包含所有"这一项的文案，同时也是它在多选框里显示的值
  allLabel: { type: String, required: true },
  placeholder: { type: String, default: '请选择' },
})
const emit = defineEmits(['update:modelValue'])

const ALL = '*'

// 接口的 ["*"] → 界面上的 [文案]
const display = computed(() => (props.modelValue || []).map(
  (v) => (v === ALL ? props.allLabel : v),
))

// 交互规则：
//   勾上"包含所有"  → 其它选项全部取消
//   取消"包含所有"  → 选择清空
//   勾上具体项      → 如果原来勾着"包含所有"，把它取消掉，具体项保留
function onChange(list) {
  const arr = Array.isArray(list) ? list : []
  const hadAll = display.value.includes(props.allLabel)
  const hasAll = arr.includes(props.allLabel)
  let next
  if (hasAll && !hadAll) {
    next = [props.allLabel]
  } else if (!hasAll && hadAll) {
    next = arr
  } else if (hasAll) {
    next = arr.filter((v) => v !== props.allLabel)
  } else {
    next = arr
  }
  emit('update:modelValue', next.map((v) => (v === props.allLabel ? ALL : v)))
}

function clear() {
  emit('update:modelValue', [])
}
</script>
