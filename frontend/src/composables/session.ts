import { computed, reactive } from 'vue'
import { api, setCsrf } from '../api/client'

export interface User { id: string; display_name: string; username: string | null; is_admin: boolean; timezone: string; version: number }
const state = reactive<{ user: User | null; ready: boolean }>({ user: null, ready: false })

export function useSession() {
  async function load() {
    const data = await api<{ user: User | null; csrf_token: string | null }>('/session')
    state.user = data.user; state.ready = true; setCsrf(data.csrf_token)
  }
  async function guest(display_name: string) {
    const data = await api<{ user: User; csrf_token: string }>('/auth/guest', { method: 'POST', body: JSON.stringify({ display_name }) })
    state.user = data.user; setCsrf(data.csrf_token)
  }
  return { user: computed(() => state.user), ready: computed(() => state.ready), load, guest }
}

