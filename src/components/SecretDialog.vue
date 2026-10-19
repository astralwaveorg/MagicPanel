<template>
  <el-dialog
    :model-value="visible"
    title="订阅地址已生成"
    width="min(460px, 94vw)"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div class="mp-secret-box">
      <div>
        地址可在首页（门户）随时查看、复制或扫码，无需在此保存。
      </div>
      <div style="font-size: 12.5px; margin-top: 10px">
        该地址包含访问凭据。泄露后持地址者可下载完整配置；
        在 <strong>设备</strong> 页轮换令牌可使旧地址立即失效，节点凭据需联系机场重置。
      </div>
    </div>
    <template #footer>
      <el-button type="primary" @click="$emit('update:visible', false)">知道了</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
defineProps({
  visible: Boolean,
})
defineEmits(['update:visible'])
</script>
