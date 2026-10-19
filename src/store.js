import { reactive } from 'vue'

export const store = reactive({
  user: null,
  csrf: '',
  ready: false,
  initialized: true,
  // 头像更新时自增，触发头像地址刷新
  avatarVersion: 0,
})
