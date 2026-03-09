<template>
  <AppShell>
    <div class="page-head">
      <div>
        <h2>通知策略</h2>
        <p>通道和策略分开管理，列表浏览，右侧抽屉编辑。</p>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="notify-tabs">
      <el-tab-pane v-if="canViewChannels" label="通知通道" name="channels">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">通知通道</div>
                <div class="panel-tip">维护企业微信机器人、PushPlus、短信和 Webhook 通道。</div>
              </div>
              <div class="panel-actions" v-if="canManageChannels">
                <el-button type="primary" @click="openCreateChannel">新增通道</el-button>
              </div>
            </div>
          </template>

          <el-table :data="channels" stripe>
            <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
            <el-table-column label="类型" width="150">
              <template #default="{ row }">{{ channelTypeLabel(row.channel_type) }}</template>
            </el-table-column>
            <el-table-column label="地址摘要" min-width="280" show-overflow-tooltip>
              <template #default="{ row }">{{ endpointSummary(row.endpoint, row.channel_type) }}</template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="canManageChannels" label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" text @click="editChannel(row)">编辑</el-button>
                  <el-button size="small" text @click="toggleChannel(row)">
                    {{ row.is_enabled ? '停用' : '启用' }}
                  </el-button>
                  <el-button size="small" text :loading="testingChannelId === row.id" @click="testChannel(row)">测试</el-button>
                  <el-dropdown trigger="click">
                    <el-button size="small" text>更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item @click="removeChannel(row)" class="danger-item">删除</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!channels.length" description="暂无通知通道" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane v-if="canViewPolicies" label="通知策略" name="policies">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">通知策略</div>
                <div class="panel-tip">按告警级别和事件类型绑定通知通道。</div>
              </div>
              <div class="panel-actions" v-if="canManagePolicies">
                <el-button type="primary" @click="openCreatePolicy">新增策略</el-button>
              </div>
            </div>
          </template>

          <el-table :data="policies" stripe>
            <el-table-column prop="name" label="策略名称" min-width="180" show-overflow-tooltip />
            <el-table-column label="通知通道" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ channelNamesByIds(row.channel_ids, row.channel_id) }}</template>
            </el-table-column>
            <el-table-column label="最小级别" width="100">
              <template #default="{ row }">{{ row.min_alarm_level }}级</template>
            </el-table-column>
            <el-table-column label="事件类型" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">{{ eventTypesLabel(row.event_types) }}</template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="canManagePolicies" label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" text @click="editPolicy(row)">编辑</el-button>
                  <el-button size="small" text @click="togglePolicy(row)">
                    {{ row.is_enabled ? '停用' : '启用' }}
                  </el-button>
                  <el-dropdown trigger="click">
                    <el-button size="small" text>更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item @click="removePolicy(row)" class="danger-item">删除</el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!policies.length" description="暂无通知策略" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-drawer
      v-model="channelDrawerVisible"
      :title="editingChannelId ? '编辑通知通道' : '新增通知通道'"
      size="520px"
      destroy-on-close
    >
      <el-form :model="channelForm" label-width="92px" class="drawer-form">
        <el-form-item label="名称">
          <el-input v-model="channelForm.name" placeholder="例如：主群机器人" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="channelForm.channel_type" style="width: 100%">
            <el-option label="企业微信机器人" value="wechat_robot" />
            <el-option label="PushPlus" value="pushplus" />
            <el-option label="腾讯云短信" value="sms_tencent" />
            <el-option label="通用回调" value="webhook" />
          </el-select>
        </el-form-item>
        <el-form-item :label="channelForm.channel_type === 'pushplus' ? 'Token' : '地址'">
          <el-input v-model="channelForm.endpoint" type="textarea" :rows="3" :placeholder="endpointPlaceholder" />
        </el-form-item>
        <template v-if="channelForm.channel_type === 'pushplus'">
          <el-form-item label="推送渠道">
            <el-select v-model="pushplusForm.channel" style="width: 100%">
              <el-option label="微信" value="wechat" />
              <el-option label="短信" value="sms" />
              <el-option label="邮件" value="mail" />
            </el-select>
          </el-form-item>
          <el-form-item label="Topic">
            <el-input v-model="pushplusForm.topic" placeholder="可选，用于群组推送" />
          </el-form-item>
          <el-form-item label="模板">
            <el-select v-model="pushplusForm.template" style="width: 100%">
              <el-option label="纯文本" value="txt" />
              <el-option label="HTML" value="html" />
              <el-option label="Markdown" value="markdown" />
            </el-select>
          </el-form-item>
        </template>
        <el-form-item label="测试消息">
          <el-input v-model="channelTestContent" placeholder="留空则使用默认测试文案" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="channelForm.is_enabled" />
        </el-form-item>

        <el-alert
          v-if="channelForm.channel_type === 'wechat_robot'"
          type="info"
          :closable="false"
          show-icon
          title="企业微信机器人地址示例：https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
        />
        <el-alert
          v-if="channelForm.channel_type === 'pushplus'"
          type="success"
          :closable="false"
          show-icon
          title="PushPlus 填写 token，可选配置微信/短信/邮件渠道与 topic。"
        />
        <el-alert
          v-if="channelForm.channel_type === 'sms_tencent'"
          type="warning"
          :closable="false"
          show-icon
          title="腾讯云短信地址填写手机号，多个号码用逗号分隔，例如：+8613800138000,+8613900139000"
        />
      </el-form>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="closeChannelDrawer">取消</el-button>
          <el-button v-if="editingChannelId" :loading="testingChannelId === editingChannelId" @click="testCurrentChannel">测试</el-button>
          <el-button type="primary" @click="submitChannel">保存</el-button>
        </div>
      </template>
    </el-drawer>

    <el-drawer
      v-model="policyDrawerVisible"
      :title="editingPolicyId ? '编辑通知策略' : '新增通知策略'"
      size="520px"
      destroy-on-close
    >
      <el-form :model="policyForm" label-width="92px" class="drawer-form">
        <el-form-item label="策略名称">
          <el-input v-model="policyForm.name" placeholder="例如：一级告警策略" />
        </el-form-item>
        <el-form-item label="通知通道">
          <el-select v-model="policyForm.channel_ids" multiple filterable style="width: 100%">
            <el-option
              v-for="item in channels"
              :key="item.id"
              :label="`${item.name}（${channelTypeLabel(item.channel_type)}）`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="最小级别">
          <el-input-number v-model="policyForm.min_alarm_level" :min="1" :max="4" />
        </el-form-item>
        <el-form-item label="事件类型">
          <el-checkbox-group v-model="policyForm.event_type_list" class="event-group">
            <el-checkbox-button v-for="item in eventTypeOptions" :key="item.value" :label="item.value">
              {{ item.label }}
            </el-checkbox-button>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="policyForm.is_enabled" />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="closePolicyDrawer">取消</el-button>
          <el-button type="primary" @click="submitPolicy">保存</el-button>
        </div>
      </template>
    </el-drawer>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import AppShell from '../components/AppShell.vue';
import http from '../api/http';
import { useAuthStore } from '../stores/auth';

const auth = useAuthStore();
const channels = ref([]);
const policies = ref([]);
const activeTab = ref('channels');
const testingChannelId = ref(null);
const channelTestContent = ref('');
const editingChannelId = ref(null);
const editingPolicyId = ref(null);
const channelDrawerVisible = ref(false);
const policyDrawerVisible = ref(false);

const canViewChannels = computed(() => auth.hasPermission('notify.channel.view'));
const canManageChannels = computed(() => auth.hasPermission('notify.channel.manage'));
const canViewPolicies = computed(() => auth.hasPermission('notify.policy.view'));
const canManagePolicies = computed(() => auth.hasPermission('notify.policy.manage'));

const channelForm = ref(createChannelForm());
const policyForm = ref(createPolicyForm());
const pushplusForm = ref(createPushplusForm());

const eventTypeOptions = [
  { label: '触发', value: 'trigger' },
  { label: '恢复', value: 'recover' },
  { label: '确认', value: 'ack' },
  { label: '关闭', value: 'close' },
];

const eventTypeLabelMap = {
  trigger: '触发',
  recover: '恢复',
  ack: '确认',
  close: '关闭',
};

const endpointPlaceholder = computed(() =>
  channelForm.value.channel_type === 'wechat_robot'
    ? 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'
    : channelForm.value.channel_type === 'pushplus'
      ? 'PushPlus token'
    : channelForm.value.channel_type === 'sms_tencent'
      ? '+8613800138000,+8613900139000'
      : 'https://...',
);

function createChannelForm() {
  return {
    name: '',
    channel_type: 'wechat_robot',
    endpoint: '',
    secret: '',
    is_enabled: true,
  };
}

function createPushplusForm() {
  return {
    channel: 'wechat',
    topic: '',
    template: 'txt',
  };
}

function createPolicyForm() {
  return {
    name: '',
    channel_ids: [],
    min_alarm_level: 2,
    event_type_list: ['trigger', 'recover'],
    is_enabled: true,
  };
}

const channelTypeLabel = (type) => {
  if (type === 'wechat_robot') return '企业微信机器人';
  if (type === 'pushplus') return 'PushPlus';
  if (type === 'sms_tencent') return '腾讯云短信';
  if (type === 'webhook') return '通用回调';
  return '未知';
};

const channelNamesByIds = (channelIds, channelId) => {
  const ids = Array.isArray(channelIds) && channelIds.length ? channelIds : [channelId].filter(Boolean);
  if (!ids.length) return '-';
  return ids
    .map((id) => {
      const row = channels.value.find((item) => item.id === id);
      return row ? row.name : `通道#${id}`;
    })
    .join('、');
};

const endpointSummary = (endpoint, channelType) => {
  const raw = String(endpoint || '').trim();
  if (!raw) return '-';
  if (channelType === 'wechat_robot') {
    const idx = raw.indexOf('key=');
    return idx >= 0 ? `Webhook key=${raw.slice(idx + 4, idx + 12)}...` : raw;
  }
  if (channelType === 'sms_tencent') {
    return raw;
  }
  if (channelType === 'pushplus') {
    return raw.length > 12 ? `${raw.slice(0, 6)}...${raw.slice(-4)}` : raw;
  }
  return raw;
};

const eventTypesLabel = (raw) => {
  const list = Array.isArray(raw)
    ? raw
    : String(raw || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
  if (!list.length) return '-';
  return list.map((item) => eventTypeLabelMap[item] || item).join('、');
};

const loadData = async () => {
  const requests = [];
  if (canViewChannels.value) {
    requests.push(http.get('/notify/channels'));
  } else {
    requests.push(Promise.resolve({ data: [] }));
  }
  if (canViewPolicies.value) {
    requests.push(http.get('/notify/policies'));
  } else {
    requests.push(Promise.resolve({ data: [] }));
  }

  const [channelRes, policyRes] = await Promise.all(requests);
  channels.value = Array.isArray(channelRes.data) ? channelRes.data : [];
  policies.value = Array.isArray(policyRes.data) ? policyRes.data : [];

  if (!canViewChannels.value && canViewPolicies.value) {
    activeTab.value = 'policies';
  }
};

const resetChannelForm = () => {
  editingChannelId.value = null;
  channelTestContent.value = '';
  channelForm.value = createChannelForm();
  pushplusForm.value = createPushplusForm();
};

const resetPolicyForm = () => {
  editingPolicyId.value = null;
  policyForm.value = createPolicyForm();
};

const openCreateChannel = () => {
  resetChannelForm();
  channelDrawerVisible.value = true;
};

const closeChannelDrawer = () => {
  channelDrawerVisible.value = false;
  resetChannelForm();
};

const openCreatePolicy = () => {
  resetPolicyForm();
  policyDrawerVisible.value = true;
};

const closePolicyDrawer = () => {
  policyDrawerVisible.value = false;
  resetPolicyForm();
};

const buildPushplusSecret = () =>
  JSON.stringify(
    {
      channel: pushplusForm.value.channel || 'wechat',
      topic: String(pushplusForm.value.topic || '').trim(),
      template: pushplusForm.value.template || 'txt',
    },
  );

const parsePushplusSecret = (raw) => {
  try {
    const parsed = JSON.parse(raw || '{}');
    return {
      channel: parsed.channel || 'wechat',
      topic: parsed.topic || '',
      template: parsed.template || 'txt',
    };
  } catch (_e) {
    return createPushplusForm();
  }
};

const submitChannel = async () => {
  if (!canManageChannels.value) {
    ElMessage.error('无权管理通知通道');
    return;
  }
  if (!channelForm.value.name || !channelForm.value.endpoint) {
    ElMessage.warning('请填写通道名称和地址');
    return;
  }
  if (channelForm.value.channel_type === 'wechat_robot') {
    const endpoint = String(channelForm.value.endpoint || '');
    if (!endpoint.startsWith('https://qyapi.weixin.qq.com/cgi-bin/webhook/send') || !endpoint.includes('key=')) {
      ElMessage.warning('企业微信机器人地址格式不正确');
      return;
    }
  }
  if (channelForm.value.channel_type === 'sms_tencent') {
    const phones = String(channelForm.value.endpoint || '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (!phones.length) {
      ElMessage.warning('请填写至少一个手机号');
      return;
    }
    const invalid = phones.filter((s) => !/^\+?\d{6,20}$/.test(s.replace(/\s|-/g, '')));
    if (invalid.length) {
      ElMessage.warning('手机号格式不正确，请检查');
      return;
    }
  }
  if (channelForm.value.channel_type === 'pushplus') {
    if (String(channelForm.value.endpoint || '').trim().length < 16) {
      ElMessage.warning('请填写有效的 PushPlus token');
      return;
    }
  }
  try {
    const payload = {
      ...channelForm.value,
      secret: channelForm.value.channel_type === 'pushplus' ? buildPushplusSecret() : channelForm.value.secret,
    };
    if (editingChannelId.value) {
      await http.put(`/notify/channels/${editingChannelId.value}`, payload);
      ElMessage.success('通道保存成功');
    } else {
      await http.post('/notify/channels', payload);
      ElMessage.success('通道创建成功');
    }
    closeChannelDrawer();
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '通道保存失败');
  }
};

const submitPolicy = async () => {
  if (!canManagePolicies.value) {
    ElMessage.error('无权管理通知策略');
    return;
  }
  if (!policyForm.value.name || !policyForm.value.channel_ids.length) {
    ElMessage.warning('请填写策略名称并选择至少一个通知通道');
    return;
  }
  if (!policyForm.value.event_type_list.length) {
    ElMessage.warning('请至少选择一种事件类型');
    return;
  }
  try {
    const payload = {
      name: policyForm.value.name,
      channel_id: policyForm.value.channel_ids[0],
      channel_ids: policyForm.value.channel_ids,
      min_alarm_level: policyForm.value.min_alarm_level,
      event_types: policyForm.value.event_type_list.join(','),
      is_enabled: policyForm.value.is_enabled,
    };
    if (editingPolicyId.value) {
      await http.put(`/notify/policies/${editingPolicyId.value}`, payload);
      ElMessage.success('策略保存成功');
    } else {
      await http.post('/notify/policies', payload);
      ElMessage.success('策略创建成功');
    }
    closePolicyDrawer();
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '策略保存失败');
  }
};

const editChannel = (row) => {
  if (!canManageChannels.value) return;
  editingChannelId.value = row.id;
  pushplusForm.value = row.channel_type === 'pushplus' ? parsePushplusSecret(row.secret) : createPushplusForm();
  channelForm.value = {
    name: row.name,
    channel_type: row.channel_type,
    endpoint: row.endpoint,
    secret: row.secret || '',
    is_enabled: row.is_enabled,
  };
  channelDrawerVisible.value = true;
};

const editPolicy = (row) => {
  if (!canManagePolicies.value) return;
  editingPolicyId.value = row.id;
  policyForm.value = {
    name: row.name,
    channel_ids: Array.isArray(row.channel_ids) && row.channel_ids.length ? row.channel_ids : [row.channel_id].filter(Boolean),
    min_alarm_level: row.min_alarm_level,
    event_type_list: String(row.event_types || '')
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    is_enabled: row.is_enabled,
  };
  policyDrawerVisible.value = true;
};

const toggleChannel = async (row) => {
  if (!canManageChannels.value) {
    ElMessage.error('无权管理通知通道');
    return;
  }
  try {
    await http.put(`/notify/channels/${row.id}`, {
      name: row.name,
      channel_type: row.channel_type,
      endpoint: row.endpoint,
      secret: row.secret || '',
      is_enabled: !row.is_enabled,
    });
    ElMessage.success(`通道已${row.is_enabled ? '停用' : '启用'}`);
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '通道状态更新失败');
  }
};

const togglePolicy = async (row) => {
  if (!canManagePolicies.value) {
    ElMessage.error('无权管理通知策略');
    return;
  }
  try {
    await http.put(`/notify/policies/${row.id}`, {
      name: row.name,
      channel_id: Array.isArray(row.channel_ids) && row.channel_ids.length ? row.channel_ids[0] : row.channel_id,
      channel_ids: Array.isArray(row.channel_ids) && row.channel_ids.length ? row.channel_ids : [row.channel_id].filter(Boolean),
      min_alarm_level: row.min_alarm_level,
      event_types: row.event_types,
      is_enabled: !row.is_enabled,
    });
    ElMessage.success(`策略已${row.is_enabled ? '停用' : '启用'}`);
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '策略状态更新失败');
  }
};

const removeChannel = async (row) => {
  if (!canManageChannels.value) {
    ElMessage.error('无权管理通知通道');
    return;
  }
  try {
    await ElMessageBox.confirm(`确认删除通知通道“${row.name}”吗？`, '删除确认', { type: 'warning' });
    await http.delete(`/notify/channels/${row.id}`);
    ElMessage.success('通道已删除');
    await loadData();
  } catch (e) {
    if (e === 'cancel' || e === 'close') return;
    ElMessage.error(e?.response?.data?.detail || '通道删除失败');
  }
};

const removePolicy = async (row) => {
  if (!canManagePolicies.value) {
    ElMessage.error('无权管理通知策略');
    return;
  }
  try {
    await ElMessageBox.confirm(`确认删除通知策略“${row.name}”吗？`, '删除确认', { type: 'warning' });
    await http.delete(`/notify/policies/${row.id}`);
    ElMessage.success('策略已删除');
    await loadData();
  } catch (e) {
    if (e === 'cancel' || e === 'close') return;
    ElMessage.error(e?.response?.data?.detail || '策略删除失败');
  }
};

const testChannel = async (row) => {
  if (!canManageChannels.value) {
    ElMessage.error('无权测试通知通道');
    return;
  }
  testingChannelId.value = row.id;
  try {
    const payload = {};
    const content = String(channelTestContent.value || '').trim();
    if (content) payload.content = content;
    const res = await http.post(`/notify/channels/${row.id}/test`, payload);
    ElMessage.success(res?.data?.detail || '测试发送成功');
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '测试发送失败');
  } finally {
    testingChannelId.value = null;
  }
};

const testCurrentChannel = async () => {
  if (!editingChannelId.value) {
    ElMessage.warning('请先保存通道后再测试');
    return;
  }
  const row = channels.value.find((item) => item.id === editingChannelId.value);
  if (!row) {
    ElMessage.warning('请先保存通道后再测试');
    return;
  }
  await testChannel(row);
};

onMounted(async () => {
  try {
    await loadData();
  } catch (_e) {
    ElMessage.error('加载通知配置失败');
  }
});
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.page-head h2 {
  margin: 0;
}

.page-head p {
  margin: 6px 0 0;
  color: #64748b;
}

.notify-tabs {
  margin-top: 12px;
}

.panel-card {
  border-radius: 16px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.panel-tip {
  margin-top: 4px;
  color: #64748b;
  font-size: 13px;
}

.panel-actions,
.row-actions,
.drawer-footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.row-actions {
  flex-wrap: wrap;
}

.drawer-form {
  padding-right: 12px;
}

.event-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

:deep(.danger-item) {
  color: #dc2626;
}

@media (max-width: 900px) {
  .page-head,
  .panel-head {
    flex-direction: column;
    align-items: stretch;
  }

  .panel-actions {
    justify-content: flex-end;
  }
}
</style>
