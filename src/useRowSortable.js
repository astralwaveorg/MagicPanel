import { nextTick } from 'vue'
import Sortable from 'sortablejs'

/** 让 Element Plus 表格的行通过左侧手柄拖动排序。 */
export function useRowSortable(tableRef, rows, onReorder) {
  let sortable = null

  async function init() {
    await nextTick()
    const el = tableRef.value?.$el?.querySelector('.el-table__body-wrapper tbody')
    if (!el) return
    if (sortable?.el === el) return
    sortable?.destroy()
    sortable = Sortable.create(el, {
      animation: 150,
      handle: '.drag-handle',
      // 触屏上必须加延迟：否则手指一按就被当成页面滚动，拖不动
      delay: 200,
      delayOnTouchOnly: true,
      touchStartThreshold: 8,
      ghostClass: 'mp-drag-ghost',
      chosenClass: 'mp-drag-chosen',
      onEnd: async () => {
        const ids = Array.from(el.querySelectorAll('tr'))
          .map((tr) => Number(tr.querySelector('.drag-handle')?.dataset.id))
          .filter((id) => Number.isInteger(id))
        if (ids.length !== rows.value.length) return
        if (ids.every((id, i) => id === rows.value[i].id)) return
        await onReorder(ids)
      },
    })
  }

  function destroy() {
    sortable?.destroy()
    sortable = null
  }

  return { init, destroy }
}
