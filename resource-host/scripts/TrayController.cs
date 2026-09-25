using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("TraceForge Resource Host Tray")]
[assembly: AssemblyDescription("TraceForge Resource Host System Tray Controller")]
[assembly: AssemblyProduct("TraceForge Resource Host")]
[assembly: AssemblyCompany("TraceForge")]
[assembly: AssemblyCopyright("Copyright (C) 2026 TraceForge Team")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace TraceForge {
    static class TrayController {
        static NotifyIcon trayIcon;
        static string dashboardUrl = "http://127.0.0.1:4098";
        static string authToken = "";
        static string stateRoot = "";
        static int parentPid = 0;

        [STAThread]
        static void Main(string[] args) {
            for (int i = 0; i < args.Length; i++) {
                if (args[i] == "--url" && i + 1 < args.Length) dashboardUrl = args[++i];
                else if (args[i] == "--token" && i + 1 < args.Length) authToken = args[++i];
                else if (args[i] == "--state-root" && i + 1 < args.Length) stateRoot = args[++i];
                else if (args[i] == "--pid" && i + 1 < args.Length) int.TryParse(args[++i], out parentPid);
            }

            if (!string.IsNullOrEmpty(dashboardUrl)) {
                dashboardUrl = dashboardUrl.Replace("://0.0.0.0:", "://127.0.0.1:").Replace("://[::]:", "://127.0.0.1:");
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            Icon appIcon = null;
            try {
                string baseDir = AppDomain.CurrentDomain.BaseDirectory;
                string[] possibleIcons = new string[] {
                    Path.Combine(baseDir, "icon.ico"),
                    Path.Combine(baseDir, "assets", "icon.ico"),
                    Path.Combine(baseDir, "..", "assets", "icon.ico")
                };
                foreach (var p in possibleIcons) {
                    if (File.Exists(p)) {
                        appIcon = new Icon(p);
                        break;
                    }
                }
            } catch { }
            if (appIcon == null) appIcon = SystemIcons.Application;

            var contextMenu = new ContextMenu();
            var itemOpen = new MenuItem("📊 打开监控面板(&O)", (s, e) => OpenDashboard());
            itemOpen.DefaultItem = true;
            contextMenu.MenuItems.Add(itemOpen);

            contextMenu.MenuItems.Add(new MenuItem("🌐 在默认浏览器中打开(&B)", (s, e) => {
                try { Process.Start(dashboardUrl); } catch { }
            }));

            if (!string.IsNullOrEmpty(stateRoot)) {
                contextMenu.MenuItems.Add(new MenuItem("📁 打开状态存储目录(&F)", (s, e) => {
                    try {
                        if (Directory.Exists(stateRoot)) Process.Start("explorer.exe", stateRoot);
                    } catch { }
                }));
            }

            if (!string.IsNullOrEmpty(authToken)) {
                contextMenu.MenuItems.Add(new MenuItem("📋 复制连接 Token(&C)", (s, e) => {
                    try {
                        Clipboard.SetText(authToken);
                        if (trayIcon != null) {
                            trayIcon.ShowBalloonTip(2000, "TraceForge", "Token 已复制到剪贴板", ToolTipIcon.Info);
                        }
                    } catch { }
                }));

                contextMenu.MenuItems.Add(new MenuItem("📦 复制前端连接配置(&J)", (s, e) => {
                    try {
                        string json = string.Format("{{\r\n  \"resource_host_url\": \"{0}\",\r\n  \"token\": \"{1}\"\r\n}}", dashboardUrl, authToken);
                        Clipboard.SetText(json);
                        if (trayIcon != null) {
                            trayIcon.ShowBalloonTip(2000, "TraceForge", "前端连接配置 (JSON) 已复制到剪贴板", ToolTipIcon.Info);
                        }
                    } catch { }
                }));
            }

            contextMenu.MenuItems.Add("-");
            contextMenu.MenuItems.Add(new MenuItem("⏹️ 退出 TraceForge 资源宿主(&X)", (s, e) => ExitApplication()));

            string tipText = "TraceForge 资源宿主 (运行中)";
            try {
                var uri = new Uri(dashboardUrl);
                tipText = string.Format("TraceForge 资源宿主 ({0}:{1})", uri.Host, uri.Port);
            } catch { }
            if (tipText.Length >= 64) tipText = tipText.Substring(0, 63);

            trayIcon = new NotifyIcon {
                Icon = appIcon,
                Text = tipText,
                ContextMenu = contextMenu,
                Visible = true
            };

            trayIcon.DoubleClick += (s, e) => OpenDashboard();
            trayIcon.Click += (s, e) => {
                var me = e as MouseEventArgs;
                if (me != null && me.Button == MouseButtons.Left) {
                    OpenDashboard();
                }
            };

            if (parentPid > 0) {
                var monitorThread = new Thread(() => {
                    try {
                        var parent = Process.GetProcessById(parentPid);
                        parent.WaitForExit();
                    } catch { }
                    ExitTrayOnly();
                }) { IsBackground = true };
                monitorThread.Start();
            }

            OpenDashboard();
            Application.Run();
        }

        static void OpenDashboard() {
            try {
                string edgePath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                    @"Microsoft\Edge\Application\msedge.exe"
                );
                if (!File.Exists(edgePath)) {
                    edgePath = Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                        @"Microsoft\Edge\Application\msedge.exe"
                    );
                }

                if (File.Exists(edgePath)) {
                    string userDataDir = Path.Combine(Path.GetTempPath(), "traceforge-rh-edge-profile");
                    string arguments = string.Format("--app=\"{0}\" --user-data-dir=\"{1}\" --window-size=1020,740", dashboardUrl, userDataDir);
                    Process.Start(new ProcessStartInfo {
                        FileName = edgePath,
                        Arguments = arguments,
                        UseShellExecute = true
                    });
                } else {
                    Process.Start(dashboardUrl);
                }
            } catch {
                try { Process.Start(dashboardUrl); } catch { }
            }
        }

        static void ExitApplication() {
            try {
                if (parentPid > 0) {
                    var parent = Process.GetProcessById(parentPid);
                    if (!parent.HasExited) parent.Kill();
                }
            } catch { }
            ExitTrayOnly();
        }

        static void ExitTrayOnly() {
            try {
                if (trayIcon != null) {
                    trayIcon.Visible = false;
                    trayIcon.Dispose();
                }
            } catch { }
            Environment.Exit(0);
        }
    }
}
