using FlaUI.Core;
using FlaUI.Core.AutomationElements;
using Application = FlaUI.Core.Application;

namespace FlaUI.UIA3.Automation;

/// <summary>
/// 对一次浏览器 UIA 会话的封装：负责启动/附加浏览器、持有 <see cref="UIA3Automation"/>，
/// 并暴露主窗口。所有交互都走 UI Automation，不使用 CDP 或 JS 注入。
/// </summary>
public sealed class BrowserSession : IDisposable
{
    private readonly Application _application;
    private readonly UIA3Automation _automation;
    private readonly bool _ownsProcess;

    private BrowserSession(Application application, bool ownsProcess)
    {
        _application = application;
        _ownsProcess = ownsProcess;
        _automation = new UIA3Automation();
    }

    public UIA3Automation Automation => _automation;

    public bool OwnsProcess => _ownsProcess;

    public Window GetMainWindow(TimeSpan timeout)
        => _application.GetMainWindow(_automation, timeout)
           ?? throw new TimeoutException($"未能在 {timeout} 内获取浏览器主窗口。");

    public static BrowserSession AttachOrLaunch(AutomationOptions options)
        => options.AttachProcessId is { } processId
            ? Attach(processId)
            : Launch(options);

    public static BrowserSession Attach(int processId)
        => new(Application.Attach(processId), ownsProcess: false);

    public static BrowserSession Launch(AutomationOptions options)
    {
        var executable = options.BrowserExecutablePath ?? ResolveExecutable(options.Browser);
        var application = Application.Launch(executable, BuildArguments(options));
        return new BrowserSession(application, ownsProcess: true);
    }

    /// <summary>仅关闭由本会话启动的浏览器；附加模式不处理外部进程。</summary>
    public void Close()
    {
        if (_ownsProcess)
        {
            _application.Close();
        }
    }

    public void Dispose()
    {
        _automation.Dispose();
    }

    public static string ResolveExecutable(BrowserKind browser)
    {
        if (browser is not (BrowserKind.Chrome or BrowserKind.Edge))
        {
            throw new FileNotFoundException($"不支持的浏览器类型 {browser}，请用 --path 显式指定可执行文件。");
        }

        foreach (var candidate in CandidatePaths(browser))
        {
            if (File.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new FileNotFoundException(
            $"未找到 {browser} 可执行文件，请用 --path 指定，例如：--path \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\"");
    }

    private static string BuildArguments(AutomationOptions options)
    {
        var parts = new List<string>(2);
        if (options.ForceRendererAccessibility)
        {
            // 让 Chromium 更稳定地暴露 Web 内容的 UIA 树；这是启动开关，不是 CDP/JS 注入。
            parts.Add("--force-renderer-accessibility");
        }

        // 调用方原样传入的启动参数（例如 --user-data-dir=...），不做转义处理。
        foreach (var extraArgument in options.ExtraArguments)
        {
            parts.Add(extraArgument);
        }

        parts.Add("--new-window");
        parts.Add(Quote(options.Url));
        return string.Join(' ', parts);
    }

    private static string Quote(string value)
        => "\"" + value.Replace("\"", "%22", StringComparison.Ordinal) + "\"";

    private static IEnumerable<string> CandidatePaths(BrowserKind browser)
    {
        var roots = new[]
        {
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
            Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        };

        foreach (var root in roots)
        {
            if (string.IsNullOrWhiteSpace(root))
            {
                continue;
            }

            yield return browser switch
            {
                BrowserKind.Chrome => Path.Combine(root, "Google", "Chrome", "Application", "chrome.exe"),
                BrowserKind.Edge => Path.Combine(root, "Microsoft", "Edge", "Application", "msedge.exe"),
                _ => throw new ArgumentOutOfRangeException(nameof(browser), browser, "不支持的浏览器类型"),
            };
        }
    }
}
