namespace FlaUI.UIA3.Automation;

/// <summary>
/// 支持的浏览器类型。
/// </summary>
public enum BrowserKind
{
    Chrome,
    Edge,
}

/// <summary>
/// 命令行与运行期参数。
/// </summary>
public sealed class AutomationOptions
{
    public BrowserKind Browser { get; init; } = BrowserKind.Chrome;

    /// <summary>启动浏览器时打开的地址。</summary>
    public string Url { get; init; } = "about:blank";

    /// <summary>显式指定浏览器可执行文件；为空时按 <see cref="Browser"/> 自动查找。</summary>
    public string? BrowserExecutablePath { get; init; }

    /// <summary>附加到已运行的浏览器进程；指定后忽略启动相关参数。</summary>
    public int? AttachProcessId { get; init; }

    /// <summary>要定位并检查的控件 AutomationId 列表。</summary>
    public IReadOnlyList<string> CheckAutomationIds { get; init; } = Array.Empty<string>();

    /// <summary>对找到的控件执行一次切换（勾选/取消）。</summary>
    public bool Toggle { get; init; }

    /// <summary>列出当前可交互的复选/单选类控件。</summary>
    public bool ListChoices { get; init; }

    /// <summary>导出 UIA 树，便于分析页面结构。</summary>
    public bool DumpTree { get; init; }

    public int TreeDepth { get; init; } = 12;

    public int TreeLimit { get; init; } = 3000;

    /// <summary>UIA 树输出文件；为空时打印到标准输出。</summary>
    public string? TreeOut { get; init; }

    /// <summary>把当前页的「UIA 快照 → 合成 HTML」写入文件，便于排查通用模式。</summary>
    public string? PageSnapshotOut { get; init; }

    /// <summary>追加到浏览器启动命令行的额外参数（可重复）。</summary>
    public IReadOnlyList<string> ExtraArguments { get; init; } = Array.Empty<string>();

    /// <summary>运行内置测试问卷作答流程。</summary>
    public bool SurveyTest { get; init; }

    /// <summary>使用 Python Agent（:8790）分析并执行整页问卷。</summary>
    public bool SurveyAi { get; init; }

    public string ApiBaseUrl { get; init; } = "http://127.0.0.1:8790";

    public string ProfilePath { get; init; } = "demo_profile.json";

    public string? TaskId { get; init; }

    /// <summary>作答完成后点击 Submit；默认只填到最后一步。</summary>
    public bool SubmitSurvey { get; init; }

    /// <summary>拟人节奏倍率：fast≈0.55、normal=1.0、slow≈1.6。</summary>
    public double PaceMultiplier { get; init; } = 1.0;

    public bool ShowHelp { get; init; }

    public TimeSpan Timeout { get; init; } = TimeSpan.FromSeconds(15);

    public TimeSpan PollInterval { get; init; } = TimeSpan.FromMilliseconds(200);

    /// <summary>
    /// 启动时附带 Chromium 的 --force-renderer-accessibility，
    /// 让 Web 内容更稳定地暴露 UI Automation 树（非 CDP，也不是 JS 注入）。
    /// </summary>
    public bool ForceRendererAccessibility { get; init; } = true;

    public static AutomationOptions Parse(string[] args)
    {
        var browser = BrowserKind.Chrome;
        var url = "about:blank";
        string? path = null;
        int? attach = null;
        var checks = new List<string>();
        var toggle = false;
        var list = false;
        var help = false;
        var dumpTree = false;
        var treeDepth = 12;
        var treeLimit = 3000;
        string? treeOut = null;
        string? pageSnapshotOut = null;
        var extraArguments = new List<string>();
        var surveyTest = false;
        var surveyAi = false;
        var apiBaseUrl = "http://127.0.0.1:8790";
        var profilePath = "demo_profile.json";
        string? taskId = null;
        var submitSurvey = false;
        var paceMultiplier = 1.0;
        var timeout = TimeSpan.FromSeconds(15);
        var forceAccessibility = true;

        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            switch (arg)
            {
                case "--browser" or "-b":
                    browser = ParseBrowser(NextValue(args, ref i, arg));
                    break;
                case "--url" or "-u":
                    url = NextValue(args, ref i, arg);
                    break;
                case "--path" or "-p":
                    path = NextValue(args, ref i, arg);
                    break;
                case "--attach" or "-a":
                    var rawPid = NextValue(args, ref i, arg);
                    if (!int.TryParse(rawPid, out var pid) || pid <= 0)
                    {
                        throw new ArgumentException($"--attach 需要正整数进程 ID，收到：{rawPid}");
                    }

                    attach = pid;
                    break;
                case "--check" or "-c":
                    checks.Add(NextValue(args, ref i, arg));
                    break;
                case "--toggle" or "-t":
                    toggle = true;
                    break;
                case "--list" or "-l":
                    list = true;
                    break;
                case "--tree":
                    dumpTree = true;
                    break;
                case "--tree-depth":
                    treeDepth = ParseNonNegativeInt(NextValue(args, ref i, arg), arg);
                    break;
                case "--tree-limit":
                    treeLimit = ParseNonNegativeInt(NextValue(args, ref i, arg), arg);
                    break;
                case "--tree-out":
                    treeOut = NextValue(args, ref i, arg);
                    break;
                case "--dump-page":
                    pageSnapshotOut = NextValue(args, ref i, arg);
                    break;
                case "--extra-arg":
                    extraArguments.Add(NextValue(args, ref i, arg));
                    break;
                case "--survey-test":
                    surveyTest = true;
                    break;
                case "--survey-ai":
                    surveyAi = true;
                    break;
                case "--api":
                    apiBaseUrl = NextValue(args, ref i, arg);
                    break;
                case "--profile":
                    profilePath = NextValue(args, ref i, arg);
                    break;
                case "--task-id":
                    taskId = NextValue(args, ref i, arg);
                    break;
                case "--submit":
                    submitSurvey = true;
                    break;
                case "--no-submit":
                    submitSurvey = false;
                    break;
                case "--pace":
                    paceMultiplier = ParsePace(NextValue(args, ref i, arg));
                    break;
                case "--timeout":
                    var rawTimeout = NextValue(args, ref i, arg);
                    if (!double.TryParse(rawTimeout, out var seconds) || seconds <= 0)
                    {
                        throw new ArgumentException($"--timeout 需要正数秒，收到：{rawTimeout}");
                    }

                    timeout = TimeSpan.FromSeconds(seconds);
                    break;
                case "--no-force-accessibility":
                    forceAccessibility = false;
                    break;
                case "--help" or "-h" or "/?":
                    help = true;
                    break;
                default:
                    throw new ArgumentException($"未知参数：{arg}。使用 --help 查看用法。");
            }
        }

        return new AutomationOptions
        {
            Browser = browser,
            Url = url,
            BrowserExecutablePath = path,
            AttachProcessId = attach,
            CheckAutomationIds = checks,
            Toggle = toggle,
            ListChoices = list,
            DumpTree = dumpTree,
            TreeDepth = treeDepth,
            TreeLimit = treeLimit,
            TreeOut = treeOut,
            PageSnapshotOut = pageSnapshotOut,
            ExtraArguments = extraArguments,
            SurveyTest = surveyTest,
            SurveyAi = surveyAi,
            ApiBaseUrl = apiBaseUrl,
            ProfilePath = profilePath,
            TaskId = taskId,
            SubmitSurvey = submitSurvey,
            PaceMultiplier = paceMultiplier,
            ShowHelp = help,
            Timeout = timeout,
            ForceRendererAccessibility = forceAccessibility,
        };
    }

    private static BrowserKind ParseBrowser(string value) => value.ToLowerInvariant() switch
    {
        "chrome" => BrowserKind.Chrome,
        "edge" or "msedge" => BrowserKind.Edge,
        _ => throw new ArgumentException($"未知浏览器：{value}，可选 chrome 或 edge。"),
    };

    private static double ParsePace(string value) => value.ToLowerInvariant() switch
    {
        "fast" => 0.55,
        "normal" => 1.0,
        "slow" => 1.6,
        _ when double.TryParse(value, out var numeric) && numeric > 0 => numeric,
        _ => throw new ArgumentException($"--pace 需要 fast、normal、slow 或正数倍率，收到：{value}"),
    };

    private static int ParseNonNegativeInt(string value, string option)
    {
        if (!int.TryParse(value, out var number) || number < 0)
        {
            throw new ArgumentException($"{option} 需要非负整数，收到：{value}");
        }

        return number;
    }

    private static string NextValue(string[] args, ref int index, string option)
    {
        if (index + 1 >= args.Length)
        {
            throw new ArgumentException($"{option} 缺少参数值。");
        }

        return args[++index];
    }
}
