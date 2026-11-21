# 获取并配置 GitHub SSH 密钥

在自己的 Windows PowerShell 中执行。密钥保存在自己的账户目录，私钥内容无需发送给聊天。

## 1. 查看已有密钥

```powershell
Get-ChildItem "$env:USERPROFILE\.ssh" -ErrorAction SilentlyContinue
```

若有 `id_ed25519` 和 `id_ed25519.pub`，可直接进行下一步。前者是私钥文件，后者是用于 GitHub 的公钥。已有的私钥文件名也可能是其他名称。

## 2. 若没有密钥，创建一对

```powershell
ssh-keygen -t ed25519 -C "GitHub" -f "$env:USERPROFILE\.ssh\id_ed25519"
```

按提示设置口令；若已有同名文件，保留原文件，换一个新文件名，例如 `id_ed25519_cet`。

## 3. 将公钥添加到 GitHub

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

复制输出的一整行公钥。打开 [GitHub SSH keys](https://github.com/settings/keys)，点击 **New SSH key**，类型选择 **Authentication Key**，粘贴公钥并保存。确认登录的 GitHub 账户具有目标仓库写入权限。

## 4. 在自己的终端验证

使用 GitHub SSH 认证前，可在自己的终端运行：

    ssh -T git@github.com

只在本机解锁密钥。不要在聊天中发送私钥、私钥路径、口令或令牌，不写进项目配置或 Git。验证成功后也要核对仓库写权限，获授权的变更走独立分支和草稿 PR，不直推主分支。

官方说明：[生成 SSH 密钥并添加到 SSH agent](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent)。
