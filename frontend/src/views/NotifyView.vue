
<template>
  <AppShell>
    <div class="page-head">
      <div>
        <h2>通知管理</h2>
        <p>统一维护通知通道、通知策略，以及公司级接收人、通知组和推送规则。</p>
      </div>
    </div>

    <el-card v-if="hasTenantScopedTabs" shadow="never" class="tenant-card">
      <div class="tenant-head">
        <div>
          <div class="panel-title">当前公司</div>
          <div class="panel-tip">公司级接收人、通知组和推送规则都按公司隔离管理。</div>
        </div>
        <el-select v-model="activeTenantCode" filterable placeholder="选择公司" style="width: 280px" @change="loadTenantScopedData">
          <el-option v-for="item in tenantOptions" :key="item.code" :label="`${item.name}（${item.code}）`" :value="item.code" />
        </el-select>
      </div>
    </el-card>

    <el-tabs v-model="activeTab" class="notify-tabs">
      <el-tab-pane v-if="canViewChannels" label="通知通道" name="channels">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">通知通道</div>
                <div class="panel-tip">维护企业微信机器人、PushPlus、短信和 Webhook 通道。</div>
              </div>
              <el-button v-if="canManageChannels" type="primary" @click="openCreateChannel">新增通道</el-button>
            </div>
          </template>
          <el-table :data="channels" stripe>
            <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
            <el-table-column label="类型" width="150"><template #default="{ row }">{{ channelTypeLabel(row.channel_type) }}</template></el-table-column>
            <el-table-column label="地址摘要" min-width="280" show-overflow-tooltip><template #default="{ row }">{{ endpointSummary(row.endpoint, row.channel_type) }}</template></el-table-column>
            <el-table-column label="启用" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column v-if="canManageChannels" label="操作" width="260" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" text @click="editChannel(row)">编辑</el-button>
                  <el-button size="small" text @click="toggleChannel(row)">{{ row.is_enabled ? '停用' : '启用' }}</el-button>
                  <el-button size="small" text :loading="testingChannelId === row.id" @click="testChannel(row)">测试</el-button>
                  <el-dropdown trigger="click">
                    <el-button size="small" text>更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item class="danger-item" @click="removeChannel(row)">删除</el-dropdown-item>
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
              <el-button v-if="canManagePolicies" type="primary" @click="openCreatePolicy">新增策略</el-button>
            </div>
          </template>
          <el-table :data="policies" stripe>
            <el-table-column prop="name" label="策略名称" min-width="180" show-overflow-tooltip />
            <el-table-column label="通知通道" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ channelNamesByIds(row.channel_ids, row.channel_id) }}</template></el-table-column>
            <el-table-column label="最小级别" width="100"><template #default="{ row }">{{ row.min_alarm_level }}级</template></el-table-column>
            <el-table-column label="事件类型" min-width="180"><template #default="{ row }">{{ eventTypesLabel(row.event_types) }}</template></el-table-column>
            <el-table-column label="启用" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column v-if="canManagePolicies" label="操作" width="220" fixed="right">
              <template #default="{ row }">
                <div class="row-actions">
                  <el-button size="small" text @click="editPolicy(row)">编辑</el-button>
                  <el-button size="small" text @click="togglePolicy(row)">{{ row.is_enabled ? '停用' : '启用' }}</el-button>
                  <el-dropdown trigger="click">
                    <el-button size="small" text>更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item class="danger-item" @click="removePolicy(row)">删除</el-dropdown-item>
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

      <el-tab-pane v-if="canViewReceivers" label="通知接收人" name="receivers">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">通知接收人</div>
                <div class="panel-tip">维护公司级手机号、系统用户、PushPlus 等接收对象。</div>
              </div>
              <el-button v-if="canManageReceivers" type="primary" :disabled="!activeTenantCode" @click="openCreateReceiver">新增接收人</el-button>
            </div>
          </template>
          <el-table :data="receivers" stripe>
            <el-table-column prop="name" label="名称" min-width="160" />
            <el-table-column label="类型" width="120"><template #default="{ row }">{{ receiverTypeLabel(row.receiver_type) }}</template></el-table-column>
            <el-table-column label="接收目标" min-width="240" show-overflow-tooltip><template #default="{ row }">{{ receiverTarget(row) }}</template></el-table-column>
            <el-table-column label="启用" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column v-if="canManageReceivers" label="操作" width="180" fixed="right">
              <template #default="{ row }"><div class="row-actions"><el-button size="small" text @click="editReceiver(row)">编辑</el-button><el-button size="small" text type="danger" @click="removeReceiver(row)">删除</el-button></div></template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!receivers.length" description="暂无通知接收人" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane v-if="canViewGroups" label="通知组" name="groups">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">通知组</div>
                <div class="panel-tip">把接收人组合成值班班组、专业组、升级组。</div>
              </div>
              <el-button v-if="canManageGroups" type="primary" :disabled="!activeTenantCode" @click="openCreateGroup">新增通知组</el-button>
            </div>
          </template>
          <el-table :data="groups" stripe>
            <el-table-column prop="name" label="名称" min-width="180" />
            <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
            <el-table-column prop="member_count" label="成员数" width="90" />
            <el-table-column label="成员摘要" min-width="260" show-overflow-tooltip><template #default="{ row }">{{ (row.member_names || []).join('、') || '-' }}</template></el-table-column>
            <el-table-column label="启用" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column v-if="canManageGroups" label="操作" width="180" fixed="right">
              <template #default="{ row }"><div class="row-actions"><el-button size="small" text @click="editGroup(row)">编辑</el-button><el-button size="small" text type="danger" @click="removeGroup(row)">删除</el-button></div></template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!groups.length" description="暂无通知组" />
        </el-card>
      </el-tab-pane>
      <el-tab-pane v-if="canViewRules" label="推送规则" name="rules">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">推送规则</div>
                <div class="panel-tip">按公司、项目、站点、设备组或自定义范围管理告警推送。</div>
              </div>
              <el-button v-if="canManageRules" type="primary" :disabled="!activeTenantCode" @click="openCreateRule">新增规则</el-button>
            </div>
          </template>
          <el-table :data="rules" stripe>
            <el-table-column prop="name" label="规则名称" min-width="180" />
            <el-table-column label="作用范围" min-width="180"><template #default="{ row }">{{ ruleScopeLabel(row) }}</template></el-table-column>
            <el-table-column label="通知组" min-width="160"><template #default="{ row }">{{ groupNameById(row.notify_group_id) }}</template></el-table-column>
            <el-table-column label="最低级别" width="90"><template #default="{ row }">{{ row.alarm_level_min }}级</template></el-table-column>
            <el-table-column label="事件类型" min-width="180"><template #default="{ row }">{{ (row.event_types || []).map(eventTypeName).join('、') || '-' }}</template></el-table-column>
            <el-table-column label="推送渠道" min-width="180"><template #default="{ row }">{{ (row.channel_types || []).map(notifyMediumLabel).join('、') || '-' }}</template></el-table-column>
            <el-table-column label="启用" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column v-if="canManageRules" label="操作" width="180" fixed="right">
              <template #default="{ row }"><div class="row-actions"><el-button size="small" text @click="editRule(row)">编辑</el-button><el-button size="small" text type="danger" @click="removeRule(row)">删除</el-button></div></template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!rules.length" description="暂无推送规则" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane v-if="canViewOncall" label="值班表" name="oncall">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">值班表</div>
                <div class="panel-tip">按公司范围维护当前值班成员和值班顺位。</div>
              </div>
              <el-button v-if="canManageOncall" type="primary" :disabled="!activeTenantCode" @click="openCreateOncall">新增值班表</el-button>
            </div>
          </template>
          <el-table :data="oncallSchedules" stripe>
            <el-table-column prop="name" label="值班表名称" min-width="180" />
            <el-table-column label="作用范围" min-width="180"><template #default="{ row }">{{ oncallScopeLabel(row) }}</template></el-table-column>
            <el-table-column prop="timezone_name" label="时区" width="140" />
            <el-table-column prop="member_count" label="成员数" width="90" />
            <el-table-column label="成员摘要" min-width="240" show-overflow-tooltip><template #default="{ row }">{{ (row.member_names || []).join('、') || '-' }}</template></el-table-column>
            <el-table-column label="启用" width="90"><template #default="{ row }"><el-tag :type="row.is_enabled ? 'success' : 'info'">{{ row.is_enabled ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column v-if="canManageOncall" label="操作" width="180" fixed="right">
              <template #default="{ row }"><div class="row-actions"><el-button size="small" text @click="editOncall(row)">编辑</el-button><el-button size="small" text type="danger" @click="removeOncall(row)">删除</el-button></div></template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!oncallSchedules.length" description="暂无值班表" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane v-if="canViewPushLogs" label="推送日志" name="pushLogs">
        <el-card shadow="never" class="panel-card">
          <template #header>
            <div class="panel-head">
              <div>
                <div class="panel-title">推送日志</div>
                <div class="panel-tip">查看告警推送结果，并对失败记录执行重发。</div>
              </div>
              <el-button text @click="loadTenantScopedData">刷新</el-button>
            </div>
          </template>
          <el-table :data="pushLogs" stripe>
            <el-table-column prop="pushed_at" label="时间" min-width="170" show-overflow-tooltip />
            <el-table-column prop="policy_name" label="策略" min-width="150" show-overflow-tooltip />
            <el-table-column prop="channel_name" label="通道" min-width="150" show-overflow-tooltip />
            <el-table-column label="类型" width="110"><template #default="{ row }">{{ notifyMediumLabel(row.channel_type) }}</template></el-table-column>
            <el-table-column prop="target" label="目标" min-width="180" show-overflow-tooltip />
            <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.push_status === 'SUCCESS' ? 'success' : 'danger'">{{ pushLogStatusLabel(row.push_status) }}</el-tag></template></el-table-column>
            <el-table-column prop="retry_count" label="重试次数" width="100" />
            <el-table-column prop="error_message" label="错误信息" min-width="220" show-overflow-tooltip />
            <el-table-column v-if="canRetryPushLogs" label="操作" width="120" fixed="right">
              <template #default="{ row }"><el-button size="small" text :disabled="row.push_status === 'SUCCESS'" @click="retryPushLog(row)">重发</el-button></template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!pushLogs.length" description="暂无推送日志" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-drawer v-model="channelDrawerVisible" :title="editingChannelId ? '编辑通知通道' : '新增通知通道'" size="520px" destroy-on-close>
      <el-form :model="channelForm" label-width="92px" class="drawer-form">
        <el-form-item label="名称"><el-input v-model="channelForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="channelForm.channel_type" style="width: 100%">
            <el-option label="企业微信机器人" value="wechat_robot" />
            <el-option label="PushPlus" value="pushplus" />
            <el-option label="腾讯云短信" value="sms_tencent" />
            <el-option label="通用回调" value="webhook" />
          </el-select>
        </el-form-item>
        <el-form-item :label="channelForm.channel_type === 'pushplus' ? 'Token' : '地址'"><el-input v-model="channelForm.endpoint" type="textarea" :rows="3" :placeholder="endpointPlaceholder" /></el-form-item>
        <template v-if="channelForm.channel_type === 'pushplus'">
          <el-form-item label="推送渠道"><el-select v-model="pushplusForm.channel" style="width: 100%"><el-option label="微信" value="wechat" /><el-option label="短信" value="sms" /><el-option label="邮件" value="mail" /></el-select></el-form-item>
          <el-form-item label="Topic"><el-input v-model="pushplusForm.topic" /></el-form-item>
          <el-form-item label="模板"><el-select v-model="pushplusForm.template" style="width: 100%"><el-option label="HTML" value="html" /><el-option label="纯文本" value="txt" /><el-option label="Markdown" value="markdown" /></el-select></el-form-item>
        </template>
        <el-form-item label="测试消息"><el-input v-model="channelTestContent" placeholder="留空则发送示例告警内容" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="channelForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer><div class="drawer-footer"><el-button @click="closeChannelDrawer">取消</el-button><el-button v-if="editingChannelId" :loading="testingChannelId === editingChannelId" @click="testCurrentChannel">测试</el-button><el-button type="primary" @click="submitChannel">保存</el-button></div></template>
    </el-drawer>

    <el-drawer v-model="policyDrawerVisible" :title="editingPolicyId ? '编辑通知策略' : '新增通知策略'" size="520px" destroy-on-close>
      <el-form :model="policyForm" label-width="92px" class="drawer-form">
        <el-form-item label="策略名称"><el-input v-model="policyForm.name" /></el-form-item>
        <el-form-item label="通知通道"><el-select v-model="policyForm.channel_ids" multiple filterable style="width: 100%"><el-option v-for="item in channels" :key="item.id" :label="`${item.name}（${channelTypeLabel(item.channel_type)}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="最小级别"><el-input-number v-model="policyForm.min_alarm_level" :min="1" :max="4" /></el-form-item>
        <el-form-item label="事件类型"><el-checkbox-group v-model="policyForm.event_type_list" class="event-group"><el-checkbox-button v-for="item in eventTypeOptions" :key="item.value" :label="item.value">{{ item.label }}</el-checkbox-button></el-checkbox-group></el-form-item>
        <el-form-item label="启用"><el-switch v-model="policyForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer><div class="drawer-footer"><el-button @click="closePolicyDrawer">取消</el-button><el-button type="primary" @click="submitPolicy">保存</el-button></div></template>
    </el-drawer>

    <el-drawer v-model="receiverDrawerVisible" :title="editingReceiverId ? '编辑接收人' : '新增接收人'" size="520px" destroy-on-close>
      <el-form :model="receiverForm" label-width="92px" class="drawer-form">
        <el-form-item label="名称"><el-input v-model="receiverForm.name" /></el-form-item>
        <el-form-item label="类型"><el-select v-model="receiverForm.receiver_type" style="width: 100%"><el-option label="系统用户" value="USER" /><el-option label="手机号" value="PHONE" /><el-option label="企业微信" value="WECHAT" /><el-option label="邮箱" value="EMAIL" /><el-option label="PushPlus" value="PUSHPLUS" /></el-select></el-form-item>
        <el-form-item v-if="receiverForm.receiver_type === 'PHONE'" label="手机号"><el-input v-model="receiverForm.mobile" /></el-form-item>
        <el-form-item v-if="receiverForm.receiver_type === 'WECHAT'" label="OpenID"><el-input v-model="receiverForm.wechat_openid" /></el-form-item>
        <el-form-item v-if="receiverForm.receiver_type === 'EMAIL'" label="邮箱"><el-input v-model="receiverForm.email" /></el-form-item>
        <el-form-item v-if="receiverForm.receiver_type === 'PUSHPLUS'" label="Token"><el-input v-model="receiverForm.pushplus_token" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="receiverForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer><div class="drawer-footer"><el-button @click="closeReceiverDrawer">取消</el-button><el-button type="primary" @click="submitReceiver">保存</el-button></div></template>
    </el-drawer>

    <el-drawer v-model="groupDrawerVisible" :title="editingGroupId ? '编辑通知组' : '新增通知组'" size="560px" destroy-on-close>
      <el-form :model="groupForm" label-width="92px" class="drawer-form">
        <el-form-item label="名称"><el-input v-model="groupForm.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="groupForm.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="成员"><el-select v-model="groupForm.member_ids" multiple filterable style="width: 100%"><el-option v-for="item in receivers" :key="item.id" :label="`${item.name}（${receiverTypeLabel(item.receiver_type)}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="启用"><el-switch v-model="groupForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer><div class="drawer-footer"><el-button @click="closeGroupDrawer">取消</el-button><el-button type="primary" @click="submitGroup">保存</el-button></div></template>
    </el-drawer>

    <el-drawer v-model="ruleDrawerVisible" :title="editingRuleId ? '编辑推送规则' : '新增推送规则'" size="620px" destroy-on-close>
      <el-form :model="ruleForm" label-width="96px" class="drawer-form">
        <el-form-item label="规则名称"><el-input v-model="ruleForm.name" /></el-form-item>
        <el-form-item label="最低级别"><el-input-number v-model="ruleForm.alarm_level_min" :min="1" :max="4" /></el-form-item>
        <el-form-item label="事件类型"><el-checkbox-group v-model="ruleForm.event_types" class="event-group"><el-checkbox-button v-for="item in eventTypeOptions" :key="item.value" :label="item.value">{{ item.label }}</el-checkbox-button></el-checkbox-group></el-form-item>
        <el-form-item label="推送渠道"><el-checkbox-group v-model="ruleForm.channel_types" class="event-group"><el-checkbox-button v-for="item in channelTypeOptions" :key="item.value" :label="item.value">{{ item.label }}</el-checkbox-button></el-checkbox-group></el-form-item>
        <el-form-item label="通知组"><el-select v-model="ruleForm.notify_group_id" clearable filterable style="width: 100%"><el-option v-for="item in groups" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="作用范围"><el-select v-model="ruleForm.scope_type" style="width: 100%"><el-option label="本公司" value="TENANT" /><el-option label="项目" value="PROJECT" /><el-option label="站点" value="SITE" /><el-option label="设备组" value="DEVICE_GROUP" /><el-option label="自定义范围" value="CUSTOM" /></el-select></el-form-item>
        <el-form-item v-if="ruleForm.scope_type === 'PROJECT'" label="项目"><el-select v-model="ruleForm.project_id" filterable clearable style="width: 100%"><el-option v-for="item in projectOptions" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item v-if="ruleForm.scope_type === 'SITE'" label="站点"><el-select v-model="ruleForm.site_id" filterable clearable style="width: 100%"><el-option v-for="item in siteOptions" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item v-if="ruleForm.scope_type === 'DEVICE_GROUP'" label="设备组"><el-select v-model="ruleForm.device_group_id" filterable clearable style="width: 100%"><el-option v-for="item in deviceGroupOptions" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item v-if="ruleForm.scope_type === 'CUSTOM'" label="自定义范围"><el-select v-model="ruleForm.custom_scope_set_id" filterable clearable style="width: 100%"><el-option v-for="item in customScopeOptions" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="正文模板"><el-input v-model="ruleForm.content_template" type="textarea" :rows="4" placeholder="可选。留空则使用系统默认告警摘要模板。" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="ruleForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer><div class="drawer-footer"><el-button @click="closeRuleDrawer">取消</el-button><el-button type="primary" @click="submitRule">保存</el-button></div></template>
    </el-drawer>

    <el-drawer v-model="oncallDrawerVisible" :title="editingOncallId ? '编辑值班表' : '新增值班表'" size="620px" destroy-on-close>
      <el-form :model="oncallForm" label-width="96px" class="drawer-form">
        <el-form-item label="名称"><el-input v-model="oncallForm.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="oncallForm.description" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="时区"><el-input v-model="oncallForm.timezone_name" /></el-form-item>
        <el-form-item label="作用范围"><el-select v-model="oncallForm.scope_type" style="width: 100%"><el-option label="本公司" value="TENANT" /><el-option label="项目" value="PROJECT" /><el-option label="站点" value="SITE" /><el-option label="设备组" value="DEVICE_GROUP" /><el-option label="自定义范围" value="CUSTOM" /></el-select></el-form-item>
        <el-form-item v-if="oncallForm.scope_type === 'PROJECT'" label="项目"><el-select v-model="oncallForm.project_id" filterable clearable style="width: 100%"><el-option v-for="item in projectOptions" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item v-if="oncallForm.scope_type === 'SITE'" label="站点"><el-select v-model="oncallForm.site_id" filterable clearable style="width: 100%"><el-option v-for="item in siteOptions" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item v-if="oncallForm.scope_type === 'DEVICE_GROUP'" label="设备组"><el-select v-model="oncallForm.device_group_id" filterable clearable style="width: 100%"><el-option v-for="item in deviceGroupOptions" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item v-if="oncallForm.scope_type === 'CUSTOM'" label="自定义范围"><el-select v-model="oncallForm.custom_scope_set_id" filterable clearable style="width: 100%"><el-option v-for="item in customScopeOptions" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="值班成员"><el-select v-model="oncallForm.member_ids" multiple filterable style="width: 100%"><el-option v-for="item in receivers" :key="item.id" :label="`${item.name}（${receiverTypeLabel(item.receiver_type)}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="启用"><el-switch v-model="oncallForm.is_enabled" /></el-form-item>
      </el-form>
      <template #footer><div class="drawer-footer"><el-button @click="closeOncallDrawer">取消</el-button><el-button type="primary" @click="submitOncall">保存</el-button></div></template>
    </el-drawer>
  </AppShell>
</template>
<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();

const activeTab = ref("channels");
const tenantOptions = ref([]);
const activeTenantCode = ref("");
const channels = ref([]);
const policies = ref([]);
const receivers = ref([]);
const groups = ref([]);
const rules = ref([]);
const oncallSchedules = ref([]);
const pushLogs = ref([]);
const projectOptions = ref([]);
const siteOptions = ref([]);
const deviceGroupOptions = ref([]);
const customScopeOptions = ref([]);
const channelDrawerVisible = ref(false);
const policyDrawerVisible = ref(false);
const receiverDrawerVisible = ref(false);
const groupDrawerVisible = ref(false);
const ruleDrawerVisible = ref(false);
const oncallDrawerVisible = ref(false);
const editingChannelId = ref(null);
const editingPolicyId = ref(null);
const editingReceiverId = ref(null);
const editingGroupId = ref(null);
const editingRuleId = ref(null);
const editingOncallId = ref(null);
const testingChannelId = ref(null);
const channelTestContent = ref("");

const canViewChannels = computed(() => auth.hasPermission("notify.channel.view"));
const canManageChannels = computed(() => auth.hasPermission("notify.channel.manage"));
const canViewPolicies = computed(() => auth.hasPermission("notify.policy.view"));
const canManagePolicies = computed(() => auth.hasPermission("notify.policy.manage"));
const canViewReceivers = computed(() => auth.hasPermission("notify.receiver.view"));
const canManageReceivers = computed(() => auth.hasPermission("notify.receiver.manage"));
const canViewGroups = computed(() => auth.hasPermission("notify.group.view"));
const canManageGroups = computed(() => auth.hasPermission("notify.group.manage"));
const canViewRules = computed(() => auth.hasPermission("notify.rule.view"));
const canManageRules = computed(() => auth.hasPermission("notify.rule.manage"));
const canViewOncall = computed(() => auth.hasPermission("notify.oncall.view"));
const canManageOncall = computed(() => auth.hasPermission("notify.oncall.manage"));
const canViewPushLogs = computed(() => auth.hasPermission("notify.push_log.view"));
const canRetryPushLogs = computed(() => auth.hasPermission("notify.push_log.retry"));
const hasTenantScopedTabs = computed(() => canViewReceivers.value || canViewGroups.value || canViewRules.value || canViewOncall.value || canViewPushLogs.value);

const eventTypeOptions = [
  { label: "触发", value: "trigger" },
  { label: "恢复", value: "recover" },
  { label: "确认", value: "ack" },
  { label: "关闭", value: "close" },
];
const channelTypeOptions = [
  { label: "企业微信", value: "wechat" },
  { label: "短信", value: "sms" },
  { label: "PushPlus", value: "pushplus" },
  { label: "邮件", value: "email" },
  { label: "Webhook", value: "webhook" },
];

const channelForm = ref(createChannelForm());
const pushplusForm = ref(createPushplusForm());
const policyForm = ref(createPolicyForm());
const receiverForm = ref(createReceiverForm());
const groupForm = ref(createGroupForm());
const ruleForm = ref(createRuleForm());
const oncallForm = ref(createOncallForm());

const endpointPlaceholder = computed(() => {
  if (channelForm.value.channel_type === "wechat_robot") return "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...";
  if (channelForm.value.channel_type === "pushplus") return "PushPlus token";
  if (channelForm.value.channel_type === "sms_tencent") return "+8613800138000,+8613900139000";
  return "https://...";
});

function createChannelForm() { return { name: "", channel_type: "wechat_robot", endpoint: "", secret: "", is_enabled: true }; }
function createPushplusForm() { return { channel: "wechat", topic: "", template: "html" }; }
function createPolicyForm() { return { name: "", channel_ids: [], min_alarm_level: 2, event_type_list: ["trigger", "recover"], is_enabled: true }; }
function createReceiverForm() { return { receiver_type: "PHONE", name: "", user_id: null, mobile: "", wechat_openid: "", email: "", pushplus_token: "", is_enabled: true }; }
function createGroupForm() { return { name: "", description: "", member_ids: [], is_enabled: true }; }
function createRuleForm() { return { name: "", alarm_level_min: 2, event_types: ["trigger", "recover"], channel_types: ["pushplus"], notify_group_id: null, scope_type: "TENANT", project_id: null, site_id: null, device_group_id: null, custom_scope_set_id: null, content_template: "", is_enabled: true }; }
function createOncallForm() { return { name: "", description: "", timezone_name: "Asia/Shanghai", scope_type: "TENANT", project_id: null, site_id: null, device_group_id: null, custom_scope_set_id: null, member_ids: [], is_enabled: true }; }

const channelTypeLabel = (type) => ({ wechat_robot: "企业微信机器人", pushplus: "PushPlus", sms_tencent: "腾讯云短信", webhook: "通用回调" }[type] || "未知");
const receiverTypeLabel = (type) => ({ USER: "系统用户", PHONE: "手机号", WECHAT: "企业微信", EMAIL: "邮箱", PUSHPLUS: "PushPlus" }[type] || type || "-");
const notifyMediumLabel = (type) => ({ wechat: "企业微信", sms: "短信", pushplus: "PushPlus", email: "邮件", webhook: "Webhook" }[type] || type || "-");
const eventTypeName = (type) => ({ trigger: "触发", recover: "恢复", ack: "确认", close: "关闭" }[type] || type || "-");
const endpointSummary = (endpoint, channelType) => {
  const raw = String(endpoint || "").trim();
  if (!raw) return "-";
  if (channelType === "wechat_robot") {
    const idx = raw.indexOf("key=");
    return idx >= 0 ? `Webhook key=${raw.slice(idx + 4, idx + 12)}...` : raw;
  }
  if (channelType === "pushplus") return raw.length > 12 ? `${raw.slice(0, 6)}...${raw.slice(-4)}` : raw;
  return raw;
};
const channelNamesByIds = (channelIds, channelId) => {
  const ids = Array.isArray(channelIds) && channelIds.length ? channelIds : [channelId].filter(Boolean);
  if (!ids.length) return "-";
  return ids.map((id) => channels.value.find((item) => item.id === id)?.name || `通道#${id}`).join("、");
};
const eventTypesLabel = (raw) => {
  const list = Array.isArray(raw) ? raw : String(raw || "").split(",").map((item) => item.trim()).filter(Boolean);
  return list.length ? list.map(eventTypeName).join("、") : "-";
};
const receiverTarget = (row) => row.mobile || row.email || row.wechat_openid || row.pushplus_token || (row.user_id ? `用户#${row.user_id}` : "-");
const groupNameById = (groupId) => groups.value.find((item) => item.id === groupId)?.name || "-";
const projectNameById = (id) => projectOptions.value.find((item) => item.id === id)?.name || (id ? `项目#${id}` : "-");
const siteNameById = (id) => siteOptions.value.find((item) => item.id === id)?.name || (id ? `站点#${id}` : "-");
const deviceGroupNameById = (id) => deviceGroupOptions.value.find((item) => item.id === id)?.name || (id ? `设备组#${id}` : "-");
const customScopeNameById = (id) => customScopeOptions.value.find((item) => item.id === id)?.name || (id ? `范围#${id}` : "-");
const pushLogStatusLabel = (status) => ({ SUCCESS: "成功", FAILED: "失败", RETRYING: "重试中" }[status] || status || "-");
const ruleScopeLabel = (row) => {
  if (row.scope_type === "TENANT") return activeTenantCode.value ? `公司（${activeTenantCode.value}）` : "本公司";
  if (row.scope_type === "PROJECT") return `项目：${projectNameById(row.project_id)}`;
  if (row.scope_type === "SITE") return `站点：${siteNameById(row.site_id)}`;
  if (row.scope_type === "DEVICE_GROUP") return `设备组：${deviceGroupNameById(row.device_group_id)}`;
  if (row.scope_type === "CUSTOM") return `自定义：${customScopeNameById(row.custom_scope_set_id)}`;
  return row.scope_type || "-";
};
const oncallScopeLabel = (row) => ruleScopeLabel(row);
const parsePushplusSecret = (raw) => {
  try {
    const parsed = JSON.parse(raw || "{}");
    return { channel: parsed.channel || "wechat", topic: parsed.topic || "", template: parsed.template || "html" };
  } catch (_e) {
    return createPushplusForm();
  }
};
const buildPushplusSecret = () => JSON.stringify({ channel: pushplusForm.value.channel || "wechat", topic: String(pushplusForm.value.topic || "").trim(), template: pushplusForm.value.template || "html" });
const normalizeRuleScope = () => {
  if (ruleForm.value.scope_type !== "PROJECT") ruleForm.value.project_id = null;
  if (ruleForm.value.scope_type !== "SITE") ruleForm.value.site_id = null;
  if (ruleForm.value.scope_type !== "DEVICE_GROUP") ruleForm.value.device_group_id = null;
  if (ruleForm.value.scope_type !== "CUSTOM") ruleForm.value.custom_scope_set_id = null;
};
const normalizeOncallScope = () => {
  if (oncallForm.value.scope_type !== "PROJECT") oncallForm.value.project_id = null;
  if (oncallForm.value.scope_type !== "SITE") oncallForm.value.site_id = null;
  if (oncallForm.value.scope_type !== "DEVICE_GROUP") oncallForm.value.device_group_id = null;
  if (oncallForm.value.scope_type !== "CUSTOM") oncallForm.value.custom_scope_set_id = null;
};
watch(() => ruleForm.value.scope_type, () => normalizeRuleScope());
watch(() => oncallForm.value.scope_type, () => normalizeOncallScope());

const loadTenants = async () => {
  if (!hasTenantScopedTabs.value) return;
  try {
    const res = await http.get("/tenants");
    tenantOptions.value = Array.isArray(res.data) ? res.data : [];
  } catch (_e) {
    tenantOptions.value = (auth.tenantCodes || []).filter((code) => code && code !== "*").map((code) => ({ code, name: code }));
  }
  if (!activeTenantCode.value) activeTenantCode.value = tenantOptions.value[0]?.code || auth.tenantCodes.find((code) => code && code !== "*") || "";
};

const loadGlobalData = async () => {
  const [channelRes, policyRes] = await Promise.all([
    canViewChannels.value ? http.get("/notify/channels") : Promise.resolve({ data: [] }),
    canViewPolicies.value ? http.get("/notify/policies") : Promise.resolve({ data: [] }),
  ]);
  channels.value = Array.isArray(channelRes.data) ? channelRes.data : [];
  policies.value = Array.isArray(policyRes.data) ? policyRes.data : [];
};
const loadTenantScopedData = async () => {
  if (!hasTenantScopedTabs.value || !activeTenantCode.value) {
    receivers.value = []; groups.value = []; rules.value = []; oncallSchedules.value = []; pushLogs.value = []; return;
  }
  const tenantCode = activeTenantCode.value;
  const jobs = await Promise.allSettled([
    canViewReceivers.value ? http.get(`/notify-receivers?tenant_code=${tenantCode}`) : Promise.resolve({ data: [] }),
    canViewGroups.value ? http.get(`/notify-groups?tenant_code=${tenantCode}`) : Promise.resolve({ data: [] }),
    canViewRules.value ? http.get(`/notify-rules?tenant_code=${tenantCode}`) : Promise.resolve({ data: [] }),
    canViewOncall.value ? http.get(`/notify-oncall?tenant_code=${tenantCode}`) : Promise.resolve({ data: [] }),
    canViewPushLogs.value ? http.get(`/notify-push-logs?tenant_code=${tenantCode}`) : Promise.resolve({ data: [] }),
    http.get(`/projects?tenant_code=${tenantCode}`),
    http.get(`/sites?tenant_code=${tenantCode}`),
    http.get(`/device-groups?tenant_code=${tenantCode}`),
    http.get(`/custom-scope-sets?tenant_code=${tenantCode}`),
  ]);
  receivers.value = jobs[0].status === "fulfilled" && Array.isArray(jobs[0].value.data) ? jobs[0].value.data : [];
  groups.value = jobs[1].status === "fulfilled" && Array.isArray(jobs[1].value.data) ? jobs[1].value.data : [];
  rules.value = jobs[2].status === "fulfilled" && Array.isArray(jobs[2].value.data) ? jobs[2].value.data : [];
  oncallSchedules.value = jobs[3].status === "fulfilled" && Array.isArray(jobs[3].value.data) ? jobs[3].value.data : [];
  pushLogs.value = jobs[4].status === "fulfilled" && Array.isArray(jobs[4].value.data) ? jobs[4].value.data : [];
  projectOptions.value = jobs[5].status === "fulfilled" && Array.isArray(jobs[5].value.data) ? jobs[5].value.data : [];
  siteOptions.value = jobs[6].status === "fulfilled" && Array.isArray(jobs[6].value.data) ? jobs[6].value.data : [];
  deviceGroupOptions.value = jobs[7].status === "fulfilled" && Array.isArray(jobs[7].value.data) ? jobs[7].value.data : [];
  customScopeOptions.value = jobs[8].status === "fulfilled" && Array.isArray(jobs[8].value.data) ? jobs[8].value.data : [];
};

const reloadAll = async () => {
  await loadTenants();
  await loadGlobalData();
  await loadTenantScopedData();
  if (!canViewChannels.value && canViewPolicies.value) activeTab.value = "policies";
  if (!canViewChannels.value && !canViewPolicies.value && canViewReceivers.value) activeTab.value = "receivers";
  if (!canViewChannels.value && !canViewPolicies.value && !canViewReceivers.value && canViewOncall.value) activeTab.value = "oncall";
};

const closeChannelDrawer = () => { channelDrawerVisible.value = false; editingChannelId.value = null; channelTestContent.value = ""; channelForm.value = createChannelForm(); pushplusForm.value = createPushplusForm(); };
const closePolicyDrawer = () => { policyDrawerVisible.value = false; editingPolicyId.value = null; policyForm.value = createPolicyForm(); };
const closeReceiverDrawer = () => { receiverDrawerVisible.value = false; editingReceiverId.value = null; receiverForm.value = createReceiverForm(); };
const closeGroupDrawer = () => { groupDrawerVisible.value = false; editingGroupId.value = null; groupForm.value = createGroupForm(); };
const closeRuleDrawer = () => { ruleDrawerVisible.value = false; editingRuleId.value = null; ruleForm.value = createRuleForm(); };
const closeOncallDrawer = () => { oncallDrawerVisible.value = false; editingOncallId.value = null; oncallForm.value = createOncallForm(); };
const openCreateChannel = () => { closeChannelDrawer(); channelDrawerVisible.value = true; };
const openCreatePolicy = () => { closePolicyDrawer(); policyDrawerVisible.value = true; };
const openCreateReceiver = () => { closeReceiverDrawer(); receiverDrawerVisible.value = true; };
const openCreateGroup = () => { closeGroupDrawer(); groupDrawerVisible.value = true; };
const openCreateRule = () => { closeRuleDrawer(); ruleDrawerVisible.value = true; };
const openCreateOncall = () => { closeOncallDrawer(); oncallDrawerVisible.value = true; };

const submitChannel = async () => {
  if (!channelForm.value.name || !channelForm.value.endpoint) return ElMessage.warning("请填写通道名称和地址");
  try {
    const payload = { ...channelForm.value, secret: channelForm.value.channel_type === "pushplus" ? buildPushplusSecret() : channelForm.value.secret };
    if (editingChannelId.value) await http.put(`/notify/channels/${editingChannelId.value}`, payload);
    else await http.post("/notify/channels", payload);
    ElMessage.success("通道保存成功");
    closeChannelDrawer();
    await loadGlobalData();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || "通道保存失败"); }
};
const submitPolicy = async () => {
  if (!policyForm.value.name || !policyForm.value.channel_ids.length) return ElMessage.warning("请填写策略名称并选择至少一个通知通道");
  try {
    const payload = { name: policyForm.value.name, channel_id: policyForm.value.channel_ids[0], channel_ids: policyForm.value.channel_ids, min_alarm_level: policyForm.value.min_alarm_level, event_types: policyForm.value.event_type_list.join(","), is_enabled: policyForm.value.is_enabled };
    if (editingPolicyId.value) await http.put(`/notify/policies/${editingPolicyId.value}`, payload);
    else await http.post("/notify/policies", payload);
    ElMessage.success("策略保存成功");
    closePolicyDrawer();
    await loadGlobalData();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || "策略保存失败"); }
};
const submitReceiver = async () => {
  if (!activeTenantCode.value) return ElMessage.warning("请先选择公司");
  if (!receiverForm.value.name) return ElMessage.warning("请填写接收人名称");
  try {
    const payload = { ...receiverForm.value };
    if (editingReceiverId.value) await http.put(`/notify-receivers/${editingReceiverId.value}?tenant_code=${activeTenantCode.value}`, payload);
    else await http.post(`/notify-receivers?tenant_code=${activeTenantCode.value}`, payload);
    ElMessage.success("接收人保存成功");
    closeReceiverDrawer();
    await loadTenantScopedData();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || "接收人保存失败"); }
};
const submitGroup = async () => {
  if (!activeTenantCode.value) return ElMessage.warning("请先选择公司");
  if (!groupForm.value.name) return ElMessage.warning("请填写通知组名称");
  try {
    const payload = { ...groupForm.value };
    if (editingGroupId.value) await http.put(`/notify-groups/${editingGroupId.value}?tenant_code=${activeTenantCode.value}`, payload);
    else await http.post(`/notify-groups?tenant_code=${activeTenantCode.value}`, payload);
    ElMessage.success("通知组保存成功");
    closeGroupDrawer();
    await loadTenantScopedData();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || "通知组保存失败"); }
};
const submitRule = async () => {
  if (!activeTenantCode.value) return ElMessage.warning("请先选择公司");
  if (!ruleForm.value.name) return ElMessage.warning("请填写规则名称");
  if (!ruleForm.value.event_types.length) return ElMessage.warning("请至少选择一个事件类型");
  if (!ruleForm.value.channel_types.length) return ElMessage.warning("请至少选择一个推送渠道");
  try {
    const payload = { ...ruleForm.value };
    if (editingRuleId.value) await http.put(`/notify-rules/${editingRuleId.value}?tenant_code=${activeTenantCode.value}`, payload);
    else await http.post(`/notify-rules?tenant_code=${activeTenantCode.value}`, payload);
    ElMessage.success("推送规则保存成功");
    closeRuleDrawer();
    await loadTenantScopedData();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || "推送规则保存失败"); }
};
const submitOncall = async () => {
  if (!activeTenantCode.value) return ElMessage.warning("请先选择公司");
  if (!oncallForm.value.name) return ElMessage.warning("请填写值班表名称");
  try {
    const payload = { ...oncallForm.value };
    if (editingOncallId.value) await http.put(`/notify-oncall/${editingOncallId.value}?tenant_code=${activeTenantCode.value}`, payload);
    else await http.post(`/notify-oncall?tenant_code=${activeTenantCode.value}`, payload);
    ElMessage.success("值班表保存成功");
    closeOncallDrawer();
    await loadTenantScopedData();
  } catch (e) { ElMessage.error(e?.response?.data?.detail || "值班表保存失败"); }
};

const editChannel = (row) => { editingChannelId.value = row.id; channelForm.value = { name: row.name, channel_type: row.channel_type, endpoint: row.endpoint, secret: row.secret || "", is_enabled: row.is_enabled }; pushplusForm.value = row.channel_type === "pushplus" ? parsePushplusSecret(row.secret) : createPushplusForm(); channelDrawerVisible.value = true; };
const editPolicy = (row) => { editingPolicyId.value = row.id; policyForm.value = { name: row.name, channel_ids: Array.isArray(row.channel_ids) && row.channel_ids.length ? [...row.channel_ids] : [row.channel_id].filter(Boolean), min_alarm_level: row.min_alarm_level, event_type_list: String(row.event_types || "").split(",").map((item) => item.trim()).filter(Boolean), is_enabled: row.is_enabled }; policyDrawerVisible.value = true; };
const editReceiver = (row) => { editingReceiverId.value = row.id; receiverForm.value = { receiver_type: row.receiver_type, name: row.name, user_id: row.user_id || null, mobile: row.mobile || "", wechat_openid: row.wechat_openid || "", email: row.email || "", pushplus_token: row.pushplus_token || "", is_enabled: row.is_enabled }; receiverDrawerVisible.value = true; };
const editGroup = (row) => { editingGroupId.value = row.id; groupForm.value = { name: row.name, description: row.description || "", member_ids: [...(row.member_ids || [])], is_enabled: row.is_enabled }; groupDrawerVisible.value = true; };
const editRule = (row) => { editingRuleId.value = row.id; ruleForm.value = { name: row.name, alarm_level_min: row.alarm_level_min, event_types: [...(row.event_types || [])], channel_types: [...(row.channel_types || [])], notify_group_id: row.notify_group_id || null, scope_type: row.scope_type || "TENANT", project_id: row.project_id || null, site_id: row.site_id || null, device_group_id: row.device_group_id || null, custom_scope_set_id: row.custom_scope_set_id || null, content_template: row.content_template || "", is_enabled: row.is_enabled }; ruleDrawerVisible.value = true; };
const editOncall = (row) => { editingOncallId.value = row.id; oncallForm.value = { name: row.name, description: row.description || "", timezone_name: row.timezone_name || "Asia/Shanghai", scope_type: row.scope_type || "TENANT", project_id: row.project_id || null, site_id: row.site_id || null, device_group_id: row.device_group_id || null, custom_scope_set_id: row.custom_scope_set_id || null, member_ids: [...(row.member_ids || [])], is_enabled: row.is_enabled }; oncallDrawerVisible.value = true; };

const toggleChannel = async (row) => { try { await http.put(`/notify/channels/${row.id}`, { name: row.name, channel_type: row.channel_type, endpoint: row.endpoint, secret: row.secret || "", is_enabled: !row.is_enabled }); ElMessage.success(`通道已${row.is_enabled ? "停用" : "启用"}`); await loadGlobalData(); } catch (e) { ElMessage.error(e?.response?.data?.detail || "通道状态更新失败"); } };
const togglePolicy = async (row) => { try { await http.put(`/notify/policies/${row.id}`, { name: row.name, channel_id: Array.isArray(row.channel_ids) && row.channel_ids.length ? row.channel_ids[0] : row.channel_id, channel_ids: Array.isArray(row.channel_ids) && row.channel_ids.length ? row.channel_ids : [row.channel_id].filter(Boolean), min_alarm_level: row.min_alarm_level, event_types: row.event_types, is_enabled: !row.is_enabled }); ElMessage.success(`策略已${row.is_enabled ? "停用" : "启用"}`); await loadGlobalData(); } catch (e) { ElMessage.error(e?.response?.data?.detail || "策略状态更新失败"); } };
const removeChannel = async (row) => { try { await ElMessageBox.confirm(`确认删除通知通道“${row.name}”吗？`, "删除确认", { type: "warning" }); await http.delete(`/notify/channels/${row.id}`); ElMessage.success("通道已删除"); await loadGlobalData(); } catch (e) { if (e === "cancel" || e === "close") return; ElMessage.error(e?.response?.data?.detail || "通道删除失败"); } };
const removePolicy = async (row) => { try { await ElMessageBox.confirm(`确认删除通知策略“${row.name}”吗？`, "删除确认", { type: "warning" }); await http.delete(`/notify/policies/${row.id}`); ElMessage.success("策略已删除"); await loadGlobalData(); } catch (e) { if (e === "cancel" || e === "close") return; ElMessage.error(e?.response?.data?.detail || "策略删除失败"); } };
const removeReceiver = async (row) => { try { await ElMessageBox.confirm(`确认删除接收人“${row.name}”吗？`, "删除确认", { type: "warning" }); await http.delete(`/notify-receivers/${row.id}?tenant_code=${activeTenantCode.value}`); ElMessage.success("接收人已删除"); await loadTenantScopedData(); } catch (e) { if (e === "cancel" || e === "close") return; ElMessage.error(e?.response?.data?.detail || "接收人删除失败"); } };
const removeGroup = async (row) => { try { await ElMessageBox.confirm(`确认删除通知组“${row.name}”吗？`, "删除确认", { type: "warning" }); await http.delete(`/notify-groups/${row.id}?tenant_code=${activeTenantCode.value}`); ElMessage.success("通知组已删除"); await loadTenantScopedData(); } catch (e) { if (e === "cancel" || e === "close") return; ElMessage.error(e?.response?.data?.detail || "通知组删除失败"); } };
const removeRule = async (row) => { try { await ElMessageBox.confirm(`确认删除推送规则“${row.name}”吗？`, "删除确认", { type: "warning" }); await http.delete(`/notify-rules/${row.id}?tenant_code=${activeTenantCode.value}`); ElMessage.success("推送规则已删除"); await loadTenantScopedData(); } catch (e) { if (e === "cancel" || e === "close") return; ElMessage.error(e?.response?.data?.detail || "推送规则删除失败"); } };
const removeOncall = async (row) => { try { await ElMessageBox.confirm(`确认删除值班表“${row.name}”吗？`, "删除确认", { type: "warning" }); await http.delete(`/notify-oncall/${row.id}?tenant_code=${activeTenantCode.value}`); ElMessage.success("值班表已删除"); await loadTenantScopedData(); } catch (e) { if (e === "cancel" || e === "close") return; ElMessage.error(e?.response?.data?.detail || "值班表删除失败"); } };
const retryPushLog = async (row) => { try { const res = await http.post(`/notify-push-logs/${row.id}/retry?tenant_code=${activeTenantCode.value}`); ElMessage.success(res?.data?.detail || "已重发"); await loadTenantScopedData(); } catch (e) { ElMessage.error(e?.response?.data?.detail || "重发失败"); } };
const testChannel = async (row) => { testingChannelId.value = row.id; try { const payload = {}; const content = String(channelTestContent.value || "").trim(); if (content) payload.content = content; const res = await http.post(`/notify/channels/${row.id}/test`, payload); ElMessage.success(res?.data?.detail || "测试发送成功"); } catch (e) { ElMessage.error(e?.response?.data?.detail || "测试发送失败"); } finally { testingChannelId.value = null; } };
const testCurrentChannel = async () => { const row = channels.value.find((item) => item.id === editingChannelId.value); if (!row) return ElMessage.warning("请先保存通道后再测试"); await testChannel(row); };

onMounted(async () => {
  try { await reloadAll(); } catch (_e) { ElMessage.error("加载通知管理数据失败"); }
});
</script>

<style scoped>
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.page-head h2 { margin: 0; }
.page-head p { margin: 6px 0 0; color: #64748b; }
.notify-tabs { margin-top: 12px; }
.tenant-card, .panel-card { border-radius: 16px; }
.tenant-head, .panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.panel-title { font-size: 16px; font-weight: 700; color: #0f172a; }
.panel-tip { margin-top: 4px; color: #64748b; font-size: 13px; }
.row-actions, .drawer-footer { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.drawer-form { padding-right: 12px; }
.event-group { display: flex; flex-wrap: wrap; gap: 8px; }
:deep(.danger-item) { color: #dc2626; }
@media (max-width: 900px) { .page-head, .tenant-head, .panel-head { flex-direction: column; align-items: stretch; } }
</style>
