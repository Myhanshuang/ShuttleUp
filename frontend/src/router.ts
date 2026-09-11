import { createRouter, createWebHistory } from 'vue-router'
import HomePage from './pages/HomePage.vue'
const ActivityPage = () => import('./pages/ActivityPage.vue')
const TimePage = () => import('./pages/TimePage.vue')
const BillPage = () => import('./pages/BillPage.vue')
const ProfilePage = () => import('./pages/ProfilePage.vue')
const InvitePage = () => import('./pages/InvitePage.vue')

export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', component: HomePage },
  { path: '/a/:id', component: ActivityPage },
  { path: '/a/:id/bill', component: BillPage },
  { path: '/i/:token', component: InvitePage },
  { path: '/me/time', component: TimePage },
  { path: '/me', component: ProfilePage },
] })
