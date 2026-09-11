<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useSession } from './composables/session'
const session = useSession()
onMounted(() => session.load())
</script>

<template>
  <header class="shell topbar">
    <RouterLink class="brand" to="/">ShuttleUp</RouterLink>
    <nav class="nav" aria-label="主导航">
      <RouterLink class="hide-mobile" to="/me/time">我的时间</RouterLink>
      <RouterLink to="/me">{{ session.user.value?.display_name || '登录' }}</RouterLink>
    </nav>
  </header>
  <main><RouterView /></main>
</template>

