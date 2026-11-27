import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import CalibrationView from '@/views/CalibrationView.vue'
import ApprovalDetailView from '@/views/ApprovalDetailView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    {
      path: '/calibration',
      name: 'calibration',
      component: CalibrationView,
      alias: ['/calibration/approvals', '/calibration-approvals', '/probe-calibration'],
    },
    {
      path: '/calibration/approvals/:approvalId',
      name: 'calibration-approval-detail',
      component: ApprovalDetailView,
      props: true,
    },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
