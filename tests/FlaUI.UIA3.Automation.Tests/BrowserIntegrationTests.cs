namespace FlaUI.UIA3.Automation.Tests;

/// <summary>
/// 需要真实浏览器的端到端测试。默认跳过：设置环境变量
/// FLAUI_E2E_PID 为已运行的 Chrome/Edge 进程 PID 后才会执行。
/// </summary>
public class BrowserIntegrationTests
{
    [Fact]
    [Trait("Category", "E2E")]
    public void AttachToRunningBrowser_ReadsMainWindowTitle()
    {
        var rawPid = Environment.GetEnvironmentVariable("FLAUI_E2E_PID");
        if (!int.TryParse(rawPid, out var processId))
        {
            return;
        }

        using var session = BrowserSession.Attach(processId);
        var window = session.GetMainWindow(TimeSpan.FromSeconds(10));

        Assert.False(string.IsNullOrWhiteSpace(window.Name));
    }

    [Fact]
    [Trait("Category", "E2E")]
    public void ResolveExecutable_ThrowsHelpfulError_WhenPathIsMissing()
    {
        var exception = Assert.Throws<FileNotFoundException>(() =>
            BrowserSession.ResolveExecutable((BrowserKind)999));

        Assert.Contains("--path", exception.Message);
    }
}
