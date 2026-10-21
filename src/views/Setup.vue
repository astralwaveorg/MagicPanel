<template>
  <div class="mp-auth-page">
    <div class="mp-auth-card">
      <h2 style="margin:0 0 20px">初始化 MagicPanel</h2>
      <el-form :model="form" label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" placeholder="字母、数字、_ . -" />
        </el-form-item>
        <el-form-item label="显示名称（可选）">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item label="密码（至少 8 位）">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="form.confirm" type="password" show-password autocomplete="new-password"
                    @keyup.enter="submit" />
        </el-form-item>
        <el-button style="width:100%" :loading="loading" @click="submit" type="primary">
          创建并进入
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { store } from '../store'

const router = useRouter()
const loading = ref(false)
const form = reactive({ username: '', display_name: '', password: '', confirm: '' })

async function submit() {
  if (!form.username || form.username.length < 2) return ElMessage.warning('用户名至少 2 个字符')
  if (form.password.length < 8) return ElMessage.warning('密码至少 8 位')
  if (form.password !== form.confirm) return ElMessage.warning('两次输入的密码不一致')
  loading.value = true
  try {
    const resp = await api('/api/v1/setup', { method: 'POST', body: {
      username: form.username, password: form.password, display_name: form.display_name,
    } })
    store.initialized = true
    const me = await api('/api/v1/auth/me')
    store.user = me
    store.csrf = me.csrf_token || resp.csrf_token
    router.push('/admin')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>
