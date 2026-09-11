export function money(cents: number | null | undefined) { return cents == null ? '价格待确认' : `¥${(cents / 100).toFixed(2)}` }
export function shortDate(iso: string) { return new Intl.DateTimeFormat('zh-CN', { weekday: 'short', month: 'numeric', day: 'numeric' }).format(new Date(iso)) }
export function shortTime(iso: string) { return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso)) }

