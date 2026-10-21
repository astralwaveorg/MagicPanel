<template>
  <div>
    <h2 class="mp-page-title">设置</h2>
    <p class="mp-page-desc">对外地址、测速核心、首页访问 PIN、账号与备份。</p>

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
      <h3>WebDAV 远程备份</h3>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:0 0 12px">
        把数据库快照与主密钥备份到远端 WebDAV（NAS、坚果云、Nextcloud 等）。
        容器内的本地备份与数据在同一块磁盘上，磁盘故障会一起丢；
        远端副本是跨故障的最后一道保险。备份可自动定时执行，也可随时手动触发。
      </p>
      <el-form label-position="top" style="max-width:560px">
        <el-form-item label="启用自动备份">
          <el-switch v-model="webdav.enabled" />
          <div class="mp-form-hint">
            关闭后仍可手动上传备份；定时任务与调度器总开关无关。
          </div>
        </el-form-item>
        <el-form-item label="WebDAV 地址">
          <el-input v-model="webdav.url" class="mono"
                    placeholder="https://dav.example.com/remote.php/dav/files/mypanel" />
        </el-form-item>
        <el-form-item label="备份目录（相对地址根目录）">
          <el-input v-model="webdav.directory" class="mono" placeholder="magicpanel" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="webdav.username" class="mono" autocomplete="off" />
        </el-form-item>
        <el-form-item label="口令">
          <el-input v-model="webdav.password" type="password" show-password
                    autocomplete="new-password"
                    :placeholder="webdav.password_set ? '已配置（留空表示不修改）' : '未设置'" />
          <div class="mp-form-hint">口令加密存储，界面与接口都不会回显明文。</div>
        </el-form-item>
        <el-form-item label="自动备份间隔（小时）">
          <el-input-number v-model="webdav.interval_hours" :min="1" :max="720" />
        </el-form-item>
        <el-form-item label="远端保留份数">
          <el-input-number v-model="webdav.keep" :min="1" :max="100" />
          <div class="mp-form-hint">超出后自动删除最旧的快照与其主密钥。</div>
        </el-form-item>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <el-button type="primary" :loading="webdavSaving" @click="saveWebdav">保存配置</el-button>
          <el-button :loading="webdavTesting" @click="testWebdav">测试连接</el-button>
          <el-button :loading="webdavUploading" @click="uploadWebdav">立即备份到 WebDAV</el-button>
          <el-button @click="loadWebdavFiles">查看远端备份</el-button>
        </div>
      </el-form>
      <div v-if="webdavInfo" style="margin-top:12px;font-size:12.5px;color:var(--mp-text-secondary)">
        上次备份：{{ webdavInfo.last_backup_at ? fmtTime(webdavInfo.last_backup_at) : '—' }}
        <span v-if="webdavInfo.last_status">（{{ webdavInfo.last_status }}）</span>
        <div v-if="webdavInfo.last_error" style="color:var(--mp-danger, #f56c6c)">
          {{ webdavInfo.last_error }}
        </div>
      </div>
      <el-table v-if="webdavFiles.length" :data="webdavFiles" size="small"
                style="margin-top:12px">
        <el-table-column prop="name" label="远端文件" min-width="220" class="mono" />
        <el-table-column label="大小" width="110" align="right">
          <template #default="{ row }">{{ (row.size / 1024 / 1024).toFixed(1) }} MB</template>
        </el-table-column>
        <el-table-column prop="modified" label="修改时间" min-width="180" />
        <el-table-column label="操作" width="120" align="right">
          <template #default="{ row }">
            <el-button v-if="row.name.endsWith('.db')" size="small" type="warning" plain
                       @click="restoreWebdav(row)">恢复</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="mp-card">
      <h3>测速核心</h3>
      <div v-if="core" style="display:flex;flex-direction:column;gap:10px;max-width:640px">
        <StatusDot :kind="core.available ? 'ok' : 'muted'"
                   :text="core.available ? `已安装：${core.version}` : '未安装'" />
        <div style="font-size:12.5px;color:var(--mp-text-secondary)">
          服务端平台 <span class="mono">{{ core.platform }}</span><template v-if="core.asset_hint">，手动下载请选 <span class="mono">{{ core.asset_hint }}</span></template>
        </div>
        <div>
          <el-button type="primary" plain :loading="coreBusy" @click="installCoreOnline">
            在线安装最新版
          </el-button>
          <el-upload
            :auto-upload="false" :show-file-list="false" :on-change="onUploadCore"
            style="display:inline-block;margin-left:10px"
          >
            <el-button plain :loading="coreBusy">本地上传安装 / 更新</el-button>
          </el-upload>
        </div>
        <p class="mp-form-hint mp-nowrap-line">
          服务端访问不了 GitHub 时，从
          <a href="https://github.com/MetaCubeX/mihomo/releases" target="_blank" rel="noopener">Mihomo 发布页</a>
          下载对应平台的包上传，自动解压替换。
        </p>
      </div>
    </div>

    <div class="mp-card">
      <h3>Magic Panel 首页访问</h3>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:0 0 12px">
        首页凭 4 位 PIN 进入，用于快速复制设备订阅地址；已登录维护者免 PIN。
        PIN 与账号绑定，一人一 PIN，任一有效即可进入，撤销某人的不影响其他人。
        PIN 只是查看门槛，链接安全由地址中的高熵令牌承担；连续输错 5 次锁定 10 分钟。
      </p>
      <!-- 输入框与按钮同一行；窄屏再换行 -->
      <div class="mp-row-actions">
        <el-input v-model="portalPin" maxlength="4" placeholder="4 位数字"
                  class="mono mp-pin-input" />
        <el-button type="primary" :loading="savingPin" @click="savePin">
          {{ store.user?.has_portal_pin ? '更换 PIN' : '设置 PIN' }}
        </el-button>
        <el-button v-if="store.user?.has_portal_pin" type="danger" plain :loading="savingPin"
                   @click="clearPin">撤销我的 PIN</el-button>
      </div>
      <p class="mp-form-hint" style="margin:8px 0 0">
        {{ store.user?.has_portal_pin ? '更换我的 PIN（4 位数字）' : '设置我的 PIN（4 位数字）' }}
      </p>
      <span style="font-size:12.5px;margin-top:8px;display:block"
            :style="{ color: portalEnabled ? 'var(--mp-ok)' : 'var(--mp-text-secondary)' }">
        Magic Panel 首页{{ portalEnabled ? '已开启' : '未开启（至少一人设置 PIN 后开启）' }}
      </span>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:14px 0 0">
        已设置 PIN 的维护者：{{ pinUsersText }}
      </p>
    </div>

    <div class="mp-card">
      <h3>我的头像</h3>
      <div style="display:flex;align-items:center;gap:16px">
        <UserAvatar :user="store.user" :size="56" />
        <!-- 两个按钮并排一行，窄屏再换行 -->
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
          <el-upload
            :auto-upload="false" :show-file-list="false"
            accept="image/png,image/jpeg,image/webp" :on-change="uploadAvatar"
          >
            <el-button type="primary" plain>上传头像</el-button>
          </el-upload>
          <el-button v-if="store.user?.has_avatar" type="danger" plain @click="removeAvatar">移除</el-button>
          <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:8px 0 0">
            支持 PNG / JPEG / WebP，不超过 2 MB；未上传时按用户名生成默认头像。
          </p>
        </div>
      </div>
    </div>

    <div class="mp-card">
      <div class="mp-toolbar">
        <h3 style="margin:0">维护者账号</h3>
        <el-button type="primary" plain @click="userDialog = true">添加维护者</el-button>
      </div>
      <p style="font-size:12.5px;color:var(--mp-text-secondary);margin:0 0 12px">
        所有维护者共享同一份数据，账号仅用于访问控制。
      </p>
      <div class="mp-table-wrap">
        <el-table :data="users" size="small">
          <el-table-column label="头像" width="60" align="center">
            <template #default="{ row }"><UserAvatar :user="row" :size="26" /></template>
          </el-table-column>
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
        备份含加密后的订阅地址与令牌摘要，需与服务端 data/secret.key 分开保管；恢复会覆盖全部数据。
      </p>
      <div class="mp-row-actions">
        <el-button @click="exportBackup">导出备份（JSON）</el-button>
        <el-upload :auto-upload="false" :show-file-list="false" accept=".json" :on-change="importBackup">
          <el-button type="warning" plain>从备份恢复</el-button>
        </el-upload>
      </div>
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
import { uploadCore } from '../core'
import UserAvatar from '../components/UserAvatar.vue'
import StatusDot from '../components/StatusDot.vue'

const settings = reactive({ base_url: '', session_ttl_hours: 168, profile_update_interval: 1, core_proxy: '' })
const webdav = reactive({
  enabled: false, url: '', directory: 'magicpanel', username: '',
  password: '', password_set: false, interval_hours: 12, keep: 7,
})
const webdavInfo = ref(null)
const webdavFiles = ref([])
const webdavSaving = ref(false)
const webdavTesting = ref(false)
const webdavUploading = ref(false)
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
const core = ref(null)
const coreBusy = ref(false)

const pinUsersText = computed(() => {
  const names = users.value
    .filter((u) => u.has_portal_pin)
    .map((u) => u.display_name || u.username)
  return names.length ? names.join('、') : '暂无'
})

async function load() {
  try {
    const [s, u, p, c] = await Promise.all([
      api('/api/v1/settings'), api('/api/v1/users'), api('/api/v1/portal/status'),
      api('/api/v1/core/status'),
    ])
    Object.assign(settings, {
      base_url: s.base_url || '',
      session_ttl_hours: Number(s.session_ttl_hours) || 168,
      profile_update_interval: Number(s.profile_update_interval) || 1,
      core_proxy: s.core_proxy || '',
    })
    users.value = u
    portalEnabled.value = p.enabled
    core.value = c
    // 本人 PIN 状态以 /auth/me 为准（users 列表里也有，但这里同步当前会话）
    const me = users.value.find((x) => x.username === store.user?.username)
    if (me && store.user) store.user.has_portal_pin = me.has_portal_pin
  } catch (e) {
    ElMessage.error(e.message)
  }
}
onMounted(() => {
  load()
  loadWebdav()
})

async function installCoreOnline() {
  coreBusy.value = true
  try {
    const result = await api('/api/v1/core/install', { method: 'POST' })
    ElMessage.success(`核心已安装：${result.version}`)
    core.value = await api('/api/v1/core/status')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    coreBusy.value = false
  }
}

async function onUploadCore(file) {
  coreBusy.value = true
  try {
    const result = await uploadCore(file.raw)
    ElMessage.success(`核心已安装：${result.version}`)
    core.value = await api('/api/v1/core/status')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    coreBusy.value = false
  }
}

async function savePin() {
  if (!/^\d{4}$/.test(portalPin.value)) return ElMessage.warning('PIN 必须是 4 位数字')
  savingPin.value = true
  try {
    await api('/api/v1/portal/my-pin', { method: 'POST', body: { pin: portalPin.value } })
    if (store.user) store.user.has_portal_pin = true
    portalEnabled.value = true
    portalPin.value = ''
    ElMessage.success('Magic 概览访问 PIN 已设置')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    savingPin.value = false
  }
}

async function clearPin() {
  if (!await confirmBox(
    '撤销后你的 PIN 将不能进入 Magic Panel 首页；其他维护者的 PIN 不受影响。确定继续？', '撤销访问 PIN')) return
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

async function loadWebdav() {
  try {
    const data = await api('/api/v1/backup/webdav')
    webdav.enabled = data.enabled
    webdav.url = data.url
    webdav.directory = data.directory
    webdav.username = data.username
    webdav.password_set = data.password_set
    webdav.interval_hours = Number(data.interval_hours) || 12
    webdav.keep = Number(data.keep) || 7
    webdavInfo.value = data
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function saveWebdav() {
  webdavSaving.value = true
  try {
    const values = {
      enabled: webdav.enabled ? '1' : '0',
      url: webdav.url,
      directory: webdav.directory,
      username: webdav.username,
      interval_hours: String(webdav.interval_hours),
      keep: String(webdav.keep),
    }
    // 留空表示不修改口令
    if (webdav.password) values.password = webdav.password
    await api('/api/v1/backup/webdav', { method: 'PUT', body: { values } })
    webdav.password = ''
    ElMessage.success('已保存 WebDAV 配置')
    await loadWebdav()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    webdavSaving.value = false
  }
}

async function testWebdav() {
  webdavTesting.value = true
  try {
    const r = await api('/api/v1/backup/webdav/test', { method: 'POST' })
    ElMessage.success(`连接正常：${r.detail}`)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    webdavTesting.value = false
  }
}

async function uploadWebdav() {
  webdavUploading.value = true
  try {
    const r = await api('/api/v1/backup/webdav/upload', { method: 'POST' })
    ElMessage.success(`已备份 ${r.files.length} 个文件到 WebDAV`)
    await loadWebdav()
    await loadWebdavFiles()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    webdavUploading.value = false
  }
}

async function loadWebdavFiles() {
  try {
    const r = await api('/api/v1/backup/webdav/files')
    webdavFiles.value = r.files
    if (!r.files.length) ElMessage.info('远端还没有备份文件')
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function restoreWebdav(row) {
  if (!await confirmBox(
    `确定用远端快照 “${row.name}” 覆盖当前全部数据？该操作不可撤销。`,
    '从 WebDAV 恢复', { type: 'warning' })) return
  try {
    const r = await api('/api/v1/backup/webdav/restore', {
      method: 'POST', body: { confirm: true, data: { file: row.name } },
    })
    ElMessage.success(r.key_restored
      ? '已恢复数据库与主密钥；主密钥已更换，请重启容器使密文可解密'
      : '已恢复数据库')
  } catch (e) {
    ElMessage.error(e.message)
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
  if (!await confirmBox(`删除维护者 “${row.username}”？其所有会话将失效。`, '删除维护者')) return
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

// 头像为二进制直传，不走 api() 的 JSON 封装
async function uploadAvatar(file) {
  const raw = file.raw
  if (!raw) return
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(raw.type)) {
    return ElMessage.warning('仅支持 PNG / JPEG / WebP 图片')
  }
  if (raw.size > 2 * 1024 * 1024) return ElMessage.warning('头像不能超过 2 MB')
  try {
    const resp = await fetch('/api/v1/auth/avatar', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': raw.type, 'X-CSRF-Token': store.csrf },
      body: raw,
    })
    if (!resp.ok) {
      const d = await resp.json().catch(() => ({}))
      throw new Error(d.detail || `上传失败（${resp.status}）`)
    }
    if (store.user) store.user.has_avatar = true
    store.avatarVersion += 1
    ElMessage.success('头像已更新')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeAvatar() {
  try {
    await api('/api/v1/auth/avatar', { method: 'DELETE' })
    if (store.user) store.user.has_avatar = false
    store.avatarVersion += 1
    ElMessage.success('已移除')
    await load()
  } catch (e) {
    ElMessage.error(e.message)
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
