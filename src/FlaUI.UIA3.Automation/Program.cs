using System.Text;

namespace FlaUI.UIA3.Automation;

internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        try
        {
            var options = AutomationOptions.Parse(args);
            if (options.ShowHelp)
            {
                PrintUsage();
                return 0;
            }

            return await RunAsync(options);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"错误：{ex.Message}");
            return 1;
        }
    }

    private static async Task<int> RunAsync(AutomationOptions options)
    {
        if (options.SurveyAi)
        {
            return await new SurveyAiRunner(options).RunAsync();
        }

        return Run(options);
    }

    private static int Run(AutomationOptions options)
    {
        Console.WriteLine(options.AttachProcessId is { } processId
            ? $"附加到浏览器进程 PID={processId} ..."
            : $"启动 {options.Browser}：{options.Url}");

        using var session = BrowserSession.AttachOrLaunch(options);
        var window = session.GetMainWindow(options.Timeout);
        Console.WriteLine($"主窗口：{window.Name}");

        if (options.SurveyTest)
        {
            var page = VueControlHelper.FindPageRoot(window, options.Timeout, options.PollInterval);
            new SurveyTestAnswerer(options, window, page).Run(submit: options.SubmitSurvey);
            return 0;
        }

        if (options.DumpTree)
        {
            DumpTree(window, options);
        }

        if (options.PageSnapshotOut is { } snapshotPath)
        {
            DumpPageSnapshot(window, options, snapshotPath);
        }

        if (options.ListChoices)
        {
            ListChoices(window);
        }

        foreach (var automationId in options.CheckAutomationIds)
        {
            InspectAndMaybeToggle(window, automationId, options);
        }

        if (!options.ListChoices && options.CheckAutomationIds.Count == 0)
        {
            Console.WriteLine("提示：使用 --list 列出控件，或 --check <AutomationId> 定位控件。");
        }

        return 0;
    }

    private static void DumpTree(
        FlaUI.Core.AutomationElements.AutomationElement window,
        AutomationOptions options)
    {
        var root = VueControlHelper.FindPageRoot(window, options.Timeout, options.PollInterval);
        Console.WriteLine($"UIA 树（页面根：{root.ControlType} \"{root.Name}\"）");

        if (options.TreeOut is { } path)
        {
            using var writer = new StreamWriter(
                path,
                append: false,
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            var count = UiTreeDumper.Dump(root, options.TreeDepth, options.TreeLimit, writer);
            Console.WriteLine($"已写入 {count} 个节点到 {path}");
            return;
        }

        UiTreeDumper.Dump(root, options.TreeDepth, options.TreeLimit, Console.Out);
    }

    private static void DumpPageSnapshot(
        FlaUI.Core.AutomationElements.AutomationElement window,
        AutomationOptions options,
        string path)
    {
        var root = VueControlHelper.FindPageRoot(window, options.Timeout, options.PollInterval);
        var snapshot = SurveyPageSnapshot.Capture(root);

        var builder = new StringBuilder();
        builder.AppendLine(
            $"# questions={snapshot.Questions.Count} " +
            $"next=[{string.Join(", ", snapshot.NextButtons.Select(b => b.Name))}] " +
            $"submit=[{string.Join(", ", snapshot.SubmitButtons.Select(b => b.Name))}]");
        foreach (var question in snapshot.Questions)
        {
            builder.AppendLine(
                $"# {question.Id} [{question.TypeName}] {question.Text} " +
                $"options=[{string.Join(" / ", question.Choices.Select(c => c.Label))}]");
        }

        builder.AppendLine(snapshot.ToHtml());
        File.WriteAllText(path, builder.ToString(), new UTF8Encoding(false));
        Console.WriteLine($"已写入页面快照：{path}（题目 {snapshot.Questions.Count}）");
    }

    private static void ListChoices(FlaUI.Core.AutomationElements.AutomationElement root)
    {
        var choices = VueControlHelper.FindChoices(root);
        Console.WriteLine($"发现 {choices.Length} 个复选/单选控件：");
        foreach (var choice in choices)
        {
            Console.WriteLine($"  - {VueControlHelper.Describe(choice)}");
        }
    }

    private static void InspectAndMaybeToggle(
        FlaUI.Core.AutomationElements.AutomationElement root,
        string automationId,
        AutomationOptions options)
    {
        var element = VueControlHelper.TryFindByAutomationId(
            root,
            automationId,
            options.Timeout,
            options.PollInterval);

        if (element is null)
        {
            Console.WriteLine($"[未找到] AutomationId={automationId}");
            return;
        }

        Console.WriteLine($"[找到] {VueControlHelper.Describe(element)}");

        if (!options.Toggle)
        {
            return;
        }

        var before = VueControlHelper.TryGetChecked(element);
        var desired = before != true;
        VueControlHelper.SetChecked(element, desired);

        var verified = VueControlHelper.WaitForChecked(
            element,
            desired,
            options.Timeout,
            options.PollInterval);

        Console.WriteLine(verified
            ? $"[已切换] 目标状态：{(desired ? "选中" : "未选中")}，已通过 UIA 复核"
            : "[警告] 切换后未在超时内确认目标状态");
    }

    private static void PrintUsage()
    {
        Console.WriteLine("""
            用法：FlaUI.UIA3.Automation [选项]

              -b, --browser <chrome|edge>   浏览器类型，默认 chrome
              -u, --url <url>               启动时打开的地址，默认 about:blank
              -p, --path <exe>              显式指定浏览器可执行文件
              -a, --attach <pid>            附加到已运行的浏览器进程（忽略 -b/-u/-p）
              -c, --check <automationId>    定位指定 AutomationId 的控件，可重复
              -t, --toggle                  对 --check 找到的控件做一次切换并复核
              -l, --list                    列出页面中的复选/单选控件
                  --tree                    导出页面 UIA 树
                  --tree-depth <n>          树的最大深度，默认 12
                  --tree-limit <n>          树的最大节点数，默认 3000
                  --tree-out <文件>          把树写入文件（默认打印到控制台）
                  --dump-page <文件>         把当前页 UIA 快照合成的 HTML 写入文件（通用模式诊断）
                  --extra-arg <参数>         追加浏览器启动参数，可重复
                  --survey-test             按内置 agent 答案拟人化作答测试问卷（9 步）
                  --survey-ai               通过 Python Agent 分析并执行问卷（自动区分测试页/通用逐页）
                  --api <url>               Python Agent 地址，默认 http://127.0.0.1:8790
                  --profile <文件>          受访者资料 JSON，默认 demo_profile.json
                  --task-id <id>            指定任务 ID（默认按时间生成）
                  --submit                  填完后点击 Submit（默认只填到最后一步，不提交）
                  --pace <fast|normal|slow> 拟人节奏，默认 normal；也可传正数倍率
                  --timeout <秒>            单步超时，默认 15
                  --no-force-accessibility  不追加 --force-renderer-accessibility
              -h, --help                    显示帮助

            示例：
              dotnet run --project src/FlaUI.UIA3.Automation -- --browser edge --url https://example.com --list
              dotnet run --project src/FlaUI.UIA3.Automation -- --attach 12345 --check agree --toggle
            """);
    }
}
