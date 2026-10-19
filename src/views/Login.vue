<template>
  <div class="mp-auth-page">
    <div class="mp-auth-card">
      <h2 style="margin:0 0 4px">MagicPanel</h2>
      <p style="color:var(--mp-text-secondary);font-size:13px;margin:0 0 20px">代理订阅配置管理</p>
      <el-form :model="form" label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="form.username" autocomplete="username" autofocus />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password
                    autocomplete="current-password" @keyup.enter="submit" />
        </el-form-item>
        <el-button type="primary" style="width:100%" :loading="loading" @click="submit">
          登录
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
const form = reactive({ username: '', password: '' })

async function submit() {
  if (!form.username || !form.password) return ElMessage.warning('请输入用户名和密码')
  loading.value = true
  try {
    await api('/api/v1/auth/login', { method: 'POST', body: { ...form } })
    const me = await api('/api/v1/auth/me')
    store.user = me
    store.csrf = me.csrf_token
    router.push('/admin')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>
