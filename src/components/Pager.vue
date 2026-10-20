<template>
  <div class="mp-pager">
    <el-pagination
      :current-page="page"
      :page-size="limit"
      :page-sizes="sizes"
      :total="total"
      layout="total, sizes, prev, pager, next, jumper"
      background
      @current-change="$emit('change', { page: $event, limit })"
      @size-change="$emit('change', { page: 1, limit: $event })"
    />
  </div>
</template>

<script setup>
defineProps({
  page: { type: Number, default: 1 },
  limit: { type: Number, default: 50 },
  total: { type: Number, default: 0 },
  sizes: { type: Array, default: () => [20, 50, 100, 200] },
})
defineEmits(['change'])
</script>

<style scoped>
.mp-pager {
  display: flex;
  justify-content: flex-end;
  padding: 10px 12px;
}
</style>
