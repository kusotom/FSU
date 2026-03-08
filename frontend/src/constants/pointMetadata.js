export const pointNameZhMap = {
  mains_voltage: "市电电压",
  mains_current: "市电电流",
  mains_frequency: "市电频率",
  mains_power_state: "市电状态",
  rectifier_module_status: "整流模块状态",
  rectifier_output_voltage: "整流输出电压",
  rectifier_output_current: "整流输出电流",
  rectifier_load_rate: "整流负载率",
  rectifier_fault_status: "整流故障状态",
  battery_group_voltage: "电池组电压",
  battery_group_current: "电池组电流",
  battery_cell_voltage_min: "电池单体最小电压",
  battery_cell_voltage_max: "电池单体最大电压",
  battery_temp: "电池温度",
  battery_fault_status: "电池故障状态",
  battery_fuse_status: "电池熔丝状态",
  gen_running_status: "油机运行状态",
  gen_start_failed: "油机启动失败",
  gen_fault_status: "油机故障状态",
  gen_fault: "油机故障状态",
  gen_fuel_level: "油机油位",
  dc_bus_voltage: "直流母线电压",
  dc_branch_current: "直流支路电流",
  dc_breaker_status: "空开状态",
  dc_overcurrent: "直流过流状态",
  spd_failure: "防雷器失效",
  room_temp: "机房温度",
  temp_room: "机房温度",
  room_humidity: "机房湿度",
  hum_room: "机房湿度",
  water_leak_status: "水浸状态",
  smoke_status: "烟雾状态",
  aircon_status: "空调状态",
  aircon_fault: "空调故障",
  ac_running_status: "空调运行状态",
  ac_fault_status: "空调故障状态",
  ac_high_pressure: "空调高压状态",
  ac_low_pressure: "空调低压状态",
  ac_comm_status: "空调通信状态",
  fresh_air_running_status: "新风运行状态",
  fresh_air_fault_status: "新风故障状态",
  access_status: "门禁状态",
  door_access_status: "门禁状态",
  camera_online_status: "摄像头在线状态",
  ups_bypass_status: "UPS旁路状态",
  voltage_a: "A相电压",
  "system:fsu_heartbeat_timeout": "设备心跳超时",
};

export const pointCategoryOrder = ["power", "env", "smart", "other"];

export const pointCategoryLabelMap = {
  power: "动力监控",
  env: "环境监控",
  smart: "智能设备",
  other: "其他",
};

export const hasChineseText = (text) => /[\u4e00-\u9fff]/.test(String(text || ""));

export const inferPointCategory = (pointKey) => {
  const key = String(pointKey || "").toLowerCase();
  if (
    key.includes("mains") ||
    key.includes("rectifier") ||
    key.includes("battery") ||
    key.startsWith("dc_") ||
    key.startsWith("gen_") ||
    key.includes("ups") ||
    key.includes("spd") ||
    key.includes("voltage")
  ) {
    return "power";
  }
  if (
    key.includes("temp") ||
    key.includes("humidity") ||
    key.includes("water") ||
    key.includes("smoke") ||
    key.startsWith("ac_") ||
    key.startsWith("fresh_air") ||
    key.includes("aircon")
  ) {
    return "env";
  }
  if (key.includes("door") || key.includes("camera") || key.includes("access")) return "smart";
  return "other";
};

export const resolvePointDisplayName = (pointKey, pointName = "", fallbackLabel = "未命名监控项") => {
  const key = String(pointKey || "").trim();
  if (!key) return fallbackLabel.replace("{key}", "");
  if (pointNameZhMap[key]) return pointNameZhMap[key];
  const name = String(pointName || "").trim();
  if (hasChineseText(name)) return name;
  return String(fallbackLabel || "未命名监控项").replace("{key}", key);
};
