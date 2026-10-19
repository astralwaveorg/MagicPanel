<template>
  <el-dialog
    :model-value="visible"
    title="订阅地址（仅显示一次）"
    width="min(560px, 94vw)"
    :close-on-click-modal="false"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div class="mp-secret-box">
      <div>完整订阅地址：</div>
      <div class="mono" style="margin: 6px 0 10px">{{ url }}</div>
      <canvas ref="qrCanvas" style="display:block;margin:0 auto 10px"></canvas>
      <div style="font-size: 12.5px">
        该地址包含访问凭据，<strong>只在本对话框显示这一次</strong>，关闭后无法再次查看。
        泄露后任何持有地址的人都能下载完整配置；请在「设备」页轮换令牌使旧地址立即失效，
        必要时还需联系机场重置订阅凭据。
      </div>
    </div>
    <template #footer>
      <el-button @click="copy">复制地址</el-button>
      <el-button type="primary" @click="$emit('update:visible', false)">我已妥善保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import QRCode from 'qrcode'

const props = defineProps({
  visible: Boolean,
  url: { type: String, default: '' },
})
defineEmits(['update:visible'])

const qrCanvas = ref(null)

watch(() => props.visible, async (v) => {
  if (v && props.url) {
    await nextTick()
    QRCode.toCanvas(qrCanvas.value, props.url, { width: 200, margin: 1 })
  }
})

async function copy() {
  try {
    await navigator.clipboard.writeText(props.url)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}
</script>
