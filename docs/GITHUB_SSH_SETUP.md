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

## 4. 给当前聊天提供私钥文件路径

```powershell
Join-Path $env:USERPROFILE '.ssh\id_ed25519'
```

只发送这个命令输出的完整路径，例如 `C:\Users\你的用户名\.ssh\id_ed25519`。不要发送私钥文件内容。Codex 将使用该路径重试推送；若目录存在应用访问限制，会申请对该文件的读取权限。

若密钥设置了口令，可在自己的终端或 SSH agent 中解锁，再继续上传。不要把口令写入项目配置或 Git 文件。

官方说明：[GitHub 生成 SSH 密钥](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent)。

## 当前上传状态

源码已有独立 Git 仓库与功能提交，origin 为 `git@github.com:WhatDoUMing/cet-writing-studio.git`。远端上传暂待凭据配置；未强制推送，也未修改原项目 Git。
