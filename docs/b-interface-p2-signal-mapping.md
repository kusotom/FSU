# B接口 P2-001 SignalIdMap 映射接入

## 映射链路

实时点位映射按以下链路执行：

1. `init_list.ini`
   通过 `DeviceId / DeviceCode` 找到设备定义，提取 `Type`
2. `SignalIdMap.ini`
   按设备类型分组，用 `标准 SignalId -> BaseTypeId 候选`
3. `SignalIdMap-2G.ini`
   作为补充简化映射
4. `MonitorUnits XML`
   用 `BaseTypeId` 或本地 `SignalId` 查找业务点位信息

## 状态定义

- `mapped`
  唯一映射成功，已得到明确业务点位
- `unmapped`
  未找到映射，但实时点位仍保留入库，不丢弃
- `ambiguous`
  找到多个候选，当前保留全部候选，并使用首个候选作为展示主值

## 已验证点位示例

- `418101001 -> I2C温度`
- `418102001 -> I2C湿度`

## 已知限制

1. `SignalIdMap` 多候选时当前不强行唯一化，统一标记为 `ambiguous`
2. 映射失败的点位不会被丢弃，仍以原始 `semaphore_id/raw_xml` 保留
3. 不修改真实设备配置
4. 不默认外呼真实 FSU
