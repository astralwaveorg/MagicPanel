import { reactive } from 'vue'

export const store = reactive({
  user: null,
  csrf: '',
  ready: false,
  initialized: true,
})
