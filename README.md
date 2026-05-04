# IronMail

这是邮件批量发送工具的工程化版本，当前默认启动 Windows 图形界面。

## 目录

- `send_emails.py`: 根目录启动入口，保留旧运行方式
- `src/ironmail/`: 核心源码目录
- `server/ironmail_license/`: 授权码后台和验证接口
- `config/config.example.yaml`: 可提交的示例配置
- `config/config.yaml`: 本地配置文件，不提交到 Git，正常使用时通过图形界面修改
- `Mails/收件名单/`: 收件人表格目录，所有 `.xlsx` / `.xlsm` / `.xls` / `.csv` 名单都放这里
- `Mails/邮件模板/`: 邮件模板目录，所有 `.md` 邮件模板都放这里
- `Mails/邮件模板/README.md`: 模板写法和变量说明
- `scripts/`: Windows 运行和打包脚本
- `logs/`: 日志目录
- `docs/`: 项目文档目录
- `requirements.txt`: Python 依赖

## 运行源码

在 Windows 命令行里执行：

```bat
scripts\run_source_windows.bat
```

或者在项目根目录执行：

```bat
py -m pip install -r requirements.txt
py send_emails.py
```

第一次运行前，如果没有 `config/config.yaml`，可以复制示例配置：

```bat
copy config\config.example.yaml config\config.yaml
```

程序会先联网验证授权码。验证失败、过期、禁用、绑定了其他电脑，或者连不上授权服务器，都会停止发送。

启动后会进入 IronMail 窗口，常用功能都可以在界面里完成：

- `发送邮件`: 选择收件名单，再选择邮件模板后开始发送
- `发件邮箱`: 查看、新增、修改、删除发件邮箱，并测试 SMTP 登录
- `收件名单`: 打开收件名单文件夹、导入表格、修改表头变量、删除表格
- `邮件模板`: 查看、新增、编辑、打开、删除 `.md` 邮件模板
- `配置`: 修改授权码、SMTP、出网代理和发送参数
- `日志`: 查看发送日志和错误日志

发件邮箱支持 Gmail、GMX、Google Workspace 和其他标准 SMTP 邮箱。新增发件邮箱时，常见邮箱会按域名自动带出 SMTP：

```text
Gmail: 直接回车使用默认SMTP设置
GMX:   直接回车使用默认SMTP设置
```

新增 Gmail 或 GMX 邮箱时，SMTP 服务器直接回车即可使用自动识别的配置。Gmail 账号需要先在 Google 账号安全设置里生成应用专用密码；GMX 请填写可用于 SMTP 的密码或应用密码。

新增多个发件邮箱后，程序会按 `每个邮箱连续发送几封后切换` 的设置自动轮询。默认值是 `1`，也就是每发 1 封切换下一个邮箱。

## 断点续发

发送过程中每成功一封邮件，程序都会把进度写入 `logs/progress/`。如果网络中断、SMTP失败或程序退出，下次选择同一个收件名单和同一个模板时，界面会提示：

```text
输入 Y 继续未完成部分 / R 重新发送全部 / N 返回菜单
```

- `Y`: 跳过已经成功发送的行，只继续未完成部分
- `R`: 清空旧进度，从第一行重新发送
- `N`: 不发送，返回菜单

如果这组名单上次已经全部发送完成，再次运行时会提示是否重新发送，默认可以选择 `N` 避免重复发邮件。

## 表格和模板规则

收件名单统一放在 `Mails/收件名单/` 目录。`config/config.yaml` 里的 `excel_file` 留空时，程序会在开始发送前列出这个目录里的 `.xlsx` / `.xlsm` / `.xls` / `.csv` 文件，让用户选择本次要发送的表格。CSV 会自动兼容 UTF-8、GBK/GB18030、UTF-16 等常见编码，以及逗号、分号、Tab 等常见分隔符。

新流程推荐把邮件主题和正文放在 `Mails/邮件模板/` 里的 `.md` 模板文件中。发送前程序会在选择收件名单后继续选择邮件模板，然后按每一行数据替换模板变量。

收件名单最低需要 `邮箱` 字段。常用字段如下：

```text
邮箱
网页
公司名
联系人
法人
备注
```

模板格式示例：

```text
邮件主题：关于 {{网页}} 的合作沟通

邮件正文：
{{法人}}您好，

我看到贵司网站是 {{网页}}，想和贵司简单沟通一下合作机会。
```

变量写法是 `{{字段名}}`，字段名必须和收件名单的表头一致。更详细的模板教学在 `Mails/邮件模板/README.md`。

旧表仍然兼容。如果旧表里已有 `邮箱`、`邮件主题`、`邮件正文` 三列，发送时可以选择不使用模板，继续按表格里的主题和正文发送。

## 授权码

授权码后台地址：

```text
https://tmpmail.oldiron.us/admin/login
```

客户端授权码建议在窗口的 `配置` 页填写。配置文件里的结构如下：

```yaml
license:
  server_url: https://tmpmail.oldiron.us
  code: IM-XXXXXX-XXXXXX-XXXXXX-XXXXXX
  timeout_seconds: 10
```

## Windows 打包

在 PowerShell 里执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build_windows.ps1
```

打包脚本会自动安装依赖、执行 PyInstaller，并把 `config/`、`Mails/` 复制到 `dist/`。打包完成后，新 exe 会在：

```text
dist\IronMail.exe
```

运行 exe 前，请检查：

```text
dist\config\config.yaml
```

发件邮箱建议通过程序窗口配置，或者在本地配置文件里填写。这个配置文件可能包含邮箱应用专用密码，不要提交到 Git。

## 未包含文件

- `自动emails_ABRS.exe`
- `用户配置.ini`
- `显示闪屏的软件信息.bat`
- 原目录里的打包 DLL
