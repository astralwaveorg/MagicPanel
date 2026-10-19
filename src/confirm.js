import { ElMessageBox } from 'element-plus'

/** 确认框；取消返回 false，不产生未处理的 Promise 拒绝。 */
export async function confirmBox(message, title, options = {}) {
  try {
    await ElMessageBox.confirm(message, title, { type: 'warning', ...options })
    return true
  } catch {
    return false
  }
}
