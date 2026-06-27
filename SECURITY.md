# 项目安全保护措施

## 当前状态

| 层级 | 措施 | 说明 |
|---|---|---|
| 代码存储 | 本地 Git (无远程) | 代码仅在 Android Termux 本地，未推送任何远程仓库 |
| 版权声明 | LICENSE + 文件头 | 8 个核心文件含版权头，专有软件保留所有权利 |
| 敏感文件 | .gitignore | keystore/key/证书/凭证 绝不入库 |
| 物理隔离 | Android 手机 | 代码在个人设备，非云端 |

## 风险与应对

| 风险 | 应对 |
|---|---|
| 手机丢失 | 定期备份到加密 U 盘或私有 NAS |
| 误推到公开仓库 | `git remote -v` 确认无远程；推送前检查 |
| 第三方库依赖 | 零外部依赖 — 纯 Python 标准库 |
| APK 反编译 | 如打包 APK，使用 PyArmor 或 Cython 编译 |

## 如需分享代码

1. **给投资人看**：现场演示 + 签署 NDA 后给只读 PDF 技术白皮书
2. **给合作开发者**：签署保密协议 + 按模块分配（不给完整代码）
3. **千万不要**：传到 GitHub Public / Gitee / 任何公有平台

## 紧急措施

如果怀疑代码已泄露：

```bash
# 1. 确认泄露范围
git log --all --oneline

# 2. 给所有文件加时间戳证据
find . -name "*.py" -exec stat {} \;

# 3. 保留原始 commit 记录作为创作时间证明
git log --all --format="%H %ai %s" > authorship_proof.txt
```

版权所有人: 李桥 (hubeiligang420@gmail.com)
