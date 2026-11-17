/** 引用确认弹窗：四页（Sources/RuleProviders/Groups/Targets）共用的状态机。

    reactive 状态 + 打开 + 确认三件套；Targets 的改名场景需要
    choices 单选下拉，作为可选字段统一支持（2026-11-18 收拢）。
    */
import { reactive } from 'vue'

export function useRefDialog() {
  const refDialog = reactive({
    visible: false, title: '', message: '', references: [], warnings: [],
    hint: '', confirmText: '删除并解除关联', busy: false, action: null,
    choices: [], choiceLabel: '', choicePlaceholder: '请选择',
  })

  function openRefDialog({ title, message, references, warnings = [], hint,
                           action, confirmText, choices = [], choiceLabel = '',
                           choicePlaceholder = '请选择' }) {
    Object.assign(refDialog, {
      visible: true, title, message, references, warnings, hint,
      confirmText: confirmText || '删除并解除关联', busy: false, action,
      choices, choiceLabel, choicePlaceholder,
    })
  }

  async function onRefConfirm() {
    if (refDialog.action) await refDialog.action()
  }

  return { refDialog, openRefDialog, onRefConfirm }
}
