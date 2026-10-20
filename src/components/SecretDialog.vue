<template>
  <el-dialog
    :model-value="visible"
    title="订阅地址已生成"
    width="min(560px, 94vw)"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div class="mp-secret-box">
      <div v-if="url">
        <div style="font-size:12.5px;margin-bottom:6px">这台设备的订阅地址（只显示这一次，也可随时在首页门户查看）：</div>
        <el-input :model-value="url" readonly class="mono">
          <template #append>
            <el-button @click="copy">复制</el-button>
          </template>
        </el-input>
      </div>
      <div v-else>
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
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: Boolean,
  url: { type: String, default: '' },
})
defineEmits(['update:visible'])

async function copy() {
  try {
    await navigator.clipboard.writeText(props.url)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择复制')
  }
}
</script>
