param(
    [string]$Url = "http://127.0.0.1:4098",
    [string]$Token = "",
    [string]$StateRoot = "",
    [int]$Pid = 0
)

if ($Url -like "*://0.0.0.0:*") {
    $Url = $Url.Replace("://0.0.0.0:", "://127.0.0.1:")
}
if ($Url -like "*://[::]:*") {
    $Url = $Url.Replace("://[::]:", "://127.0.0.1:")
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$appIcon = $null
$iconPaths = @(
    (Join-Path $PSScriptRoot "..\assets\icon.ico"),
    (Join-Path $PSScriptRoot "icon.ico"),
    (Join-Path ([System.AppDomain]::CurrentDomain.BaseDirectory) "assets\icon.ico")
)
foreach ($p in $iconPaths) {
    if (Test-Path $p) {
        try { $appIcon = New-Object System.Drawing.Icon($p); break } catch { }
    }
}
if ($null -eq $appIcon) {
    $appIcon = [System.Drawing.SystemIcons]::Application
}

function Open-Dashboard {
    $edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if (-not (Test-Path $edgePath)) {
        $edgePath = "C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    }
    if (Test-Path $edgePath) {
        $tempProfile = Join-Path $env:TEMP "traceforge-rh-edge-profile"
        Start-Process $edgePath -ArgumentList "--app=`"$Url`"", "--user-data-dir=`"$tempProfile`"", "--window-size=1020,740"
    } else {
        Start-Process $Url
    }
}

$contextMenu = New-Object System.Windows.Forms.ContextMenu
$itemOpen = New-Object System.Windows.Forms.MenuItem("📊 打开监控面板(&O)")
$itemOpen.DefaultItem = $true
$itemOpen.add_Click({ Open-Dashboard })
$contextMenu.MenuItems.Add($itemOpen) | Out-Null

$itemBrowser = New-Object System.Windows.Forms.MenuItem("🌐 在默认浏览器中打开(&B)")
$itemBrowser.add_Click({ Start-Process $Url })
$contextMenu.MenuItems.Add($itemBrowser) | Out-Null

if ($StateRoot -and (Test-Path $StateRoot)) {
    $itemFolder = New-Object System.Windows.Forms.MenuItem("📁 打开状态存储目录(&F)")
    $itemFolder.add_Click({ Start-Process "explorer.exe" -ArgumentList $StateRoot })
    $contextMenu.MenuItems.Add($itemFolder) | Out-Null
}

if ($Token) {
    $itemCopy = New-Object System.Windows.Forms.MenuItem("📋 复制连接 Token(&C)")
    $itemCopy.add_Click({
        [System.Windows.Forms.Clipboard]::SetText($Token)
        $notify.ShowBalloonTip(2000, "TraceForge", "Token 已复制到剪贴板", [System.Windows.Forms.ToolTipIcon]::Info)
    })
    $contextMenu.MenuItems.Add($itemCopy) | Out-Null
}

$contextMenu.MenuItems.Add("-") | Out-Null

$itemExit = New-Object System.Windows.Forms.MenuItem("⏹️ 退出 TraceForge 资源宿主(&X)")
$itemExit.add_Click({
    if ($Pid -gt 0) {
        try { Stop-Process -Id $Pid -Force } catch { }
    }
    $notify.Visible = $false
    $notify.Dispose()
    [System.Windows.Forms.Application]::Exit()
})
$contextMenu.MenuItems.Add($itemExit) | Out-Null

$tipText = "TraceForge 资源宿主 ($Url)"
if ($tipText.Length -ge 64) { $tipText = $tipText.Substring(0, 63) }

$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = $appIcon
$notify.Text = $tipText
$notify.ContextMenu = $contextMenu
$notify.Visible = $true

$notify.add_DoubleClick({ Open-Dashboard })
$notify.add_Click({
    param($s, $e)
    if ($e.Button -eq [System.Windows.Forms.MouseButtons]::Left) {
        Open-Dashboard
    }
})

if ($Pid -gt 0) {
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 2000
    $timer.add_Tick({
        $proc = Get-Process -Id $Pid -ErrorAction SilentlyContinue
        if ($null -eq $proc -or $proc.HasExited) {
            $timer.Stop()
            $notify.Visible = $false
            $notify.Dispose()
            [System.Windows.Forms.Application]::Exit()
        }
    })
    $timer.Start()
}

Open-Dashboard
[System.Windows.Forms.Application]::Run()
