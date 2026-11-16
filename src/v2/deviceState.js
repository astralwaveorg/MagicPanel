export function deviceState({ expected_at, last_delivered_at, loaded_at, business_at, now }) {
  const due = Date.parse(expected_at)
  const clock = Date.parse(now)
  const delivered = Date.parse(last_delivered_at)
  return {
    delivery: (!Number.isFinite(due) || !Number.isFinite(clock)) ? 'unknown'
      : (Number.isFinite(delivered) && delivered > due ? 'delivered' : clock > due ? 'overdue' : 'within_schedule'),
    loading: loaded_at ? 'observed' : 'unknown',
    business: business_at ? 'observed' : 'unknown',
  }
}
