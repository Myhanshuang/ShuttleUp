<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useSession } from '../composables/session'
const session = useSession(); const router = useRouter()
const name = ref(''); const title = ref('周末打球'); const error = ref('')
async function start() {
  try {
    if (!session.user.value) await session.guest(name.value)
    const activity = await api<{id: string}>('/activities', { method: 'POST', body: JSON.stringify({ title: title.value }) })
    router.push(`/a/${activity.id}`)
  } catch (e) { error.value = e instanceof Error ? e.message : '操作失败' }
}
</script>

<template>
  <section class="shell page">
    <div class="page-head">
      <div><p class="eyebrow">今天要做什么</p><h1>把下一场球约起来</h1><p class="muted">先定大家都有空的时间，再去订场；打完后账也在这里结清。</p></div>
      <button class="primary" @click="start">发起约球</button>
    </div>
    <div class="grid">
      <article class="card stack">
        <h2>发起一场活动</h2>
        <label v-if="!session.user.value">你的昵称<input v-model="name" autocomplete="nickname" placeholder="例如：小林" /></label>
        <label>活动标题<input v-model="title" maxlength="80" /></label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button class="primary" @click="start">继续设置时间与场馆</button>
      </article>
      <article class="card empty">
        <h2>还没有进行中的活动</h2>
        <p class="muted">收到邀请链接后，活动也会出现在这里。</p>
      </article>
    </div>
  </section>
</template>

