<template>
  <img
    v-if="user?.has_avatar"
    class="mp-avatar"
    :src="src"
    :alt="name"
    :style="sizeStyle"
  >
  <span v-else class="mp-avatar mp-avatar-fallback" :style="[sizeStyle, { background: bg }]">
    {{ initial }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { store } from '../store'

const props = defineProps({
  user: { type: Object, default: null },
  size: { type: Number, default: 28 },
})

const name = computed(() => props.user?.display_name || props.user?.username || '?')
const initial = computed(() => {
  const ch = [...name.value][0] || '?'
  return /[a-z]/.test(ch) ? ch.toUpperCase() : ch
})
// 未上传头像时按用户名散列取色，保证同一用户颜色稳定
const bg = computed(() => {
  let h = 0
  for (const ch of props.user?.username || '') h = (h * 31 + ch.codePointAt(0)) % 360
  return `hsl(${h} 48% 42%)`
})
const sizeStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  fontSize: `${Math.round(props.size * 0.46)}px`,
}))
const src = computed(() => `/api/v1/users/${props.user?.id}/avatar?v=${store.avatarVersion}`)
</script>

<style scoped>
.mp-avatar {
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}
.mp-avatar-fallback {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-weight: 600;
  user-select: none;
}
</style>
