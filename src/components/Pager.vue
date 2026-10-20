<template>
  <div class="mp-pager" :class="{ narrow }">
    <!-- 窄屏：总数与每页条数单独一行，分页只留上一页/页码/下一页 -->
    <div v-if="narrow" class="mp-pager-bar">
      <span class="mp-pager-total">共 {{ total }} 条</span>
      <el-select
        :model-value="limit"
        size="small"
        style="width:96px"
        @change="(v) => $emit('change', { page: 1, limit: v })"
      >
        <el-option v-for="s in sizes" :key="s" :value="s" :label="`${s} 条/页`" />
      </el-select>
    </div>
    <el-pagination
      :current-page="page"
      :page-size="limit"
      :page-sizes="sizes"
      :total="total"
      :layout="narrow ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
      :pager-count="narrow ? 5 : 7"
      :small="narrow"
      background
      @current-change="(p) => $emit('change', { page: p, limit })"
      @size-change="(s) => $emit('change', { page: 1, limit: s })"
    />
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

defineProps({
  page: { type: Number, default: 1 },
  limit: { type: Number, default: 50 },
  total: { type: Number, default: 0 },
  sizes: { type: Array, default: () => [20, 50, 100, 200] },
})
defineEmits(['change'])

// 窄屏放不下完整布局（总数 + 每页条数 + 页码 + 跳页），会被挤变形。
// 这里按视口宽度切换布局：宽屏用完整版，窄屏只留翻页与页码。
const narrow = ref(false)
let mql = null
let onChange = null

function applyNarrow(matches) {
  narrow.value = matches
}

onMounted(() => {
  if (typeof window.matchMedia !== 'function') return
  mql = window.matchMedia('(max-width: 768px)')
  applyNarrow(mql.matches)
  onChange = (e) => applyNarrow(e.matches)
  mql.addEventListener('change', onChange)
})

onBeforeUnmount(() => {
  if (mql && onChange) mql.removeEventListener('change', onChange)
})
</script>

<style scoped>
.mp-pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 10px 12px;
  overflow-x: auto;
}
.mp-pager.narrow {
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  padding: 8px 10px 12px;
}
.mp-pager-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.mp-pager-total {
  font-size: 12.5px;
  color: var(--mp-text-secondary);
}
.mp-pager :deep(.el-pagination) {
  flex-wrap: wrap;
  row-gap: 6px;
  justify-content: flex-end;
}
.mp-pager.narrow :deep(.el-pagination) {
  justify-content: center;
}
</style>
