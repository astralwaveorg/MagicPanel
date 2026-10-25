<template>
  <div class="mp-baseconfig">
    <h2 class="mp-page-title">基础配置</h2>
    <el-tabs v-model="tab" class="mp-bc-tabs">
      <el-tab-pane label="引擎平台" name="targets">
        <TargetsPanel />
      </el-tab-pane>
      <el-tab-pane label="产物配置" name="artifact">
        <ArtifactPanel />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
// 「引擎平台」不再是独立页面，改为基础配置页的第一个 tab；
// tab 走 query 参数（?tab=targets / ?tab=artifact），两个 tab 各自可直达。
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import TargetsPanel from './Targets.vue'
import ArtifactPanel from './ArtifactConfig.vue'

const TABS = ['targets', 'artifact']
const route = useRoute()
const router = useRouter()

const tab = computed({
  get: () => (TABS.includes(route.query.tab) ? route.query.tab : 'artifact'),
  set: (v) => {
    if (route.query.tab === v) return
    router.replace({ path: '/admin/artifact', query: { ...route.query, tab: v } })
  },
})
</script>

<style scoped>
.mp-bc-tabs :deep(.el-tabs__header) { margin-bottom: 14px; }
.mp-bc-tabs :deep(.el-tabs__item) { font-size: 14px; }
/* 面板内的说明段落跟着 tab 走，别跟页面标题挤在一起 */
.mp-bc-tabs :deep(.mp-page-desc) { margin-bottom: 12px; }
</style>
