-- PostgreSQL initialization SQL for FSU monitoring platform MVP

create extension if not exists timescaledb;

create table if not exists site (
  id bigserial primary key,
  code varchar(64) not null unique,
  name varchar(128) not null,
  region varchar(128),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists fsu_device (
  id bigserial primary key,
  site_id bigint not null references site(id),
  code varchar(64) not null unique,
  name varchar(128) not null,
  vendor varchar(64) not null default 'Vertiv e-stone',
  status varchar(32) not null default 'online',
  last_seen_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists monitor_point (
  id bigserial primary key,
  device_id bigint not null references fsu_device(id),
  point_key varchar(64) not null,
  point_name varchar(128) not null,
  category varchar(32) not null default 'power',
  unit varchar(16),
  high_threshold double precision,
  low_threshold double precision
);

create unique index if not exists idx_monitor_point_key on monitor_point(device_id, point_key);

create table if not exists telemetry_latest (
  id bigserial primary key,
  point_id bigint not null unique references monitor_point(id),
  value double precision not null,
  collected_at timestamptz not null,
  updated_at timestamptz not null default now()
);

create table if not exists telemetry_history (
  id bigserial primary key,
  point_id bigint not null references monitor_point(id),
  value double precision not null,
  collected_at timestamptz not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_history_point_time on telemetry_history(point_id, collected_at);
alter table telemetry_history drop constraint if exists telemetry_history_pkey;
alter table telemetry_history add constraint telemetry_history_pkey primary key (id, collected_at);
select create_hypertable(
  'telemetry_history',
  'collected_at',
  if_not_exists => true,
  migrate_data => true,
  chunk_time_interval => interval '1 day'
);
alter table telemetry_history set (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'point_id',
  timescaledb.compress_orderby = 'collected_at DESC'
);
select add_compression_policy('telemetry_history', interval '7 days', if_not_exists => true);
select add_retention_policy('telemetry_history', interval '90 days', if_not_exists => true);

create table if not exists sys_user (
  id bigserial primary key,
  username varchar(64) not null unique,
  password_hash varchar(255) not null,
  full_name varchar(128),
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists sys_role (
  id bigserial primary key,
  name varchar(64) not null unique,
  description varchar(255)
);

create table if not exists sys_user_role (
  user_id bigint not null references sys_user(id),
  role_id bigint not null references sys_role(id),
  primary key(user_id, role_id)
);

create table if not exists alarm_event (
  id bigserial primary key,
  site_id bigint not null references site(id),
  device_id bigint not null references fsu_device(id),
  point_id bigint not null references monitor_point(id),
  alarm_code varchar(64) not null,
  alarm_name varchar(128) not null,
  alarm_level int not null default 2,
  status varchar(16) not null default 'active',
  trigger_value double precision not null,
  content text not null,
  started_at timestamptz not null,
  recovered_at timestamptz,
  acknowledged_at timestamptz,
  acknowledged_by bigint references sys_user(id),
  closed_at timestamptz,
  closed_by bigint references sys_user(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_alarm_status_time on alarm_event(status, started_at desc);
create index if not exists idx_alarm_event_point_status on alarm_event(point_id, status);

create table if not exists alarm_action_log (
  id bigserial primary key,
  alarm_id bigint not null references alarm_event(id),
  action varchar(32) not null,
  operator_id bigint references sys_user(id),
  content varchar(255) not null,
  created_at timestamptz not null default now()
);

create table if not exists alarm_rule (
  id bigserial primary key,
  rule_key varchar(64) not null unique,
  rule_name varchar(128) not null,
  category varchar(32) not null default 'power',
  metric_key varchar(64),
  alarm_code varchar(64) not null,
  comparison varchar(24) not null default 'gt',
  threshold_value double precision,
  duration_seconds int not null default 0,
  alarm_level int not null default 2,
  is_enabled boolean not null default true,
  description varchar(255),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_alarm_rule_metric on alarm_rule(metric_key);
create index if not exists idx_alarm_rule_code on alarm_rule(alarm_code);

create table if not exists alarm_condition_state (
  id bigserial primary key,
  point_id bigint not null references monitor_point(id),
  rule_id bigint not null references alarm_rule(id),
  abnormal_since timestamptz,
  normal_since timestamptz,
  updated_at timestamptz not null default now(),
  unique(point_id, rule_id)
);

create index if not exists idx_alarm_condition_point on alarm_condition_state(point_id);
create index if not exists idx_alarm_condition_rule on alarm_condition_state(rule_id);

create table if not exists notify_channel (
  id bigserial primary key,
  name varchar(64) not null unique,
  channel_type varchar(32) not null,
  endpoint varchar(512) not null,
  secret varchar(255),
  is_enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists notify_policy (
  id bigserial primary key,
  name varchar(64) not null unique,
  channel_id bigint not null references notify_channel(id),
  min_alarm_level int not null default 2,
  event_types varchar(64) not null default 'trigger,recover',
  is_enabled boolean not null default true,
  created_at timestamptz not null default now()
);

create index if not exists idx_notify_policy_channel on notify_policy(channel_id);
