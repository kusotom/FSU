-- Permission and scope seed for current RBAC + data scope implementation

-- Builtin role permissions
insert into sys_role_permission(role_id, permission_key)
select r.id, p.permission_key
from sys_role r
join (
  values
    ('admin', 'dashboard.view'),
    ('admin', 'realtime.view'),
    ('admin', 'realtime.important.manage'),
    ('admin', 'alarm.view'),
    ('admin', 'alarm.ack'),
    ('admin', 'alarm.close'),
    ('admin', 'history.view'),
    ('admin', 'report.export'),
    ('admin', 'device.command.send'),
    ('admin', 'site.view'),
    ('admin', 'site.create'),
    ('admin', 'site.update'),
    ('admin', 'alarm_rule.template.view'),
    ('admin', 'alarm_rule.template.manage'),
    ('admin', 'alarm_rule.tenant.view'),
    ('admin', 'alarm_rule.tenant.manage'),
    ('admin', 'notify.channel.view'),
    ('admin', 'notify.channel.manage'),
    ('admin', 'notify.policy.view'),
    ('admin', 'notify.policy.manage'),
    ('admin', 'user.view'),
    ('admin', 'user.manage'),
    ('hq_noc', 'dashboard.view'),
    ('hq_noc', 'realtime.view'),
    ('hq_noc', 'alarm.view'),
    ('hq_noc', 'alarm.ack'),
    ('hq_noc', 'alarm.close'),
    ('hq_noc', 'history.view'),
    ('hq_noc', 'site.view'),
    ('hq_noc', 'alarm_rule.template.view'),
    ('hq_noc', 'alarm_rule.template.manage'),
    ('hq_noc', 'notify.channel.view'),
    ('hq_noc', 'notify.channel.manage'),
    ('hq_noc', 'notify.policy.view'),
    ('hq_noc', 'notify.policy.manage'),
    ('sub_noc', 'dashboard.view'),
    ('sub_noc', 'realtime.view'),
    ('sub_noc', 'alarm.view'),
    ('sub_noc', 'alarm.ack'),
    ('sub_noc', 'alarm.close'),
    ('sub_noc', 'history.view'),
    ('sub_noc', 'site.view'),
    ('sub_noc', 'site.create'),
    ('sub_noc', 'site.update'),
    ('sub_noc', 'alarm_rule.tenant.view'),
    ('sub_noc', 'alarm_rule.tenant.manage'),
    ('sub_noc', 'notify.channel.view'),
    ('sub_noc', 'notify.policy.view'),
    ('operator', 'dashboard.view'),
    ('operator', 'realtime.view'),
    ('operator', 'alarm.view'),
    ('operator', 'history.view'),
    ('operator', 'site.view')
) as p(role_name, permission_key) on p.role_name = r.name
on conflict (role_id, permission_key) do nothing;

-- Compatibility permissions for environments still using old keys.
insert into sys_role_permission(role_id, permission_key)
select r.id, p.permission_key
from sys_role r
join (
  values
    ('admin', 'site.manage'),
    ('admin', 'notify.view'),
    ('admin', 'notify.manage'),
    ('hq_noc', 'notify.view'),
    ('hq_noc', 'notify.manage'),
    ('sub_noc', 'site.manage')
) as p(role_name, permission_key) on p.role_name = r.name
on conflict (role_id, permission_key) do nothing;

-- Default data scopes
insert into sys_user_data_scope(user_id, scope_type, scope_value, scope_name)
select u.id, 'all', '*', '全部数据'
from sys_user u
where u.username in ('admin', 'hq_noc')
on conflict (user_id, scope_type, scope_value) do nothing;

insert into sys_user_data_scope(user_id, scope_type, scope_value, scope_name)
select u.id, 'tenant', t.code, t.name
from sys_user u
join tenant t on t.code = 'SUB-A'
where u.username = 'suba_noc'
on conflict (user_id, scope_type, scope_value) do nothing;
