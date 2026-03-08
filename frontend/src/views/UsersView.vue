<template>
  <AppShell>
    <div class="page-head">
      <div>
        <h2>公司与人员管理</h2>
        <p>先建公司，再在公司下添加管理员、员工和站点，按层级完成配置。</p>
      </div>
      <div class="head-actions">
        <el-button @click="openRoleManager">角色管理</el-button>
        <el-button type="primary" @click="openTenantCreate">新增公司</el-button>
      </div>
    </div>

    <div class="company-layout">
      <aside class="company-pane">
        <el-input v-model="tenantKeyword" clearable placeholder="搜索公司名称或编码" />
        <div class="company-list">
          <button
            v-for="tenant in filteredTenants"
            :key="tenant.code"
            type="button"
            class="company-item"
            :class="{ active: selectedTenantCode === tenant.code }"
            @click="selectTenant(tenant.code)"
          >
            <strong>{{ tenant.name }}</strong>
            <small>{{ tenant.code }}</small>
          </button>
          <div v-if="filteredTenants.length === 0" class="empty-block">暂无公司</div>
        </div>
      </aside>

      <section class="detail-pane" v-if="selectedTenant">
        <div class="tenant-summary">
          <div>
            <h3>{{ selectedTenant.name }}</h3>
            <p>{{ selectedTenant.code }} · {{ tenantTypeLabel(selectedTenant.tenant_type) }}</p>
          </div>
          <div class="summary-actions">
            <el-button @click="openCreateUserForTenant('manager')">新增管理员</el-button>
            <el-button type="primary" @click="openCreateUserForTenant('staff')">新增员工</el-button>
          </div>
        </div>

        <el-tabs v-model="activeTenantTab">
          <el-tab-pane label="管理员" name="managers">
            <div class="tab-toolbar">
              <span>负责该公司人员、站点和策略的管理员账号</span>
              <el-button size="small" @click="openCreateUserForTenant('manager')">添加管理员</el-button>
            </div>
            <el-table :data="selectedTenantManagers" stripe>
              <el-table-column prop="username" label="用户名" min-width="140" />
              <el-table-column prop="full_name" label="姓名" min-width="120" />
              <el-table-column label="角色" min-width="180">
                <template #default="{ row }">{{ formatRoleNames(row.roles) }}</template>
              </el-table-column>
              <el-table-column label="数据范围" min-width="220">
                <template #default="{ row }">{{ formatDataScopes(row.data_scopes) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? "启用" : "停用" }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="220" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="openEdit(row)">编辑</el-button>
                  <el-button size="small" @click="toggleActive(row)">{{ row.is_active ? "停用" : "启用" }}</el-button>
                  <el-button size="small" type="danger" @click="removeUser(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="员工" name="staff">
            <div class="tab-toolbar">
              <span>默认继承该公司数据范围，必要时再细化到项目、站点、设备组或自定义范围</span>
            <div class="head-actions">
              <el-button size="small" @click="downloadBatchTemplate">下载模板</el-button>
              <el-button size="small" @click="openBatchCreate">批量创建</el-button>
              <el-button size="small" type="primary" @click="openCreateUserForTenant('staff')">添加员工</el-button>
            </div>
            </div>
            <el-table :data="selectedTenantStaff" stripe>
              <el-table-column prop="username" label="用户名" min-width="140" />
              <el-table-column prop="full_name" label="姓名" min-width="120" />
              <el-table-column label="角色" min-width="180">
                <template #default="{ row }">{{ formatRoleNames(row.roles) }}</template>
              </el-table-column>
              <el-table-column label="数据范围" min-width="220">
                <template #default="{ row }">{{ formatDataScopes(row.data_scopes) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? "启用" : "停用" }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="220" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="openEdit(row)">编辑</el-button>
                  <el-button size="small" @click="toggleActive(row)">{{ row.is_active ? "停用" : "启用" }}</el-button>
                  <el-button size="small" type="danger" @click="removeUser(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="项目" name="projects">
            <div class="tab-toolbar">
              <span>项目是公司下的授权分层，员工范围可以直接绑定到项目</span>
              <el-button size="small" type="primary" @click="openProjectCreate">新增项目</el-button>
            </div>
            <el-table :data="selectedTenantProjects" stripe>
              <el-table-column prop="code" label="项目编码" min-width="140" />
              <el-table-column prop="name" label="项目名称" min-width="180" />
              <el-table-column prop="status" label="状态" width="100" />
              <el-table-column label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="openProjectEdit(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="removeProject(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="站点" name="sites">
            <div class="tab-toolbar">
              <span>当前公司已绑定站点</span>
              <router-link class="inline-link" to="/sites-manage">去站点管理</router-link>
            </div>
            <el-table :data="selectedTenantSites" stripe>
              <el-table-column prop="code" label="站点编码" min-width="120" />
              <el-table-column prop="name" label="站点名称" min-width="160" />
              <el-table-column prop="region" label="区域" min-width="120" />
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? "启用" : "停用" }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="设备组" name="device_groups">
            <div class="tab-toolbar">
              <span>设备组用于把站点下设备做授权归类，适合更细粒度的员工范围控制</span>
              <el-button size="small" type="primary" @click="openDeviceGroupCreate">新增设备组</el-button>
            </div>
            <el-table :data="selectedTenantDeviceGroups" stripe>
              <el-table-column prop="code" label="设备组编码" min-width="140" />
              <el-table-column prop="name" label="设备组名称" min-width="180" />
              <el-table-column label="所属项目" min-width="160">
                <template #default="{ row }">{{ projectNameById(row.project_id) }}</template>
              </el-table-column>
              <el-table-column label="所属站点" min-width="180">
                <template #default="{ row }">{{ siteNameById(row.site_id) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="openDeviceGroupEdit(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="removeDeviceGroup(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="自定义范围" name="custom_scopes">
            <div class="tab-toolbar">
              <span>把常用站点集合预先存成范围模板，员工授权时可直接选用</span>
              <el-button size="small" type="primary" @click="openCustomScopeCreate">新增范围</el-button>
            </div>
            <el-table :data="customScopeSets" stripe>
              <el-table-column prop="name" label="范围名称" min-width="180" />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">{{ row.resource_type === "site" ? "站点集合" : row.resource_type }}</template>
              </el-table-column>
              <el-table-column prop="item_count" label="站点数" width="90" />
              <el-table-column label="站点摘要" min-width="260">
                <template #default="{ row }">{{ customScopeSiteSummary(row) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="openCustomScopeEdit(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="removeCustomScope(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane v-if="auth.hasPermission('audit.view')" label="操作记录" name="operation_logs">
            <div class="tab-toolbar">
              <span>查看当前公司的账号、项目、设备组和自定义范围操作轨迹</span>
              <div class="head-actions">
                <el-select v-model="operationLogFilters.action" clearable size="small" placeholder="动作筛选" style="width: 180px">
                  <el-option
                    v-for="item in operationLogActionOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
                <el-input
                  v-model="operationLogFilters.operator_keyword"
                  clearable
                  size="small"
                  placeholder="搜索操作人"
                  style="width: 160px"
                />
                <el-date-picker
                  v-model="operationLogFilters.date_range"
                  type="daterange"
                  range-separator="至"
                  start-placeholder="开始日期"
                  end-placeholder="结束日期"
                  size="small"
                  value-format="YYYY-MM-DD"
                />
                <el-button size="small" @click="exportOperationLogs">导出</el-button>
                <el-button size="small" @click="reloadOperationLogs">刷新</el-button>
              </div>
            </div>
            <el-table :data="pagedOperationLogs" stripe>
              <el-table-column label="时间" min-width="170">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作人" min-width="120">
                <template #default="{ row }">{{ row.operator_name || "-" }}</template>
              </el-table-column>
              <el-table-column label="动作" min-width="140">
                <template #default="{ row }">{{ operationActionLabel(row.action) }}</template>
              </el-table-column>
              <el-table-column prop="content" label="内容" min-width="360" />
            </el-table>
            <div class="pagination-wrap">
              <el-pagination
                v-model:current-page="operationLogPage"
                v-model:page-size="operationLogPageSize"
                :page-sizes="[10, 20, 50]"
                :total="selectedTenantOperationLogs.length"
                layout="total, sizes, prev, pager, next"
              />
            </div>
          </el-tab-pane>
        </el-tabs>
      </section>

      <section v-else class="detail-pane empty-state">
        <h3>先选择或新增一个公司</h3>
        <p>后续管理员、员工和站点都围绕该公司维护。</p>
      </section>
    </div>

    <el-dialog v-model="tenantDialogVisible" title="新增公司" width="520px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="公司名称" required>
          <el-input v-model="tenantForm.name" placeholder="例如：A公司" />
        </el-form-item>
        <el-form-item label="公司编码" required>
          <el-input v-model="tenantForm.code" placeholder="例如：COMP-A" />
        </el-form-item>
        <el-form-item label="公司类型">
          <el-select v-model="tenantForm.tenant_type" style="width: 100%">
            <el-option label="子公司" value="subsidiary" />
            <el-option label="客户" value="customer" />
            <el-option label="总部" value="headquarters" />
          </el-select>
        </el-form-item>
        <el-form-item label="上级公司">
          <el-select v-model="tenantForm.parent_code" clearable filterable style="width: 100%" placeholder="可选">
            <el-option
              v-for="item in tenantOptionsForParent"
              :key="item.code"
              :label="`${item.name}（${item.code}）`"
              :value="item.code"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tenantDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTenant">保存并继续</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="projectDialogVisible"
      :title="projectEditingId ? '编辑项目' : '新增项目'"
      width="560px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="所属公司">
          <el-input :model-value="selectedTenant ? `${selectedTenant.name}（${selectedTenant.code}）` : '-'" disabled />
        </el-form-item>
        <el-form-item label="项目编码" required>
          <el-input v-model="projectForm.code" :disabled="Boolean(projectEditingId)" placeholder="例如：PROJ-002" />
        </el-form-item>
        <el-form-item label="项目名称" required>
          <el-input v-model="projectForm.name" placeholder="例如：东区示范项目" />
        </el-form-item>
        <el-form-item label="状态" v-if="projectEditingId">
          <el-select v-model="projectForm.status" style="width: 100%">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="inactive" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projectDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="projectSubmitLoading" @click="submitProject">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="batchDialogVisible"
      title="批量创建员工"
      width="760px"
      destroy-on-close
    >
      <el-form label-width="108px">
        <el-form-item label="所属公司">
          <el-input :model-value="selectedTenant ? `${selectedTenant.name}（${selectedTenant.code}）` : '-'" disabled />
        </el-form-item>
        <div class="grid grid-two">
          <el-form-item label="默认角色">
            <el-select v-model="batchForm.primary_role" filterable style="width: 100%">
              <el-option
                v-for="role in roleDefs.filter((item) => item.name !== 'sub_noc' && item.name !== 'admin' && item.name !== 'hq_noc')"
                :key="role.id"
                :label="roleLabel(role.name)"
                :value="role.name"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="默认密码">
            <el-input v-model="batchForm.default_password" type="password" show-password placeholder="每行未填密码时使用，至少 6 位" />
          </el-form-item>
        </div>
        <el-form-item label="重复账号处理">
          <el-select v-model="batchForm.on_existing" style="width: 100%">
            <el-option label="跳过已存在账号" value="skip" />
            <el-option label="只更新姓名" value="update_name" />
            <el-option label="更新姓名并重置密码" value="reset_password" />
          </el-select>
          <div class="field-tip">当前版本不会改动已存在账号的角色和数据范围，只处理姓名和密码。</div>
        </el-form-item>
        <el-form-item label="批量内容" required>
          <el-input
            v-model="batchForm.rows_text"
            type="textarea"
            :rows="10"
            placeholder="每行一个员工，格式：用户名,姓名,密码（密码可省略）&#10;例如：a_user01,张三,abc12345&#10;a_user02,李四"
          />
          <div class="field-tip">批量入口默认只绑定当前公司范围。如需更细的数据范围，创建后再单独编辑该员工。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSubmitLoading" @click="submitBatchCreate">开始创建</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="userDialogVisible"
      :title="editingUserId ? '编辑用户' : (userDialogMode === 'manager' ? '新增管理员' : '新增员工')"
      width="820px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <div class="grid grid-two">
          <el-form-item label="所属公司">
            <el-input :model-value="selectedTenant ? `${selectedTenant.name}（${selectedTenant.code}）` : '-'" disabled />
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="form.primary_role" filterable style="width: 100%" @change="syncRolesFromPrimary">
              <el-option v-for="role in currentRoleOptions" :key="role.id" :label="roleLabel(role.name)" :value="role.name" />
            </el-select>
          </el-form-item>
        </div>

        <div class="grid grid-two">
          <el-form-item label="用户名" required>
            <el-input v-model="form.username" placeholder="例如：a_admin01" />
          </el-form-item>
          <el-form-item label="姓名">
            <el-input v-model="form.full_name" placeholder="例如：张三" />
          </el-form-item>
        </div>

        <div class="grid grid-two">
          <el-form-item :label="editingUserId ? '新密码' : '密码'" required>
            <el-input v-model="form.password" type="password" show-password :placeholder="editingUserId ? '留空则不修改密码' : '至少 6 位'" />
          </el-form-item>
          <el-form-item label="用户状态">
            <el-switch v-model="form.is_active" active-text="启用" inactive-text="停用" :disabled="!editingUserId" />
          </el-form-item>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">数据范围</div>
              <div class="panel-tip">默认已绑定当前公司。只有需要进一步收窄权限时，才增加项目、站点、设备组、区域或自定义范围。</div>
            </div>
            <div class="head-actions">
              <el-button size="small" @click="resetToTenantScope">仅本公司</el-button>
              <el-button size="small" @click="addExtraScope">增加范围</el-button>
            </div>
          </div>
          <div v-for="(scope, index) in form.extra_scopes" :key="index" class="scope-row">
            <el-select v-model="scope.scope_type" style="width: 180px" @change="scope.scope_value = ''">
              <el-option label="项目" value="project" />
              <el-option label="站点" value="site" />
              <el-option label="设备组" value="device_group" />
              <el-option label="区域" value="region" />
              <el-option label="自定义范围" value="custom" />
            </el-select>
            <el-select v-model="scope.scope_value" filterable clearable style="flex: 1" :placeholder="scopePlaceholder(scope.scope_type)">
              <el-option
                v-for="option in extraScopeOptions(scope.scope_type)"
                :key="`${scope.scope_type}-${option.value}`"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-button text type="danger" @click="removeExtraScope(index)">删除</el-button>
          </div>
          <div v-if="form.extra_scopes.length === 0" class="empty-inline">当前为“仅本公司”范围。</div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitLoading" @click="submitUser">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="deviceGroupDialogVisible"
      :title="deviceGroupEditingId ? '编辑设备组' : '新增设备组'"
      width="620px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="所属公司">
          <el-input :model-value="selectedTenant ? `${selectedTenant.name}（${selectedTenant.code}）` : '-'" disabled />
        </el-form-item>
        <el-form-item label="设备组编码" required>
          <el-input v-model="deviceGroupForm.code" :disabled="Boolean(deviceGroupEditingId)" placeholder="例如：DG-002" />
        </el-form-item>
        <el-form-item label="设备组名称" required>
          <el-input v-model="deviceGroupForm.name" placeholder="例如：夜间值守设备组" />
        </el-form-item>
        <el-form-item label="所属项目">
          <el-select v-model="deviceGroupForm.project_id" clearable filterable style="width: 100%">
            <el-option
              v-for="project in selectedTenantProjects"
              :key="project.id"
              :label="`${project.name}（${project.code}）`"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="所属站点">
          <el-select v-model="deviceGroupForm.site_id" clearable filterable style="width: 100%">
            <el-option
              v-for="site in selectedTenantSites"
              :key="site.id"
              :label="`${site.name}（${site.code}）`"
              :value="site.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deviceGroupDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="deviceGroupSubmitLoading" @click="submitDeviceGroup">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="customScopeDialogVisible"
      :title="customScopeEditingId ? '编辑自定义范围' : '新增自定义范围'"
      width="640px"
      destroy-on-close
    >
      <el-form label-width="96px">
        <el-form-item label="所属公司">
          <el-input :model-value="selectedTenant ? `${selectedTenant.name}（${selectedTenant.code}）` : '-'" disabled />
        </el-form-item>
        <el-form-item label="范围名称" required>
          <el-input v-model="customScopeForm.name" placeholder="例如：重点站点、夜间值守站点" />
        </el-form-item>
        <el-form-item label="站点集合" required>
          <el-select v-model="customScopeForm.resource_ids" multiple filterable clearable style="width: 100%" placeholder="选择站点">
            <el-option
              v-for="site in selectedTenantSites"
              :key="site.id"
              :label="`${site.name}（${site.code}）`"
              :value="site.id"
            />
          </el-select>
          <div class="field-tip">当前版本自定义范围先按站点集合实现，后续再扩展项目或设备组集合。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="customScopeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="customScopeSubmitLoading" @click="submitCustomScope">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleDialogVisible" title="角色管理" width="980px">
      <div class="role-toolbar">
        <el-input v-model="roleKeyword" clearable placeholder="搜索角色名或说明" style="max-width: 320px" />
        <el-button @click="openRoleCreate">新建角色</el-button>
      </div>
      <el-table :data="filteredRoleDefs" stripe>
        <el-table-column label="角色" min-width="180">
          <template #default="{ row }">
            <div class="role-name-cell">
              <strong>{{ roleLabel(row.name) }}</strong>
              <small>{{ row.name }}</small>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="说明" min-width="180" />
        <el-table-column label="权限数" width="90">
          <template #default="{ row }">{{ (row.permissions || []).length }}</template>
        </el-table-column>
        <el-table-column label="权限预览" min-width="260">
          <template #default="{ row }">{{ summarizePermissions(row.permissions) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ row.is_builtin ? "内置" : "自定义" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="210">
          <template #default="{ row }">
            <el-button size="small" @click="openRoleEdit(row)">{{ row.is_builtin ? "查看" : "编辑" }}</el-button>
            <el-button size="small" @click="copyRole(row)">复制</el-button>
            <el-button size="small" type="danger" :disabled="row.is_builtin" @click="deleteRole(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="roleEditVisible" :title="roleEditingId ? '编辑角色' : '新建角色'" width="920px" destroy-on-close>
      <el-form label-width="96px">
        <div class="grid grid-two">
          <el-form-item label="角色标识" required>
            <el-input v-model="roleForm.name" :disabled="roleForm.is_builtin" placeholder="例如：regional_manager" />
            <div class="field-tip">只支持小写字母、数字、下划线，且必须以字母开头。</div>
          </el-form-item>
          <el-form-item label="角色说明">
            <el-input v-model="roleForm.description" placeholder="例如：区域值班负责人" />
          </el-form-item>
        </div>

        <el-form-item v-if="!roleEditingId" label="套用模板">
          <el-select v-model="roleForm.template_key" clearable style="width: 100%" placeholder="先选一个角色模板，再按需微调" @change="applyTemplateByKey">
            <el-option v-for="preset in rolePresets" :key="preset.key" :label="preset.label" :value="preset.key" />
          </el-select>
        </el-form-item>

        <el-form-item label="权限搜索">
          <el-input v-model="permissionKeyword" clearable placeholder="搜索权限名称、说明或权限键" />
        </el-form-item>
        <div class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">快捷配置</div>
              <div class="panel-tip">已选择 {{ roleForm.permissions.length }} 项权限。</div>
            </div>
            <div class="head-actions">
              <el-button size="small" :disabled="roleForm.is_builtin" @click="selectAllPermissions">全选</el-button>
              <el-button size="small" :disabled="roleForm.is_builtin" @click="clearPermissions">清空</el-button>
            </div>
          </div>
          <div class="preset-list">
            <el-button v-for="preset in rolePresets" :key="preset.key" size="small" :disabled="roleForm.is_builtin" @click="applyPreset(preset.keys)">
              {{ preset.label }}
            </el-button>
          </div>
        </div>

        <div v-for="group in permissionGroups" :key="group.key" class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">{{ group.label }}</div>
              <div class="panel-tip">{{ group.items.length }} 项权限</div>
            </div>
            <div class="head-actions">
              <el-button size="small" text :disabled="roleForm.is_builtin" @click="toggleGroup(group.items, true)">全选本组</el-button>
              <el-button size="small" text :disabled="roleForm.is_builtin" @click="toggleGroup(group.items, false)">清空本组</el-button>
            </div>
          </div>
          <el-checkbox-group v-model="roleForm.permissions" :disabled="roleForm.is_builtin" class="permission-grid">
            <el-checkbox v-for="item in group.items" :key="item.key" :label="item.key" :value="item.key">
              <span>{{ item.label }}</span>
              <small>{{ item.description }}</small>
            </el-checkbox>
          </el-checkbox-group>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="roleEditVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRole">保存</el-button>
      </template>
    </el-dialog>
  </AppShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AppShell from "../components/AppShell.vue";
import http from "../api/http";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const rows = ref([]);
const tenants = ref([]);
const sites = ref([]);
const projects = ref([]);
const deviceGroups = ref([]);
const customScopeSets = ref([]);
const operationLogs = ref([]);
const operationLogPage = ref(1);
const operationLogPageSize = ref(10);
const roleDefs = ref([]);
const permissionOptions = ref([]);
const roleKeyword = ref("");
const permissionKeyword = ref("");
const tenantKeyword = ref("");
const tenantDialogVisible = ref(false);
const projectDialogVisible = ref(false);
const batchDialogVisible = ref(false);
const userDialogVisible = ref(false);
const deviceGroupDialogVisible = ref(false);
const roleDialogVisible = ref(false);
const roleEditVisible = ref(false);
const customScopeDialogVisible = ref(false);
const submitLoading = ref(false);
const projectSubmitLoading = ref(false);
const batchSubmitLoading = ref(false);
const deviceGroupSubmitLoading = ref(false);
const customScopeSubmitLoading = ref(false);
const editingUserId = ref(null);
const projectEditingId = ref(null);
const roleEditingId = ref(null);
const deviceGroupEditingId = ref(null);
const customScopeEditingId = ref(null);
const selectedTenantCode = ref("");
const activeTenantTab = ref("managers");
const userDialogMode = ref("staff");
const operationLogFilters = reactive({
  action: "",
  operator_keyword: "",
  date_range: [],
});

const operationLogActionOptions = [
  { value: "user.create", label: "创建用户" },
  { value: "user.update", label: "更新用户" },
  { value: "user.delete", label: "删除用户" },
  { value: "user.batch_create", label: "批量创建用户" },
  { value: "project.create", label: "创建项目" },
  { value: "project.update", label: "更新项目" },
  { value: "project.delete", label: "删除项目" },
  { value: "device_group.create", label: "创建设备组" },
  { value: "device_group.update", label: "更新设备组" },
  { value: "device_group.delete", label: "删除设备组" },
  { value: "custom_scope.create", label: "创建自定义范围" },
  { value: "custom_scope.update", label: "更新自定义范围" },
  { value: "custom_scope.delete", label: "删除自定义范围" },
];

const roleLabelMap = {
  admin: "管理员",
  operator: "员工",
  hq_noc: "总部管理员",
  sub_noc: "公司管理员",
};

const rolePresets = [
  { key: "read_only", label: "只读值守模板", keys: ["dashboard.view", "realtime.view", "alarm.view", "history.view", "site.view"] },
  { key: "tenant_ops", label: "租户运维模板", keys: ["dashboard.view", "realtime.view", "alarm.view", "alarm.ack", "alarm.close", "history.view", "site.view", "site.create", "site.update", "alarm_rule.tenant.view", "alarm_rule.tenant.manage", "notify.channel.view", "notify.policy.view"] },
  { key: "hq_ops", label: "总部治理模板", keys: ["dashboard.view", "realtime.view", "alarm.view", "alarm.ack", "alarm.close", "history.view", "site.view", "alarm_rule.template.view", "alarm_rule.template.manage", "notify.channel.view", "notify.channel.manage", "notify.policy.view", "notify.policy.manage"] },
];

const tenantForm = reactive({
  code: "",
  name: "",
  tenant_type: "subsidiary",
  parent_code: "",
});

const form = reactive({
  username: "",
  full_name: "",
  password: "",
  is_active: true,
  primary_role: "operator",
  role_names: [],
  extra_scopes: [],
});

const roleForm = reactive({
  name: "",
  description: "",
  template_key: "",
  permissions: [],
  is_builtin: false,
});

const batchForm = reactive({
  primary_role: "operator",
  default_password: "",
  on_existing: "skip",
  rows_text: "",
});

const projectForm = reactive({
  code: "",
  name: "",
  status: "active",
});

const deviceGroupForm = reactive({
  code: "",
  name: "",
  project_id: null,
  site_id: null,
});

const customScopeForm = reactive({
  name: "",
  resource_ids: [],
});

const filteredTenants = computed(() => {
  const keyword = String(tenantKeyword.value || "").trim().toLowerCase();
  if (!keyword) return tenants.value;
  return tenants.value.filter((item) => [item.name, item.code].join(" ").toLowerCase().includes(keyword));
});

const selectedTenant = computed(() => tenants.value.find((item) => item.code === selectedTenantCode.value) || null);
const tenantOptionsForParent = computed(() => tenants.value.filter((item) => item.code !== tenantForm.code));

const usersByTenant = computed(() => {
  const map = new Map();
  for (const tenant of tenants.value) map.set(tenant.code, []);
  for (const row of rows.value) {
    const codes = new Set();
    for (const scope of row.data_scopes || []) {
      if (scope.scope_type === "tenant" && scope.scope_value) codes.add(scope.scope_value);
    }
    for (const item of row.tenant_roles || []) {
      if (item.tenant_code) codes.add(item.tenant_code);
    }
    for (const code of codes) {
      if (!map.has(code)) map.set(code, []);
      map.get(code).push(row);
    }
  }
  return map;
});

const selectedTenantUsers = computed(() => usersByTenant.value.get(selectedTenantCode.value) || []);
const selectedTenantManagers = computed(() => selectedTenantUsers.value.filter((item) => isManagerUser(item)));
const selectedTenantStaff = computed(() => selectedTenantUsers.value.filter((item) => !isManagerUser(item)));
const selectedTenantSites = computed(() => sites.value.filter((item) => item.tenant_code === selectedTenantCode.value));
const selectedTenantProjects = computed(() => projects.value.filter((item) => item.tenant_code === selectedTenantCode.value));
const selectedTenantDeviceGroups = computed(() => deviceGroups.value.filter((item) => item.tenant_code === selectedTenantCode.value));
const selectedTenantOperationLogs = computed(() => operationLogs.value);
const pagedOperationLogs = computed(() => {
  const start = (operationLogPage.value - 1) * operationLogPageSize.value;
  return selectedTenantOperationLogs.value.slice(start, start + operationLogPageSize.value);
});

const filteredRoleDefs = computed(() => {
  const keyword = String(roleKeyword.value || "").trim().toLowerCase();
  if (!keyword) return roleDefs.value;
  return roleDefs.value.filter((item) => [item.name, roleLabel(item.name), item.description || ""].join(" ").toLowerCase().includes(keyword));
});

const permissionGroups = computed(() => {
  const keyword = String(permissionKeyword.value || "").trim().toLowerCase();
  const groupMap = new Map();
  for (const item of permissionOptions.value) {
    if (keyword) {
      const haystack = [item.key, item.label, item.description].join(" ").toLowerCase();
      if (!haystack.includes(keyword)) continue;
    }
    const group = resolvePermissionGroup(item.key);
    if (!groupMap.has(group.key)) groupMap.set(group.key, { ...group, items: [] });
    groupMap.get(group.key).items.push(item);
  }
  return Array.from(groupMap.values());
});

const currentRoleOptions = computed(() =>
  userDialogMode.value === "manager" ? roleDefs.value.filter((item) => item.name !== "operator") : roleDefs.value
);

const regionOptionsForTenant = computed(() => {
  const map = new Map();
  for (const site of selectedTenantSites.value) {
    const region = String(site.region || "").trim();
    if (region && !map.has(region)) map.set(region, { value: region, label: region });
  }
  return Array.from(map.values());
});

const roleLabel = (name) => roleLabelMap[name] || name;

const tenantTypeLabel = (type) => {
  if (type === "subsidiary") return "子公司";
  if (type === "customer") return "客户";
  if (type === "headquarters") return "总部";
  return type || "-";
};

const permissionLabel = (key) => permissionOptions.value.find((item) => item.key === key)?.label || key;

const summarizePermissions = (permissions) => {
  const labels = (permissions || []).map((item) => permissionLabel(item));
  if (!labels.length) return "-";
  if (labels.length <= 3) return labels.join("、");
  return `${labels.slice(0, 3).join("、")} 等 ${labels.length} 项`;
};

const formatRoleNames = (roles) => (roles || []).map((item) => roleLabel(item)).join("、") || "-";
const formatDataScopes = (scopes) =>
  (scopes || [])
    .map((item) => `${scopeTypeLabel(item.scope_type)}：${item.scope_name || item.scope_value}`)
    .join("；") || "-";

const scopeTypeLabel = (type) => {
  if (type === "all") return "全部";
  if (type === "tenant") return "公司";
  if (type === "project") return "项目";
  if (type === "site") return "站点";
  if (type === "device_group") return "设备组";
  if (type === "region") return "区域";
  if (type === "custom") return "自定义";
  return type;
};

const customScopeSiteSummary = (item) => {
  const resourceIds = Array.isArray(item?.resource_ids) ? item.resource_ids : [];
  const labels = resourceIds
    .map((resourceId) => selectedTenantSites.value.find((site) => site.id === resourceId))
    .filter(Boolean)
    .map((site) => site.name);
  if (!labels.length) return "-";
  if (labels.length <= 3) return labels.join("、");
  return `${labels.slice(0, 3).join("、")} 等 ${labels.length} 个站点`;
};

const projectNameById = (projectId) => selectedTenantProjects.value.find((item) => item.id === projectId)?.name || "-";
const siteNameById = (siteId) => selectedTenantSites.value.find((item) => item.id === siteId)?.name || "-";
const formatDateTime = (value) => {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
};

const operationActionLabel = (action) => {
  const labels = {
    "user.create": "创建用户",
    "user.update": "更新用户",
    "user.delete": "删除用户",
    "user.batch_create": "批量创建用户",
    "user.batch_create_item": "批量创建条目",
    "project.create": "创建项目",
    "project.update": "更新项目",
    "project.delete": "删除项目",
    "device_group.create": "创建设备组",
    "device_group.update": "更新设备组",
    "device_group.delete": "删除设备组",
    "custom_scope.create": "创建自定义范围",
    "custom_scope.update": "更新自定义范围",
    "custom_scope.delete": "删除自定义范围",
  };
  return labels[action] || action;
};

const isManagerUser = (user) => {
  const roles = new Set(user.roles || []);
  return roles.has("admin") || roles.has("hq_noc") || roles.has("sub_noc") || roles.has("user.manage");
};

const resolvePermissionGroup = (key) => {
  if (key.startsWith("dashboard.")) return { key: "dashboard", label: "平台总览" };
  if (key.startsWith("realtime.")) return { key: "realtime", label: "实时监控" };
  if (key.startsWith("alarm_rule.template.")) return { key: "template", label: "总部规则模板" };
  if (key.startsWith("alarm_rule.tenant.")) return { key: "tenant_rule", label: "租户监控策略" };
  if (key.startsWith("notify.channel.")) return { key: "notify_channel", label: "通知通道" };
  if (key.startsWith("notify.policy.")) return { key: "notify_policy", label: "通知策略" };
  if (key.startsWith("alarm.")) return { key: "alarm", label: "告警中心" };
  if (key.startsWith("history.") || key.startsWith("report.")) return { key: "history", label: "历史与报表" };
  if (key.startsWith("device.")) return { key: "device", label: "设备控制" };
  if (key.startsWith("site.")) return { key: "site", label: "站点管理" };
  if (key.startsWith("user.")) return { key: "user", label: "账号与角色" };
  return { key: "other", label: "其他" };
};

const extraScopeOptions = (scopeType) => {
  if (scopeType === "project") return selectedTenantProjects.value.map((item) => ({ value: item.code, label: `${item.name}（${item.code}）` }));
  if (scopeType === "site") return selectedTenantSites.value.map((item) => ({ value: item.code, label: `${item.name}（${item.code}）` }));
  if (scopeType === "device_group") return selectedTenantDeviceGroups.value.map((item) => ({ value: item.code, label: `${item.name}（${item.code}）` }));
  if (scopeType === "region") return regionOptionsForTenant.value;
  if (scopeType === "custom") return customScopeSets.value.map((item) => ({ value: String(item.id), label: `${item.name}（${item.item_count}个站点）` }));
  return [];
};

const scopePlaceholder = (scopeType) => {
  if (scopeType === "project") return "选择项目";
  if (scopeType === "site") return "选择站点";
  if (scopeType === "device_group") return "选择设备组";
  if (scopeType === "region") return "选择区域";
  if (scopeType === "custom") return "选择自定义范围";
  return "选择范围";
};
const resetTenantForm = () => {
  tenantForm.code = "";
  tenantForm.name = "";
  tenantForm.tenant_type = "subsidiary";
  tenantForm.parent_code = "";
};

const resetUserForm = () => {
  editingUserId.value = null;
  form.username = "";
  form.full_name = "";
  form.password = "";
  form.is_active = true;
  form.primary_role = userDialogMode.value === "manager" ? "sub_noc" : "operator";
  form.role_names = [form.primary_role];
  form.extra_scopes = [];
};

const resetRoleForm = () => {
  roleEditingId.value = null;
  roleForm.name = "";
  roleForm.description = "";
  roleForm.template_key = "";
  roleForm.permissions = [];
  roleForm.is_builtin = false;
  permissionKeyword.value = "";
};

const resetProjectForm = () => {
  projectEditingId.value = null;
  projectForm.code = "";
  projectForm.name = "";
  projectForm.status = "active";
};

const resetBatchForm = () => {
  batchForm.primary_role = "operator";
  batchForm.default_password = "";
  batchForm.on_existing = "skip";
  batchForm.rows_text = "";
};

const buildOperationLogQuery = (tenantCode) => {
  const params = new URLSearchParams({ tenant_code: tenantCode });
  params.set("limit", "200");
  if (operationLogFilters.action) params.set("action", operationLogFilters.action);
  if (operationLogFilters.operator_keyword) params.set("operator_keyword", operationLogFilters.operator_keyword.trim());
  if (Array.isArray(operationLogFilters.date_range) && operationLogFilters.date_range.length === 2) {
    if (operationLogFilters.date_range[0]) params.set("date_from", operationLogFilters.date_range[0]);
    if (operationLogFilters.date_range[1]) params.set("date_to", operationLogFilters.date_range[1]);
  }
  return params.toString();
};

const resetDeviceGroupForm = () => {
  deviceGroupEditingId.value = null;
  deviceGroupForm.code = "";
  deviceGroupForm.name = "";
  deviceGroupForm.project_id = null;
  deviceGroupForm.site_id = null;
};

const resetCustomScopeForm = () => {
  customScopeEditingId.value = null;
  customScopeForm.name = "";
  customScopeForm.resource_ids = [];
};

const syncRolesFromPrimary = () => {
  form.role_names = form.primary_role ? [form.primary_role] : [];
};

const resetToTenantScope = () => {
  form.extra_scopes = [];
};

const addExtraScope = () => {
  form.extra_scopes.push({ scope_type: "project", scope_value: "" });
};

const removeExtraScope = (index) => {
  form.extra_scopes.splice(index, 1);
};

const buildUserPayload = () => {
  const username = String(form.username || "").trim();
  if (!selectedTenant.value) throw new Error("请先选择公司");
  if (!username) throw new Error("用户名不能为空");
  if (username.length < 3 || username.length > 64) throw new Error("用户名长度必须在 3-64 位之间");
  if (!editingUserId.value && String(form.password || "").length < 6) throw new Error("密码长度至少 6 位");
  if ((form.password || "") && String(form.password).length < 6) throw new Error("密码长度至少 6 位");
  if (!form.primary_role) throw new Error("请选择角色");

  const scopeMap = new Map();
  scopeMap.set(`tenant:${selectedTenant.value.code}`, { scope_type: "tenant", scope_value: selectedTenant.value.code });
  for (const item of form.extra_scopes) {
    const scopeType = String(item.scope_type || "").trim();
    const scopeValue = String(item.scope_value || "").trim();
    if (!scopeType || !scopeValue) throw new Error("请完整填写附加范围");
    scopeMap.set(`${scopeType}:${scopeValue}`, { scope_type: scopeType, scope_value: scopeValue });
  }

  return {
    username,
    full_name: String(form.full_name || "").trim() || null,
    password: editingUserId.value ? String(form.password || "") || null : String(form.password || ""),
    is_active: form.is_active,
    role_names: [...form.role_names],
    data_scopes: Array.from(scopeMap.values()),
    tenant_roles: [{ tenant_code: selectedTenant.value.code, role_name: form.primary_role }],
  };
};

const loadRoleDefs = async () => {
  const res = await http.get("/users/role-defs");
  roleDefs.value = Array.isArray(res.data) ? res.data : [];
};

const loadMeta = async () => {
  const res = await http.get("/users/meta");
  permissionOptions.value = Array.isArray(res.data?.permission_options) ? res.data.permission_options : [];
};

const loadTenantScopedData = async (tenantCode) => {
  if (!tenantCode) {
    projects.value = [];
    deviceGroups.value = [];
    customScopeSets.value = [];
    operationLogs.value = [];
    return;
  }
  const [projectRes, deviceGroupRes, customScopeRes, operationLogRes] = await Promise.all([
    http.get(`/projects?tenant_code=${tenantCode}`),
    http.get(`/device-groups?tenant_code=${tenantCode}`),
    http.get(`/custom-scope-sets?tenant_code=${tenantCode}`),
    http.get(`/operation-logs?${buildOperationLogQuery(tenantCode)}`),
  ]);
  projects.value = Array.isArray(projectRes.data) ? projectRes.data : [];
  deviceGroups.value = Array.isArray(deviceGroupRes.data) ? deviceGroupRes.data : [];
  customScopeSets.value = Array.isArray(customScopeRes.data) ? customScopeRes.data : [];
  operationLogs.value = Array.isArray(operationLogRes.data) ? operationLogRes.data : [];
  operationLogPage.value = 1;
};

const loadData = async () => {
  const [userRes, tenantRes, siteRes] = await Promise.all([http.get("/users"), http.get("/tenants"), http.get("/sites"), loadRoleDefs(), loadMeta()]);
  rows.value = Array.isArray(userRes.data) ? userRes.data : [];
  tenants.value = Array.isArray(tenantRes.data) ? tenantRes.data : [];
  sites.value = Array.isArray(siteRes.data) ? siteRes.data : [];
  if (!selectedTenantCode.value && tenants.value.length) selectedTenantCode.value = tenants.value[0].code;
  if (selectedTenantCode.value && !tenants.value.some((item) => item.code === selectedTenantCode.value)) {
    selectedTenantCode.value = tenants.value[0]?.code || "";
  }
  await loadTenantScopedData(selectedTenantCode.value);
};

const selectTenant = (tenantCode) => {
  selectedTenantCode.value = tenantCode;
};

const openTenantCreate = () => {
  resetTenantForm();
  tenantDialogVisible.value = true;
};

const submitTenant = async () => {
  try {
    const payload = {
      code: String(tenantForm.code || "").trim().toUpperCase(),
      name: String(tenantForm.name || "").trim(),
      tenant_type: tenantForm.tenant_type,
      parent_code: String(tenantForm.parent_code || "").trim() || null,
    };
    await http.post("/tenants", payload);
    tenantDialogVisible.value = false;
    await loadData();
    selectedTenantCode.value = payload.code;
    activeTenantTab.value = "managers";
    openCreateUserForTenant("manager");
    ElMessage.success("公司已创建，请继续添加管理员");
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "新增公司失败");
  }
};

const openCreateUserForTenant = (mode) => {
  userDialogMode.value = mode;
  resetUserForm();
  userDialogVisible.value = true;
};

const openBatchCreate = () => {
  resetBatchForm();
  batchDialogVisible.value = true;
};

const downloadBatchTemplate = () => {
  const content = [
    "# 每行一个员工，格式：用户名,姓名,密码（密码可省略）",
    "# 密码留空时使用上方默认密码",
    "a_user01,张三,abc12345",
    "a_user02,李四,",
  ].join("\r\n");
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "批量创建员工模板.txt";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};

const openEdit = (row) => {
  const tenantScope = (row.data_scopes || []).find((item) => item.scope_type === "tenant") || null;
  if (tenantScope) selectedTenantCode.value = tenantScope.scope_value;
  editingUserId.value = row.id;
  userDialogMode.value = isManagerUser(row) ? "manager" : "staff";
  form.username = row.username || "";
  form.full_name = row.full_name || "";
  form.password = "";
  form.is_active = Boolean(row.is_active);
  form.primary_role = (row.roles || [])[0] || (userDialogMode.value === "manager" ? "sub_noc" : "operator");
  form.role_names = [form.primary_role];
  form.extra_scopes = (row.data_scopes || [])
    .filter((item) => item.scope_type !== "tenant" && item.scope_type !== "all")
    .map((item) => ({ scope_type: item.scope_type, scope_value: item.scope_value }));
  userDialogVisible.value = true;
};

const submitUser = async () => {
  try {
    submitLoading.value = true;
    const payload = buildUserPayload();
    if (editingUserId.value) {
      await http.put(`/users/${editingUserId.value}`, payload);
      ElMessage.success("用户已更新");
    } else {
      await http.post("/users", payload);
      ElMessage.success(userDialogMode.value === "manager" ? "管理员已创建" : "员工已创建");
    }
    userDialogVisible.value = false;
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "用户保存失败");
  } finally {
    submitLoading.value = false;
  }
};

const toggleActive = async (row) => {
  try {
    const payload = {
      username: row.username,
      full_name: row.full_name,
      password: null,
      is_active: !row.is_active,
      role_names: row.roles || [],
      data_scopes: (row.data_scopes || []).map((item) => ({ scope_type: item.scope_type, scope_value: item.scope_value })),
      tenant_roles: (row.tenant_roles || []).map((item) => ({ tenant_code: item.tenant_code, role_name: item.role_name })),
    };
    await http.put(`/users/${row.id}`, payload);
    ElMessage.success(`用户已${row.is_active ? "停用" : "启用"}`);
    await loadData();
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || "状态更新失败");
  }
};

const removeUser = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除用户 ${row.username} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/users/${row.id}`);
    ElMessage.success("用户已删除");
    await loadData();
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || "删除用户失败");
  }
};

const parseBatchItems = () => {
  const lines = String(batchForm.rows_text || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!lines.length) {
    throw new Error("请至少填写一条员工记录");
  }

  return lines.map((line, index) => {
    const parts = line.split(/[，,]/).map((item) => item.trim());
    const username = parts[0] || "";
    const fullName = parts[1] || null;
    const password = parts[2] || null;
    if (!username) {
      throw new Error(`第 ${index + 1} 行缺少用户名`);
    }
    return {
      username,
      full_name: fullName,
      password,
    };
  });
};

const formatBatchResultMessage = (data) => {
  const createdItems = Array.isArray(data?.created_items) ? data.created_items : [];
  const failedItems = Array.isArray(data?.failed_items) ? data.failed_items : [];
  const lines = [
    `成功 ${data?.created_count || 0} 条`,
    `更新 ${data?.updated_count || 0} 条`,
    `跳过 ${data?.skipped_count || 0} 条`,
    `失败 ${data?.failed_count || 0} 条`,
  ];
  if (createdItems.length) {
    lines.push("", "成功记录：");
    for (const item of createdItems) {
      lines.push(`- ${item.username}：${item.message}`);
    }
  }
  const updatedItems = Array.isArray(data?.updated_items) ? data.updated_items : [];
  if (updatedItems.length) {
    lines.push("", "更新记录：");
    for (const item of updatedItems) {
      lines.push(`- ${item.username}：${item.message}`);
    }
  }
  const skippedItems = Array.isArray(data?.skipped_items) ? data.skipped_items : [];
  if (skippedItems.length) {
    lines.push("", "跳过记录：");
    for (const item of skippedItems) {
      lines.push(`- ${item.username}：${item.message}`);
    }
  }
  if (failedItems.length) {
    lines.push("", "失败记录：");
    for (const item of failedItems) {
      lines.push(`- ${item.username || "未命名"}：${item.message}`);
    }
  }
  return lines.join("\n");
};

const submitBatchCreate = async () => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    if (!batchForm.primary_role) throw new Error("请选择默认角色");

    const items = parseBatchItems();
    batchSubmitLoading.value = true;
    const payload = {
      items,
      default_password: String(batchForm.default_password || "").trim() || null,
      on_existing: batchForm.on_existing,
      role_names: [batchForm.primary_role],
      tenant_roles: [{ tenant_code: selectedTenant.value.code, role_name: batchForm.primary_role }],
      data_scopes: [{ scope_type: "tenant", scope_value: selectedTenant.value.code }],
    };
    const res = await http.post("/users/batch", payload);
    batchDialogVisible.value = false;
    await loadData();
    await ElMessageBox.alert(formatBatchResultMessage(res.data), "批量创建结果", {
      confirmButtonText: "知道了",
    });
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "批量创建失败");
  } finally {
    batchSubmitLoading.value = false;
  }
};

const openRoleManager = async () => {
  await Promise.all([loadRoleDefs(), loadMeta()]);
  roleDialogVisible.value = true;
};

const openProjectCreate = () => {
  resetProjectForm();
  projectDialogVisible.value = true;
};

const openProjectEdit = (row) => {
  projectEditingId.value = row.id;
  projectForm.code = row.code || "";
  projectForm.name = row.name || "";
  projectForm.status = row.status || "active";
  projectDialogVisible.value = true;
};

const openDeviceGroupCreate = () => {
  resetDeviceGroupForm();
  deviceGroupDialogVisible.value = true;
};

const openDeviceGroupEdit = (row) => {
  deviceGroupEditingId.value = row.id;
  deviceGroupForm.code = row.code || "";
  deviceGroupForm.name = row.name || "";
  deviceGroupForm.project_id = row.project_id || null;
  deviceGroupForm.site_id = row.site_id || null;
  deviceGroupDialogVisible.value = true;
};

const openCustomScopeCreate = () => {
  resetCustomScopeForm();
  customScopeDialogVisible.value = true;
};

const openCustomScopeEdit = (row) => {
  customScopeEditingId.value = row.id;
  customScopeForm.name = row.name || "";
  customScopeForm.resource_ids = Array.isArray(row.resource_ids) ? [...row.resource_ids] : [];
  customScopeDialogVisible.value = true;
};

const openRoleCreate = () => {
  resetRoleForm();
  roleEditVisible.value = true;
};

const openRoleEdit = (row) => {
  roleEditingId.value = row.id;
  roleForm.name = row.name || "";
  roleForm.description = row.description || "";
  roleForm.template_key = "";
  roleForm.permissions = [...(row.permissions || [])];
  roleForm.is_builtin = Boolean(row.is_builtin);
  permissionKeyword.value = "";
  roleEditVisible.value = true;
};

const copyRole = (row) => {
  resetRoleForm();
  roleForm.name = `${row.name}_copy`;
  roleForm.description = row.description || `${roleLabel(row.name)}复制版`;
  roleForm.permissions = [...(row.permissions || [])];
  roleEditVisible.value = true;
};

const selectAllPermissions = () => {
  roleForm.permissions = permissionOptions.value.map((item) => item.key);
};

const clearPermissions = () => {
  roleForm.permissions = [];
};

const applyPreset = (keys) => {
  const allowed = new Set(permissionOptions.value.map((item) => item.key));
  roleForm.permissions = Array.from(new Set(keys.filter((key) => allowed.has(key)))).sort();
};

const applyTemplateByKey = (key) => {
  const preset = rolePresets.find((item) => item.key === key);
  if (preset) applyPreset(preset.keys);
};

const toggleGroup = (items, checked) => {
  const current = new Set(roleForm.permissions);
  for (const item of items) {
    if (checked) current.add(item.key);
    else current.delete(item.key);
  }
  roleForm.permissions = Array.from(current).sort();
};

const submitRole = async () => {
  try {
    const name = String(roleForm.name || "").trim();
    if (!name) throw new Error("角色标识不能为空");
    if (!roleForm.is_builtin && roleForm.permissions.length === 0) throw new Error("请至少选择一项功能权限");
    const payload = { name, description: String(roleForm.description || "").trim() || null, permissions: roleForm.permissions };
    if (roleEditingId.value) {
      await http.put(`/users/role-defs/${roleEditingId.value}`, payload);
      ElMessage.success("角色已更新");
    } else {
      await http.post("/users/role-defs", payload);
      ElMessage.success("角色已创建");
    }
    roleEditVisible.value = false;
    await Promise.all([loadRoleDefs(), loadData()]);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "角色保存失败");
  }
};

const deleteRole = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除角色 ${roleLabel(row.name)} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/users/role-defs/${row.id}`);
    ElMessage.success("角色已删除");
    await Promise.all([loadRoleDefs(), loadData()]);
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || "删除角色失败");
  }
};

const submitCustomScope = async () => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    const name = String(customScopeForm.name || "").trim();
    if (!name) throw new Error("范围名称不能为空");
    if (!customScopeForm.resource_ids.length) throw new Error("请至少选择一个站点");

    customScopeSubmitLoading.value = true;
    const payload = {
      name,
      resource_type: "site",
      resource_ids: [...new Set(customScopeForm.resource_ids)],
    };

    if (customScopeEditingId.value) {
      await http.put(`/custom-scope-sets/${customScopeEditingId.value}?tenant_code=${selectedTenant.value.code}`, payload);
      ElMessage.success("自定义范围已更新");
    } else {
      await http.post(`/custom-scope-sets?tenant_code=${selectedTenant.value.code}`, payload);
      ElMessage.success("自定义范围已创建");
    }
    customScopeDialogVisible.value = false;
    await loadTenantScopedData(selectedTenant.value.code);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "自定义范围保存失败");
  } finally {
    customScopeSubmitLoading.value = false;
  }
};

const submitProject = async () => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    const code = String(projectForm.code || "").trim().toUpperCase();
    const name = String(projectForm.name || "").trim();
    if (!code && !projectEditingId.value) throw new Error("项目编码不能为空");
    if (!name) throw new Error("项目名称不能为空");

    projectSubmitLoading.value = true;
    if (projectEditingId.value) {
      await http.put(`/projects/${projectEditingId.value}?tenant_code=${selectedTenant.value.code}`, {
        name,
        status: projectForm.status,
      });
      ElMessage.success("项目已更新");
    } else {
      await http.post(`/projects?tenant_code=${selectedTenant.value.code}`, { code, name });
      ElMessage.success("项目已创建");
    }
    projectDialogVisible.value = false;
    await loadTenantScopedData(selectedTenant.value.code);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "项目保存失败");
  } finally {
    projectSubmitLoading.value = false;
  }
};

const removeProject = async (row) => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    await ElMessageBox.confirm(`确定删除项目 ${row.name} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/projects/${row.id}?tenant_code=${selectedTenant.value.code}`);
    ElMessage.success("项目已删除");
    await loadTenantScopedData(selectedTenant.value.code);
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || e.message || "删除项目失败");
  }
};

const submitDeviceGroup = async () => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    const code = String(deviceGroupForm.code || "").trim().toUpperCase();
    const name = String(deviceGroupForm.name || "").trim();
    if (!code && !deviceGroupEditingId.value) throw new Error("设备组编码不能为空");
    if (!name) throw new Error("设备组名称不能为空");

    deviceGroupSubmitLoading.value = true;
    const payload = {
      name,
      project_id: deviceGroupForm.project_id || null,
      site_id: deviceGroupForm.site_id || null,
    };
    if (deviceGroupEditingId.value) {
      await http.put(`/device-groups/${deviceGroupEditingId.value}?tenant_code=${selectedTenant.value.code}`, payload);
      ElMessage.success("设备组已更新");
    } else {
      await http.post(`/device-groups?tenant_code=${selectedTenant.value.code}`, {
        code,
        ...payload,
      });
      ElMessage.success("设备组已创建");
    }
    deviceGroupDialogVisible.value = false;
    await loadTenantScopedData(selectedTenant.value.code);
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "设备组保存失败");
  } finally {
    deviceGroupSubmitLoading.value = false;
  }
};

const removeDeviceGroup = async (row) => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    await ElMessageBox.confirm(`确定删除设备组 ${row.name} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/device-groups/${row.id}?tenant_code=${selectedTenant.value.code}`);
    ElMessage.success("设备组已删除");
    await loadTenantScopedData(selectedTenant.value.code);
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || e.message || "删除设备组失败");
  }
};

const removeCustomScope = async (row) => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    await ElMessageBox.confirm(`确定删除自定义范围 ${row.name} 吗？`, "删除确认", { type: "warning" });
    await http.delete(`/custom-scope-sets/${row.id}?tenant_code=${selectedTenant.value.code}`);
    ElMessage.success("自定义范围已删除");
    await loadTenantScopedData(selectedTenant.value.code);
  } catch (e) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.response?.data?.detail || e.message || "删除自定义范围失败");
  }
};

const reloadOperationLogs = async () => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    const res = await http.get(`/operation-logs?${buildOperationLogQuery(selectedTenant.value.code)}`);
    operationLogs.value = Array.isArray(res.data) ? res.data : [];
    operationLogPage.value = 1;
    ElMessage.success("操作记录已刷新");
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "刷新操作记录失败");
  }
};

const exportOperationLogs = async () => {
  try {
    if (!selectedTenant.value) throw new Error("请先选择公司");
    const res = await http.get(`/operation-logs/export?${buildOperationLogQuery(selectedTenant.value.code)}`, {
      responseType: "blob",
    });
    const blob = new Blob([res.data], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${selectedTenant.value.code}_operation_logs.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    ElMessage.success("操作记录已导出");
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || "导出操作记录失败");
  }
};

onMounted(() => {
  loadData().catch((e) => {
    ElMessage.error(e?.response?.data?.detail || "加载公司与人员数据失败");
  });
});

watch(selectedTenantCode, async (tenantCode) => {
  try {
    await loadTenantScopedData(tenantCode);
  } catch (_e) {
    // 选项加载失败时由具体操作再提示
  }
});
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.page-head h2 {
  margin: 0;
  font-size: 24px;
}

.page-head p {
  margin: 6px 0 0;
  color: #64748b;
}

.head-actions,
.summary-actions,
.tab-toolbar,
.role-toolbar,
.preset-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.company-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
}

.company-pane,
.detail-pane {
  background: #fff;
  border: 1px solid #dbe4f0;
  border-radius: 16px;
  padding: 16px;
}

.company-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.company-item {
  text-align: left;
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  padding: 12px;
  background: #f8fbff;
  cursor: pointer;
}

.company-item.active {
  border-color: #1d4ed8;
  background: #eff6ff;
}

.company-item strong,
.role-name-cell strong {
  display: block;
  color: #0f172a;
}

.company-item small,
.role-name-cell small {
  color: #64748b;
}

.tenant-summary {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.tenant-summary h3 {
  margin: 0;
  font-size: 22px;
}

.tenant-summary p {
  margin: 6px 0 0;
  color: #64748b;
}

.tab-toolbar {
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: #64748b;
}

.inline-link {
  color: #2563eb;
  text-decoration: none;
}
.panel {
  padding: 14px;
  margin-bottom: 16px;
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}

.panel-tip,
.field-tip {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.grid {
  display: grid;
  gap: 12px;
}

.grid-two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.scope-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.permission-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  width: 100%;
}

.permission-grid :deep(.el-checkbox) {
  display: flex;
  align-items: flex-start;
  margin-right: 0;
  padding: 10px 12px;
  border: 1px solid #dbe4f0;
  border-radius: 10px;
  background: #fff;
}

.permission-grid small {
  display: block;
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
}

.empty-inline,
.empty-block,
.empty-state {
  color: #94a3b8;
}

.empty-state {
  display: grid;
  place-items: center;
  min-height: 320px;
  text-align: center;
}

@media (max-width: 1080px) {
  .company-layout {
    grid-template-columns: 1fr;
  }

  .tenant-summary,
  .tab-toolbar,
  .role-toolbar,
  .page-head {
    flex-direction: column;
    align-items: stretch;
  }

  .grid-two {
    grid-template-columns: 1fr;
  }

  .scope-row {
    flex-direction: column;
    align-items: stretch;
  }

  .permission-grid {
    grid-template-columns: 1fr;
  }
}
</style>


