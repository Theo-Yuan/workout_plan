## 通用错误处理

### 鉴权错误
- `apikey missing` / `apikey invalid`: 让用户回 App 重新申请，然后复制并重新发送最新的 Skill。
- `仅VIP可用`: 当前账号需要会员权限。

### 限频
- 调用过于频繁时服务端返回 `too frequent`，等待响应中 `retry_after_ms` 指定的毫秒数后重试。
