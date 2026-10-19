<template>
  <div>
    <h2 class="mp-page-title">设置</h2>
    <p class="mp-page-desc">对外地址、维护者账号与备份。</p>

    <div class="mp-card">
      <h3>分发设置</h3>
      <el-form label-position="top" style="max-width:560px">
        <el-form-item label="对外基础地址（订阅链接使用该地址；留空则按当前访问地址生成）">
          <el-input v-model="settings.base_url" class="mono" placeholder="https://panel.example.com" />
        </el-form-item>
        <el-form-item label="会话有效期（小时）">
          <el-input-number v-model.number="settings.session_ttl_hours" :min="1" :max="720" />
        </el-form-item>
        <el-form-item label="配置更新提示（小时，写入 profile-update-interval，仅为客户端提示）">
          <el-input-number v-model.number="settings.profile_update_interval" :min="1" :max="168" />
        </el-form-item>
        <el-form-item label="核心下载代理（可选，仅用于安装测速核心，例如 http://127.0.0.1:7890）">
          <el-input v-model="settings.core_proxy" class="mono" placeholder="留空表示直连" />
        </el-form-item>
        <el-button type="primary" :loading="savingSettings" @click="saveSettings">保存设置</el-button>
      </el-form>
    </div>

    <div class="mp-card">
      <h3>门户展示页（/）</h3>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:0 0 12px">
        门户页用于快速查看并复制各设备的订阅地址，凭 4 位 PIN 进入。
        PIN 与维护者账号绑定，每人设置自己的 PIN，任一有效 PIN 都可进入；
        撤销某人的 PIN 不影响其他人。PIN 只是查看门槛，订阅链接本身的安全性由地址中的高熵令牌承担；
        PIN 连续输错 5 次会锁定 10 分钟。
      </p>
      <el-form label-position="top" style="max-width:420px">
        <el-form-item :label="store.user?.has_portal_pin ? '更换我的 PIN（4 位数字）' : '设置我的 PIN（4 位数字）'">
          <el-input v-model="portalPin" maxlength="4" placeholder="4 位数字"
                    style="max-width:200px" class="mono" />
        </el-form-item>
        <el-button type="primary" :loading="savingPin" @click="savePin">
          {{ store.user?.has_portal_pin ? '更换 PIN' : '设置 PIN' }}
        </el-button>
        <el-button v-if="store.user?.has_portal_pin" type="danger" plain :loading="savingPin"
                   @click="clearPin">撤销我的 PIN</el-button>
        <span style="margin-left:12px;font-size:12.5px"
              :style="{ color: portalEnabled ? 'var(--mp-ok)' : 'var(--mp-text-secondary)' }">
          门户页{{ portalEnabled ? '已开启' : '未开启（至少一人设置 PIN 后开启）' }}
        </span>
      </el-form>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:14px 0 0">
        已设置 PIN 的维护者：{{ pinUsersText }}
      </p>
    </div>

    <div class="mp-card">
      <div class="mp-toolbar">
        <h3 style="margin:0">维护者账号</h3>
        <el-button type="primary" plain @click="userDialog = true">添加维护者</el-button>
      </div>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:0 0 12px">
        所有维护者共享同一份配置数据，账号仅用于访问控制，不隔离各自资料。
      </p>
      <div class="mp-table-wrap">
        <el-table :data="users" size="small">
          <el-table-column prop="username" label="用户名" min-width="120" />
          <el-table-column prop="display_name" label="显示名称" min-width="120">
            <template #default="{ row }">{{ row.display_name || '—' }}</template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="135">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="最近登录" min-width="135">
            <template #default="{ row }">{{ fmtTime(row.last_login_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" type="danger" plain
                         :disabled="row.username === store.user?.username"
                         @click="removeUser(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="mp-card">
      <h3>修改我的密码</h3>
      <el-form label-position="top" style="max-width:420px">
        <el-form-item label="原密码">
          <el-input v-model="pwd.old_password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码（至少 8 位；修改后其他设备的会话将失效）">
          <el-input v-model="pwd.new_password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-button :loading="changingPwd" @click="changePwd">修改密码</el-button>
      </el-form>
    </div>

    <div class="mp-card">
      <h3>备份与恢复</h3>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:0 0 12px">
        备份包含加密后的订阅地址与设备令牌摘要，需与服务端 data/secret.key 分开保管。
        恢复会覆盖当前全部数据。
      </p>
      <el-button @click="exportBackup">导出备份（JSON）</el-button>
      <el-upload :auto-upload="false" :show-file-list="false" accept=".json" :on-change="importBackup">
        <el-button type="warning" plain>从备份恢复</el-button>
      </el-upload>
    </div>

    <el-dialog v-model="userDialog" title="添加维护者" width="min(480px, 94vw)">
      <el-form :model="userForm" label-position="top">
        <el-form-item label="用户名">
          <el-input v-model="userForm.username" autocomplete="off" />
        </el-form-item>
        <el-form-item label="显示名称（可选）">
          <el-input v-model="userForm.display_name" />
        </el-form-item>
        <el-form-item label="初始密码（至少 8 位，请告知对方尽快修改）">
          <el-input v-model="userForm.password" type="password" show-password autocomplete="off" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="userDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingUser" @click="addUser">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { confirmBox } from '../confirm'
import { store } from '../store'
import { fmtTime } from '../format'

const settings = reactive({ base_url: '', session_ttl_hours: 168, profile_update_interval: 12, core_proxy: '' })
const savingSettings = ref(false)
const users = ref([])
const userDialog = ref(false)
const savingUser = ref(false)
const userForm = reactive({ username: '', display_name: '', password: '' })
const pwd = reactive({ old_password: '', new_password: '' })
const changingPwd = ref(false)
const portalEnabled = ref(false)
const portalPin = ref('')
const savingPin = ref(false)

const pinUsersText = computed(() => {
  const names = users.value
    .filter((u) => u.has_portal_pin)
    .map((u) => u.display_name || u.username)
  return names.length ? names.join('、') : '暂无'
})

async function load() {
  try {
    const [s, u, p] = await Promise.all([
      api('/api/v1/settings'), api('/api/v1/users'), api('/api/v1/portal/status'),
    ])
    Object.assign(settings, {
      base_url: s.base_url || '',
      session_ttl_hours: Number(s.session_ttl_hours) || 168,
      profile_update_interval: Number(s.profile_update_interval) || 12,
      core_proxy: s.core_proxy || '',
    })
    users.value = u
    portalEnabled.value = p.enabled
    // 本人 PIN 状态以 /auth/me 为准（users 列表里也有，但这里同步当前会话）
    const me = users.value.find((x) => x.username === store.user?.username)
    if (me && store.user) store.user.has_portal_pin = me.has_portal_pin
  } catch (e) {
    ElMessage.error(e.message)
  }
}
onMounted(load)

async function savePin() {
  if (!/^\d{4}$/.test(portalPin.value)) return ElMessage.warning('PIN 必须是 4 位数字')
  savingPin.value = true
  try {
    await api('/api/v1/portal/my-pin', { method: 'POST', body: { pin: portalPin.value } })
    if (store.user) store.user.has_portal_pin = true
    portalEnabled.value = true
    portalPin.value = ''
    ElMessage.success('PIN 已设置，门户页地址为站点根路径 /')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingPin.value = false
  }
}

async function clearPin() {
  if (!await confirmBox(
    '撤销后你的 PIN 将不能进入门户页；其他维护者的 PIN 不受影响。确定继续？', '撤销门户 PIN')) return
  savingPin.value = true
  try {
    await api('/api/v1/portal/my-pin', { method: 'DELETE' })
    if (store.user) store.user.has_portal_pin = false
    ElMessage.success('已撤销')
    await load()
    portalEnabled.value = users.value.some((u) => u.has_portal_pin)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingPin.value = false
  }
}

async function saveSettings() {
  savingSettings.value = true
  try {
    await api('/api/v1/settings', { method: 'PUT', body: { values: {
      base_url: settings.base_url,
      session_ttl_hours: String(settings.session_ttl_hours),
      profile_update_interval: String(settings.profile_update_interval),
      core_proxy: settings.core_proxy,
    } } })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingSettings.value = false
  }
}

async function addUser() {
  if (userForm.password.length < 8) return ElMessage.warning('密码至少 8 位')
  savingUser.value = true
  try {
    await api('/api/v1/users', { method: 'POST', body: { ...userForm } })
    userDialog.value = false
    Object.assign(userForm, { username: '', display_name: '', password: '' })
    ElMessage.success('已创建')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingUser.value = false
  }
}

async function removeUser(row) {
  if (!await confirmBox(`删除维护者「${row.username}」？其所有会话将失效。`, '删除维护者')) return
  try {
    await api(`/api/v1/users/${row.id}`, { method: 'DELETE' })
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function changePwd() {
  if (pwd.new_password.length < 8) return ElMessage.warning('新密码至少 8 位')
  changingPwd.value = true
  try {
    await api('/api/v1/auth/password', { method: 'POST', body: { ...pwd } })
    Object.assign(pwd, { old_password: '', new_password: '' })
    ElMessage.success('密码已修改，其他会话已失效')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    changingPwd.value = false
  }
}

async function exportBackup() {
  try {
    const data = await api('/api/v1/backup/export')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `magicpanel-backup-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('备份已导出，请妥善保管')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function importBackup(file) {
  let data
  try {
    data = JSON.parse(await file.raw.text())
  } catch {
    return ElMessage.error('备份文件不是有效的 JSON')
  }
  if (!await confirmBox('恢复会覆盖当前全部数据（账号、策略、设备、构建记录），确定继续？', '恢复备份')) return
  try {
    await api('/api/v1/backup/restore', { method: 'POST', body: { confirm: true, data } })
    ElMessage.success('已恢复，请重新登录')
    store.user = null
    location.assign('/admin/login')
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>
