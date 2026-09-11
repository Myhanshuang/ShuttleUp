<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, setCsrf } from '../api/client'
import { useSession } from '../composables/session'
const route=useRoute(); const router=useRouter(); const session=useSession(); const summary=ref<any>(); const name=ref(''); const error=ref(''); const loading=ref(false)
onMounted(async()=>{try{summary.value=await api(`/invites/${route.params.token}`)}catch(e){error.value=e instanceof Error?e.message:'邀请无效'}})
async function join(){loading.value=true;error.value='';try{const data=await api<any>(`/invites/${route.params.token}/join`,{method:'POST',body:JSON.stringify({display_name:session.user.value?undefined:name.value})});if(data.csrf_token)setCsrf(data.csrf_token);await session.load();router.push(`/a/${data.activity.id}`)}catch(e){error.value=e instanceof Error?e.message:'加入失败'}finally{loading.value=false}}
</script>
<template><section class="shell invite-page"><article v-if="summary" class="card invite-card stack"><div><p class="eyebrow">{{ summary.host_name }} 邀请你</p><h1>{{ summary.title }}</h1><p class="muted">{{ summary.date_from }} 至 {{ summary.date_to }} · 已有 {{ summary.participant_count }} 人 · 计划 {{ summary.min_players }}–{{ summary.max_players }} 人</p></div><label v-if="!session.user.value">你的昵称<input v-model="name" autocomplete="nickname" autofocus placeholder="加入后可以升级为正式账号" /></label><p v-else>将以 <strong>{{ session.user.value.display_name }}</strong> 加入。</p><p v-if="error" class="error" role="alert">{{ error }}</p><button class="primary" :disabled="loading||(!session.user.value&&!name.trim())" @click="join">{{ loading?'正在加入…':'加入活动' }}</button></article><article v-else-if="error" class="card invite-card empty"><h1>这个邀请不可用</h1><p class="error">{{ error }}</p><RouterLink class="button" to="/">回到首页</RouterLink></article></section></template>
<style scoped>.invite-page{min-height:calc(100vh - 64px);display:grid;place-items:center;padding:24px 0 80px}.invite-card{width:min(100%,520px);padding:clamp(24px,5vw,40px)}</style>

