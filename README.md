# WavesActivity

![icon](./ICON.png)

鸣潮（Wuthering Waves）每日活跃度检查与群内推送提醒插件，适用于 [gsuid_core](https://github.com/Stareven233/gsuid_core)。

玩家在群内自行开启推送后，Bot 将每天在指定时间检查其活跃度，若活跃度低于设定阈值，则在绑定群内 @ 玩家提醒。

---

## 部署方式

```
├── gsuid_core
│   ├── gsuid_core
│   │   ├── plugins
│   │   │   ├── XutheringWavesUID
│   │   │   ├── WavesActivity          ← 本插件
```

```shell
cd gsuid_core/gsuid_core/plugins
git clone --depth=1 <your_repo_url> WavesActivity
```

**依赖**：[XutheringWavesUID](https://github.com/tyql688/WutheringWavesUID) 及其数据库表

---

## 使用说明

### 玩家指令（群聊内使用）

| 指令 | 说明 |
|---|---|
| `ww开启活跃度推送` | 开启每日活跃度检查提醒（需已绑定 UID 并登录）|
| `ww关闭活跃度推送` | 关闭每日活跃度检查提醒 |
| `ww活跃度阈值 80` | 设置个人提醒阈值（1~100，低于此值才提醒，默认使用全局配置）|
| `ww推送阈值 80` | 同上 |
| `ww手动检查活跃度` | 立即触发一次活跃度检查（调试用）|
| `ww查看推送时间` | 查看当前推送时间配置、总开关状态及当前时间（调试用）|

> 开启推送后，Bot 将在每日配置的**每个时间点**检查您的活跃度，若不足设定阈值则在本群 @ 您。活跃度达标后不再提醒，否则每个时间点均会提醒（方便避免遗忘）。

### 管理员配置

在 gsuid_core 配置面板中找到 **WavesActivity配置**，可调整以下项目：

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `EnableLivenessPush` | 是否启用活跃度推送功能 | `false` |
| `LivenessPushTime` | 每日推送检查时间，支持多个时间用英文逗号分隔，例如 `12:00,18:00,22:00`。修改后需重启生效 | `22:00` |
| `LivenessThreshold` | 全局默认活跃度阈值（1~100） | `100` |

---

## 数据存储

配置与状态文件位于：

```
gsuid_core/data/WavesActivity/
├── config.json      # 插件配置
└── status.json      # 今日/昨日推送统计
```

---

## 状态面板

在 gsuid_core 状态面板中可查看：

- 今日活跃度通知成功数
- 今日活跃度通知失败数
- 昨日通知总数

---

## 工作流程

1. 玩家在群内发送 `ww开启活跃度推送`，Bot 记录其 UID、绑定群号
2. 每天到达配置的检查时间（支持多个时间点），Bot 遍历所有开启推送的玩家
3. 查询玩家当日活跃度；若低于阈值，则在绑定群内 @ 玩家发送提醒
4. 每到一个检查时间点，若玩家活跃度仍不足则继续提醒；达标后不再提醒
