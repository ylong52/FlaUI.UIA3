using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using FlaUI.Core.AutomationElements;
using FlaUI.Core.Definitions;
using FlaUI.Core.Input;
using FlaUI.Core.WindowsAPI;

namespace FlaUI.UIA3.Automation;

/// <summary>
/// 原生 Chrome + C# FlaUI + Python Agent 的整页答题执行器。
/// 无 CDP：页面源码通过 HTTP 获取；Python 端使用 survey_test 适配器。
/// 只执行 status=ready；needs_review 不操作；最后一页不点击 Submit。
/// </summary>
internal sealed class SurveyAiRunner
{
    private const string DefaultSurveyUrl = "https://api.x-survey.com/test/survey-test.html";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    private static readonly Regex StepRegex = new(
        @"Step\s+(\d+)\s+of\s+9",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private readonly AutomationOptions _options;
    private readonly HumanPacing _pacing;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(120) };

    private Window _window = null!;
    private AutomationElement _page = null!;

    public SurveyAiRunner(AutomationOptions options)
    {
        _options = options;
        _pacing = new HumanPacing(options.PaceMultiplier);
    }

    public async Task<int> RunAsync()
    {
        var surveyUrl = _options.Url == "about:blank" ? DefaultSurveyUrl : _options.Url;
        var profilePath = Path.GetFullPath(_options.ProfilePath);
        if (!File.Exists(profilePath))
        {
            Console.Error.WriteLine($"未找到受访者资料文件：{profilePath}");
            return 2;
        }

        using var profileDocument = JsonDocument.Parse(
            await File.ReadAllTextAsync(profilePath));
        var profile = profileDocument.RootElement.Clone();

        Console.WriteLine("[1/6] 查找原生 Chrome 窗口（无 CDP）");
        var pid = _options.AttachProcessId ?? WaitForChromePid(surveyUrl);
        if (pid is null)
        {
            Console.Error.WriteLine("未找到原生 Chrome 窗口，请先通过 start.cmd 启动浏览器。");
            return 3;
        }

        using var session = BrowserSession.Attach(pid.Value);
        _window = session.GetMainWindow(_options.Timeout);
        Console.WriteLine($"      已附加：{_window.Name}");
        _page = VueControlHelper.FindPageRoot(
            _window,
            _options.Timeout,
            _options.PollInterval);

        // 内置 9 步测试页保留原流程；其他问卷走通用逐页模式。
        if (ReadStep(_page) is null)
        {
            Console.WriteLine("      未检测到 \"Step N of 9\"：使用通用逐页模式");
            return await RunGenericAsync(profile);
        }

        Console.WriteLine($"[2/6] 读取页面源码：{surveyUrl}");
        string html;
        try
        {
            html = await FetchHtmlAsync(surveyUrl);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"读取页面源码失败：{ex.Message}");
            return 2;
        }

        Console.WriteLine($"      HTML 长度：{html.Length}");

        if (!EnsureStepOne())
        {
            Console.Error.WriteLine("无法回到第 1 步。");
            return 4;
        }

        Console.WriteLine("[3/6] 调用 Python Agent 分析整页问卷");
        var taskId = _options.TaskId ?? $"survey-{DateTime.Now:yyyyMMdd-HHmmss}";
        var request = new AnalyzeRequestDto
        {
            TaskId = taskId,
            PageId = "full-page",
            Html = html,
            RespondentProfile = profile,
        };

        AnalyzeResponseDto? response;
        try
        {
            response = await AnalyzeAsync(request);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"调用 Python Agent 失败：{ex.Message}");
            return 5;
        }

        if (response is null)
        {
            return 5;
        }

        PrintAnalysis(response);

        Console.WriteLine("[4/6] 执行答题计划（只执行 ready）");
        var result = ExecuteAllSteps(response);
        if (result != 0)
        {
            return result;
        }

        Console.WriteLine("[6/6] 完成：已填到最后一页，未点击 Submit。");
        Console.WriteLine($"      task_id={response.TaskId} status={response.Status}");
        return 0;
    }

    // ---------------------------------------------------------------- generic mode

    /// <summary>
    /// 通用逐页模式：每页从 UIA 取题干与真实控件 → 合成 HTML → 调 Agent →
    /// 按控件作答 → 点 Next；遇到 Submit 只停止不点击。
    /// </summary>
    private async Task<int> RunGenericAsync(JsonElement profile)
    {
        var taskId = _options.TaskId ?? $"survey-{DateTime.Now:yyyyMMdd-HHmmss}";
        const int maxPages = 40;

        for (var pageNumber = 1; pageNumber <= maxPages; pageNumber++)
        {
            SurveyPageSnapshot? snapshot;
            try
            {
                snapshot = WaitForPageReady(pageNumber);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[第 {pageNumber} 页] 读取页面结构失败：{ex.Message}");
                return 8;
            }

            if (snapshot is null)
            {
                Console.Error.WriteLine(
                    $"[第 {pageNumber} 页] 页面长时间没有可识别的题目（可能仍在加载），已停止。");
                return 8;
            }

            if (snapshot.SubmitButtons.Count > 0)
            {
                Console.WriteLine(
                    $"[第 {pageNumber} 页] 检测到提交按钮 \"{snapshot.SubmitButtons[0].Name}\"，" +
                    "已停止（未点击 Submit）。");
                break;
            }

            if (snapshot.Questions.Count == 0)
            {
                if (SurveyPageSnapshot.LooksFinished(snapshot.Texts))
                {
                    Console.WriteLine(
                        $"[第 {pageNumber} 页] 问卷已结束（感谢页/筛除页），无需继续填写：" +
                        Shorten(string.Join(" ", snapshot.Texts), 120));
                    return 0;
                }

                Console.Error.WriteLine($"[第 {pageNumber} 页] 未识别到任何题目，已停止。");
                return 8;
            }

            Console.WriteLine(
                $"[第 {pageNumber} 页] 识别到 {snapshot.Questions.Count} 题：" +
                string.Join(" | ", snapshot.Questions.Select(question => Shorten(question.Text))));

            var request = new AnalyzeRequestDto
            {
                TaskId = taskId,
                PageId = $"page-{pageNumber}",
                Html = snapshot.ToHtml(),
                RespondentProfile = profile,
                Options = new AnalyzeOptionsDto { PageAdapter = "html" },
            };

            AnalyzeResponseDto? response;
            try
            {
                response = await AnalyzeAsync(request);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"调用 Python Agent 失败：{ex.Message}");
                return 5;
            }

            if (response is null)
            {
                return 5;
            }

            PrintAnalysis(response);
            FocusWindow();
            ExecutePage(snapshot, response);
            _pacing.AfterStep();

            if (snapshot.NextButtons.Count == 0)
            {
                Console.WriteLine("      当前页没有 Next 类按钮，已停止（可能是最后一页）。");
                break;
            }

            var next = snapshot.NextButtons[0];
            Console.WriteLine($"      点击 \"{next.Name}\"，等待进入下一页…");
            try
            {
                if (!ClickAndWaitForPageChange(next, snapshot.Signature))
                {
                    return 7;
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"      点击 Next 失败：{ex.Message}");
                return 7;
            }
        }

        Console.WriteLine("[完成] 已逐页填写，未点击 Submit。");
        return 0;
    }

    /// <summary>等待页面渲染出题目（或识别为结束页），最多约 45 秒。</summary>
    private SurveyPageSnapshot? WaitForPageReady(int pageNumber)
    {
        try
        {
            return Retry.Until(
                () => SurveyPageSnapshot.Capture(_page, pageNumber),
                snapshot => snapshot.Questions.Count > 0
                            || snapshot.SubmitButtons.Count > 0
                            || SurveyPageSnapshot.LooksFinished(snapshot.Texts),
                TimeSpan.FromSeconds(Math.Max(45, _options.Timeout.TotalSeconds * 2)),
                _options.PollInterval);
        }
        catch (TimeoutException)
        {
            return null;
        }
    }

    private void ExecutePage(SurveyPageSnapshot snapshot, AnalyzeResponseDto response)
    {
        var byId = new Dictionary<string, PageQuestion>(StringComparer.OrdinalIgnoreCase);
        foreach (var question in snapshot.Questions)
        {
            byId[question.Id] = question;
        }

        foreach (var answer in response.Answers)
        {
            if (!byId.TryGetValue(answer.QuestionId, out var question))
            {
                Console.WriteLine($"      [warn] 计划中的题目不在本页：{answer.QuestionId}");
                continue;
            }

            if (answer.Status != "ready")
            {
                // 已在 PrintAnalysis 输出过，避免重复刷屏。
                continue;
            }

            try
            {
                FillPageAnswer(question, answer);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"      [error] {answer.QuestionId}：{ex.Message}");
            }
        }

        foreach (var question in snapshot.Questions)
        {
            var answered = response.Answers.Any(answer =>
                string.Equals(answer.QuestionId, question.Id, StringComparison.OrdinalIgnoreCase));
            if (!answered)
            {
                Console.WriteLine($"      [missing] {question.Id}: {Shorten(question.Text)}");
            }
        }
    }

    private void FillPageAnswer(PageQuestion question, AnswerDto answer)
    {
        switch (question.Kind)
        {
            case PageQuestionKind.SingleChoice:
            {
                var label = answer.SelectedOptions.FirstOrDefault();
                var choice = FindPageChoice(question, label);
                if (choice is null)
                {
                    Console.WriteLine($"      [warn] 找不到选项：{label}");
                    return;
                }

                SelectElement(choice.Element);
                _pacing.OptionGap();
                Console.WriteLine($"      单选：{choice.Label}");
                return;
            }

            case PageQuestionKind.MultiChoice:
            {
                foreach (var label in answer.SelectedOptions)
                {
                    var choice = FindPageChoice(question, label);
                    if (choice is null)
                    {
                        Console.WriteLine($"      [warn] 找不到选项：{label}");
                        continue;
                    }

                    if (VueControlHelper.TryGetChecked(choice.Element) != true)
                    {
                        EnsureVisible(choice.Element);
                        ClickAtCenter(choice.Element);
                    }

                    _pacing.OptionGap();
                    Console.WriteLine($"      多选：{choice.Label}");
                }

                return;
            }

            case PageQuestionKind.Dropdown:
            {
                if (question.Input is null)
                {
                    Console.WriteLine("      [warn] 下拉控件缺失");
                    return;
                }

                var label = answer.SelectedOptions.FirstOrDefault() ?? answer.AnswerText;
                SelectDropdown(question.Input, label);
                return;
            }

            case PageQuestionKind.Rating:
            {
                if (question.Input is null)
                {
                    Console.WriteLine("      [warn] 评分控件缺失");
                    return;
                }

                var pattern = question.Input.Patterns.RangeValue.PatternOrDefault;
                if (pattern is null)
                {
                    Console.WriteLine("      [warn] 评分控件不支持 RangeValue");
                    return;
                }

                pattern.SetValue(answer.NumericValue ?? 0);
                _pacing.OptionGap();
                Console.WriteLine($"      评分：{FormatNumber(answer.NumericValue)}");
                return;
            }

            default:
            {
                if (question.Input is null)
                {
                    Console.WriteLine("      [warn] 输入控件缺失");
                    return;
                }

                var text = answer.AnswerText;
                if (string.IsNullOrWhiteSpace(text) && answer.NumericValue is { } number)
                {
                    text = FormatNumber(number);
                }

                TypeText(question.Input, text ?? string.Empty);
                Console.WriteLine($"      输入：{text}");
                return;
            }
        }
    }

    private static PageChoice? FindPageChoice(PageQuestion question, string? label)
    {
        if (string.IsNullOrWhiteSpace(label))
        {
            return null;
        }

        var target = NormalizeLabel(label);
        var loose = NormalizeLoose(label);
        return question.Choices.FirstOrDefault(choice =>
                   NormalizeLabel(choice.Label) == target)
               ?? question.Choices.FirstOrDefault(choice =>
                   NormalizeLabel(choice.Label).Contains(target, StringComparison.Ordinal))
               ?? (loose.Length > 0
                   ? question.Choices.FirstOrDefault(choice =>
                       NormalizeLoose(choice.Label) == loose)
                   : null);
    }

    private bool ClickAndWaitForPageChange(AutomationElement button, string signature)
    {
        if (!WaitUntilEnabled(button))
        {
            Console.Error.WriteLine(
                "      Next 仍处于禁用状态：可能有必答题未填写，已停止。");
            return false;
        }

        _pacing.ReadingPause();
        InvokeOrClick(button);

        try
        {
            Retry.Until(
                () => SurveyPageSnapshot.Capture(_page).Signature,
                current => !string.Equals(current, signature, StringComparison.Ordinal),
                TimeSpan.FromSeconds(Math.Max(20, _options.Timeout.TotalSeconds * 2)),
                _options.PollInterval);
        }
        catch (TimeoutException)
        {
            Console.Error.WriteLine(
                "      点击 Next 后页面未变化（可能被必答校验拦截或仍在加载），已停止。");
            return false;
        }

        _page = VueControlHelper.FindPageRoot(
            _window,
            _options.Timeout,
            _options.PollInterval);
        return true;
    }

    private bool WaitUntilEnabled(AutomationElement element)
    {
        try
        {
            Retry.Until(
                () => element.Properties.IsEnabled.ValueOrDefault,
                enabled => enabled,
                _options.Timeout,
                _options.PollInterval);
            return true;
        }
        catch (TimeoutException)
        {
            return false;
        }
    }

    private void InvokeOrClick(AutomationElement element)
    {
        var invoke = element.Patterns.Invoke.PatternOrDefault;
        if (invoke is not null)
        {
            try
            {
                invoke.Invoke();
                return;
            }
            catch
            {
                // 部分浏览器控件 Invoke 会被拒绝，退回真实鼠标点击。
            }
        }

        ClickAtCenter(element);
    }

    private static string Shorten(string? text, int max = 60)
    {
        var value = NormalizeLabel(text);
        return value.Length <= max ? value : value[..max] + "…";
    }

    // ---------------------------------------------------------------- HTTP

    private async Task<string> FetchHtmlAsync(string url)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        request.Headers.UserAgent.ParseAdd("FlaUI.UIA3.Automation/1.0");
        using var response = await _http.SendAsync(request);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadAsStringAsync();
    }

    private async Task<AnalyzeResponseDto?> AnalyzeAsync(AnalyzeRequestDto request)
    {
        var baseUrl = _options.ApiBaseUrl.TrimEnd('/');
        var json = JsonSerializer.Serialize(request, JsonOptions);
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        using var response = await _http.PostAsync(
            $"{baseUrl}/api/v1/agent/analyze",
            content);
        var body = await response.Content.ReadAsStringAsync();

        if (!response.IsSuccessStatusCode)
        {
            Console.Error.WriteLine(
                $"分析失败 HTTP {(int)response.StatusCode}：{body}");
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<AnalyzeResponseDto>(body, JsonOptions);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(
                $"分析响应解析失败：{ex.Message}\n{body[..Math.Min(body.Length, 500)]}");
            return null;
        }
    }

    private static void PrintAnalysis(AnalyzeResponseDto response)
    {
        var ready = response.Answers.Count(answer => answer.Status == "ready");
        Console.WriteLine(
            $"      status={response.Status} answers={response.Answers.Count} ready={ready} " +
            $"tokens={response.Usage.TotalTokens} model={response.Usage.Model}");

        foreach (var warning in response.Warnings)
        {
            Console.WriteLine($"      warning: {warning}");
        }

        foreach (var answer in response.Answers.Where(a => a.Status != "ready"))
        {
            Console.WriteLine(
                $"      [{answer.Status}] {answer.QuestionId}: {answer.Notes}");
        }
    }

    // ---------------------------------------------------------------- execution

    private int ExecuteAllSteps(AnalyzeResponseDto response)
    {
        var answers = response.Answers.ToDictionary(
            answer => answer.QuestionId,
            StringComparer.Ordinal);

        for (var step = 1; step <= 9; step++)
        {
            if (!TryWaitForStep(step))
            {
                Console.Error.WriteLine(
                    $"未到达 Step {step}：可能存在 needs_review 的必答题，已停止，未提交。");
                return 6;
            }

            _pacing.AfterStep();
            Console.WriteLine($"[Step {step}/9]");
            ExecuteStep(step, response.Questions, answers);

            if (step == 9)
            {
                break;
            }

            Console.WriteLine($"      点击 Next，进入 Step {step + 1}");
            ClickNext();
        }

        return 0;
    }

    private void ExecuteStep(
        int step,
        List<QuestionDto> questions,
        Dictionary<string, AnswerDto> answers)
    {
        var stepQuestions = questions.Where(question => GetStep(question) == step).ToList();
        var edits = _page.FindAllDescendants(cf => cf.ByControlType(ControlType.Edit));
        var editIndex = 0;

        foreach (var question in stepQuestions)
        {
            if (!answers.TryGetValue(question.QuestionId, out var answer))
            {
                Console.WriteLine($"      [missing] {question.QuestionId}");
                continue;
            }

            if (answer.Status != "ready")
            {
                Console.WriteLine(
                    $"      [{answer.Status}] {question.QuestionId}: {answer.Notes}");
                continue;
            }

            try
            {
                switch (question.QuestionType)
                {
                    case "single_choice":
                        SelectRadioByName(answer.SelectedOptions.FirstOrDefault());
                        break;
                    case "dropdown":
                        SelectDropdown(answer.SelectedOptions.FirstOrDefault());
                        break;
                    case "multi_choice":
                        foreach (var option in answer.SelectedOptions)
                        {
                            SelectCheckboxByName(option);
                        }

                        break;
                    case "text":
                        TypeIntoEdit(edits, ref editIndex, answer.AnswerText ?? string.Empty);
                        break;
                    case "number":
                        TypeIntoEdit(
                            edits,
                            ref editIndex,
                            FormatNumber(answer.NumericValue));
                        break;
                    case "matrix":
                        ExecuteMatrix(question, answer);
                        break;
                    case "rating":
                        ExecuteRating(answer);
                        break;
                    case "ranking":
                        VerifyRanking(answer);
                        break;
                    default:
                        Console.WriteLine(
                            $"      [skip] {question.QuestionId}: 未支持的题型 {question.QuestionType}");
                        break;
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine(
                    $"      [error] {question.QuestionId}：{ex.Message}");
            }
        }
    }

    private void TypeIntoEdit(
        AutomationElement[] edits,
        ref int editIndex,
        string text)
    {
        if (editIndex >= edits.Length)
        {
            Console.WriteLine("      [warn] 页面输入框数量不足");
            return;
        }

        var edit = edits[editIndex++];
        TypeText(edit, text);
    }

    private void TypeText(AutomationElement edit, string text)
    {
        var sanitized = text.ReplaceLineEndings(" ");
        FocusWindow();
        EnsureVisible(edit);

        for (var attempt = 1; attempt <= 2; attempt++)
        {
            TypeKeystrokes(edit, sanitized);
            if (ValueMatches(edit, sanitized))
            {
                return;
            }

            Console.WriteLine(
                $"      [warn] 第 {attempt} 次输入未生效，重新聚焦再输入");
        }

        // 键盘输入两次都没落进控件时，用 ValuePattern 兜底。
        var pattern = edit.Patterns.Value.PatternOrDefault;
        if (pattern is not null)
        {
            try
            {
                pattern.SetValue(sanitized);
                _pacing.ActionGap();
            }
            catch
            {
                // 不支持写入时保持键盘输入结果。
            }
        }

        if (!ValueMatches(edit, sanitized))
        {
            Console.WriteLine("      [warn] 输入框内容与计划不一致，请检查该题");
        }
    }

    private void TypeKeystrokes(AutomationElement edit, string text)
    {
        _pacing.ActionGap();
        ClickAtCenter(edit);
        _pacing.ActionGap();
        // 首次点击可能只激活浏览器窗口，再点一次确保焦点落在输入框。
        ClickAtCenter(edit);
        _pacing.BeforeTyping();

        Keyboard.Press(VirtualKeyShort.CONTROL);
        Keyboard.Press(VirtualKeyShort.KEY_A);
        Keyboard.Release(VirtualKeyShort.KEY_A);
        Keyboard.Release(VirtualKeyShort.CONTROL);
        _pacing.ActionGap();

        Keyboard.Press(VirtualKeyShort.DELETE);
        Keyboard.Release(VirtualKeyShort.DELETE);
        _pacing.ActionGap();

        foreach (var character in text)
        {
            Keyboard.Type(character.ToString());
            _pacing.CharDelay();
            if (character is '.' or ',' or '?' or '!' or ';' or ':')
            {
                _pacing.PunctuationPause();
            }
        }

        _pacing.FieldGap();
    }

    private static bool ValueMatches(AutomationElement element, string expected)
    {
        var pattern = element.Patterns.Value.PatternOrDefault;
        if (pattern is null)
        {
            return true; // 无法读取时不误报
        }

        try
        {
            var current = pattern.Value.ValueOrDefault ?? string.Empty;
            return string.Equals(current.Trim(), expected.Trim(), StringComparison.Ordinal);
        }
        catch
        {
            return true;
        }
    }

    private void FocusWindow()
    {
        try
        {
            _window.Focus();
        }
        catch
        {
            // 窗口可能已最小化或失去焦点。
        }
    }

    private void SelectRadioByName(string? label)
    {
        if (string.IsNullOrWhiteSpace(label))
        {
            Console.WriteLine("      [warn] 单选答案为空");
            return;
        }

        var radios = _page.FindAllDescendants(cf => cf.ByControlType(ControlType.RadioButton));
        var target = FindByLabel(radios, label);
        if (target is null)
        {
            Console.WriteLine($"      [warn] 找不到单选：{label}");
            return;
        }

        SelectElement(target);
        _pacing.OptionGap();
        Console.WriteLine($"      单选：{label}");
    }

    private void SelectCheckboxByName(string label)
    {
        var boxes = _page.FindAllDescendants(cf => cf.ByControlType(ControlType.CheckBox));
        var target = FindByLabel(boxes, label);
        if (target is null)
        {
            Console.WriteLine($"      [warn] 找不到多选：{label}");
            return;
        }

        if (VueControlHelper.TryGetChecked(target) != true)
        {
            EnsureVisible(target);
            ClickAtCenter(target);
        }

        _pacing.OptionGap();
        Console.WriteLine($"      多选：{label}");
    }

    private void SelectDropdown(string? label)
    {
        if (string.IsNullOrWhiteSpace(label))
        {
            Console.WriteLine("      [warn] 下拉答案为空");
            return;
        }

        var combo = _page
            .FindAllDescendants(cf => cf.ByControlType(ControlType.ComboBox))
            .FirstOrDefault();
        if (combo is null)
        {
            Console.WriteLine("      [warn] 找不到下拉框");
            return;
        }

        SelectDropdown(combo, label);
    }

    private void SelectDropdown(AutomationElement combo, string? label)
    {
        if (string.IsNullOrWhiteSpace(label))
        {
            Console.WriteLine("      [warn] 下拉答案为空");
            return;
        }

        EnsureVisible(combo);
        ClickAtCenter(combo);
        _pacing.BeforeTyping();

        foreach (var character in label)
        {
            Keyboard.Type(character.ToString());
            _pacing.CharDelay();
        }

        _pacing.ActionGap();
        Keyboard.Press(VirtualKeyShort.ENTER);
        Keyboard.Release(VirtualKeyShort.ENTER);
        _pacing.OptionGap();
        Keyboard.Press(VirtualKeyShort.ESCAPE);
        Keyboard.Release(VirtualKeyShort.ESCAPE);
        _pacing.ActionGap();

        Console.WriteLine($"      下拉：{label}");
    }

    private void ExecuteMatrix(QuestionDto question, AnswerDto answer)
    {
        if (question.Matrix is null)
        {
            Console.WriteLine($"      [warn] {question.QuestionId} 缺少矩阵定义");
            return;
        }

        var radios = _page.FindAllDescendants(cf => cf.ByControlType(ControlType.RadioButton));
        var rows = question.Matrix.Rows;
        var columns = question.Matrix.Columns;

        foreach (var (rowId, columnId) in answer.MatrixSelections)
        {
            var rowIndex = rows.FindIndex(row => row.Id == rowId);
            var columnIndex = columns.FindIndex(column => column.Id == columnId);
            if (rowIndex < 0 || columnIndex < 0)
            {
                Console.WriteLine(
                    $"      [warn] 矩阵行列不存在：{rowId} -> {columnId}");
                continue;
            }

            var index = rowIndex * columns.Count + columnIndex;
            if (index < 0 || index >= radios.Length)
            {
                Console.WriteLine($"      [warn] 矩阵单选索引越界：{index}");
                continue;
            }

            SelectElement(radios[index]);
            _pacing.OptionGap();
            Console.WriteLine($"      矩阵：{rowId} -> {columnId}");
        }
    }

    private void ExecuteRating(AnswerDto answer)
    {
        var slider = _page
            .FindAllDescendants(cf => cf.ByControlType(ControlType.Slider))
            .FirstOrDefault();
        if (slider is null)
        {
            Console.WriteLine("      [warn] 找不到评分滑杆");
            return;
        }

        var value = answer.NumericValue ?? 0;
        var pattern = slider.Patterns.RangeValue.PatternOrDefault;
        if (pattern is null)
        {
            Console.WriteLine("      [warn] 滑杆不支持 RangeValue");
            return;
        }

        pattern.SetValue(value);
        _pacing.OptionGap();
        Console.WriteLine($"      评分：{FormatNumber(value)}");
    }

    private void VerifyRanking(AnswerDto answer)
    {
        var items = _page.FindAllDescendants(cf => cf.ByControlType(ControlType.ListItem));
        var current = items
            .Select(item => NormalizeRank(item.Name))
            .Where(value => value.Length > 0)
            .ToList();
        var desired = answer.Ranking.Select(NormalizeRank).ToList();

        if (current.Count == desired.Count && current.SequenceEqual(desired))
        {
            Console.WriteLine("      排序：页面顺序与计划一致，无需拖拽");
            return;
        }

        Console.WriteLine(
            "      [warn] 排序与计划不一致，保留页面原序（未执行拖拽）：" +
            $"current=[{string.Join(", ", current)}] " +
            $"desired=[{string.Join(", ", desired)}]");
    }

    // ---------------------------------------------------------------- UIA helpers

    private void ClickNext()
    {
        var buttons = _page.FindAllDescendants(cf => cf.ByControlType(ControlType.Button));
        var next = buttons.FirstOrDefault(button =>
            button.Name?.Contains("Next", StringComparison.OrdinalIgnoreCase) == true);
        if (next is null)
        {
            Console.WriteLine("      [warn] 找不到 Next 按钮");
            return;
        }

        _pacing.ReadingPause();
        var invoke = next.Patterns.Invoke.PatternOrDefault;
        if (invoke is not null)
        {
            invoke.Invoke();
        }
        else
        {
            ClickAtCenter(next);
        }
    }

    private bool TryWaitForStep(int step)
    {
        try
        {
            Retry.Until(
                () => ReadStep(_page),
                current => current == step,
                _options.Timeout,
                _options.PollInterval);
            return true;
        }
        catch (TimeoutException)
        {
            return false;
        }
    }

    private int? ReadStep(AutomationElement page)
    {
        try
        {
            var texts = page.FindAllDescendants(cf => cf.ByControlType(ControlType.Text));
            foreach (var text in texts)
            {
                var match = StepRegex.Match(text.Name ?? string.Empty);
                if (match.Success)
                {
                    return int.Parse(match.Groups[1].Value, CultureInfo.InvariantCulture);
                }
            }
        }
        catch
        {
            // 页面重绘时忽略。
        }

        return null;
    }

    private bool EnsureStepOne()
    {
        if (ReadStep(_page) == 1)
        {
            return true;
        }

        Console.WriteLine("      当前不在 Step 1，刷新重置…");
        try
        {
            _window.Focus();
        }
        catch
        {
            // 窗口可能已失去焦点。
        }

        Keyboard.Press(VirtualKeyShort.F5);
        Keyboard.Release(VirtualKeyShort.F5);
        Thread.Sleep(1500);
        _page = VueControlHelper.FindPageRoot(
            _window,
            _options.Timeout,
            _options.PollInterval);
        return TryWaitForStep(1);
    }

    private int? WaitForChromePid(string surveyUrl)
    {
        var deadline = DateTime.UtcNow.AddSeconds(
            Math.Max(30, _options.Timeout.TotalSeconds));
        while (DateTime.UtcNow < deadline)
        {
            var process = FindChromeWindowProcess();
            if (process is not null)
            {
                return process.Id;
            }

            Thread.Sleep(500);
        }

        Console.WriteLine("      未发现 Chrome 窗口，尝试直接启动原生 Chrome");
        try
        {
            LaunchChrome(surveyUrl);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"启动 Chrome 失败：{ex.Message}");
            return null;
        }

        deadline = DateTime.UtcNow.AddSeconds(45);
        while (DateTime.UtcNow < deadline)
        {
            var process = FindChromeWindowProcess();
            if (process is not null)
            {
                return process.Id;
            }

            Thread.Sleep(500);
        }

        return null;
    }

    private static Process? FindChromeWindowProcess()
    {
        foreach (var process in Process.GetProcessesByName("chrome"))
        {
            try
            {
                if (process.MainWindowHandle == IntPtr.Zero)
                {
                    continue;
                }

                var title = process.MainWindowTitle;
                if (title.Contains("Industrial Valve", StringComparison.OrdinalIgnoreCase)
                    || title.Contains("ValveSpec", StringComparison.OrdinalIgnoreCase)
                    || title.Contains("Survey", StringComparison.OrdinalIgnoreCase))
                {
                    return process;
                }
            }
            catch
            {
                // 进程可能已退出。
            }
        }

        return null;
    }

    private static void LaunchChrome(string surveyUrl)
    {
        var chromePath = BrowserSession.ResolveExecutable(BrowserKind.Chrome);
        var profileDirectory = Path.Combine(Path.GetTempPath(), "survey-agent-chrome");
        Directory.CreateDirectory(profileDirectory);
        var arguments =
            "--force-renderer-accessibility " +
            $"--user-data-dir=\"{profileDirectory}\" " +
            "--no-first-run --no-default-browser-check " +
            $"--new-window \"{surveyUrl}\"";
        Process.Start(new ProcessStartInfo(chromePath, arguments)
        {
            UseShellExecute = false,
        });
    }

    private static int GetStep(QuestionDto question)
    {
        if (question.Raw.ValueKind == JsonValueKind.Object
            && question.Raw.TryGetProperty("step", out var step)
            && step.TryGetInt32(out var value))
        {
            return value;
        }

        return 0;
    }

    private static AutomationElement? FindByLabel(
        AutomationElement[] elements,
        string label)
    {
        var target = NormalizeLabel(label);
        var loose = NormalizeLoose(label);
        return elements.FirstOrDefault(element =>
                   NormalizeLabel(element.Name) == target)
               ?? elements.FirstOrDefault(element =>
                   NormalizeLabel(element.Name).Contains(target, StringComparison.Ordinal))
               ?? (loose.Length > 0
                   ? elements.FirstOrDefault(element =>
                       NormalizeLoose(element.Name) == loose)
                   : null)
               ?? (loose.Length > 0
                   ? elements.FirstOrDefault(element =>
                       NormalizeLoose(element.Name).Contains(loose, StringComparison.Ordinal))
                   : null);
    }

    private static string NormalizeLabel(string? value)
        => Regex.Replace(value ?? string.Empty, @"\s+", " ").Trim();

    private static string NormalizeLoose(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        return new string(value.Where(char.IsLetterOrDigit).ToArray())
            .ToLowerInvariant();
    }

    private static string NormalizeRank(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var chars = value.Where(char.IsLetterOrDigit).ToArray();
        return new string(chars)
            .ToLowerInvariant()
            .TrimStart('0', '1', '2', '3', '4', '5', '6', '7', '8', '9');
    }

    private static string FormatNumber(double? value)
        => (value ?? 0).ToString("0.##", CultureInfo.InvariantCulture);

    private void SelectElement(AutomationElement element)
    {
        EnsureVisible(element);

        var selection = element.Patterns.SelectionItem.PatternOrDefault;
        if (selection is not null)
        {
            selection.Select();
            return;
        }

        var toggle = element.Patterns.Toggle.PatternOrDefault;
        if (toggle is not null)
        {
            if (toggle.ToggleState.ValueOrDefault != ToggleState.On)
            {
                toggle.Toggle();
            }

            return;
        }

        var invoke = element.Patterns.Invoke.PatternOrDefault;
        if (invoke is not null)
        {
            invoke.Invoke();
            return;
        }

        ClickAtCenter(element);
    }

    private void EnsureVisible(AutomationElement element)
    {
        try
        {
            if (!element.Properties.IsOffscreen.ValueOrDefault)
            {
                return;
            }

            element.Patterns.ScrollItem.PatternOrDefault?.ScrollIntoView();
            _pacing.ActionGap();
        }
        catch
        {
            // 元素可能不支持 ScrollItem。
        }
    }

    private void ClickAtCenter(AutomationElement element)
    {
        EnsureVisible(element);
        var point = element.GetClickablePoint();
        MoveMouseHumanly(new Point(
            point.X + _pacing.Jitter(2),
            point.Y + _pacing.Jitter(2)));
        _pacing.MouseTravel();
        Mouse.Click(MouseButton.Left);
        _pacing.MouseSettle();
    }

    private void MoveMouseHumanly(Point target)
    {
        Point start;
        try
        {
            start = Mouse.Position;
        }
        catch
        {
            Mouse.MoveTo(target);
            return;
        }

        var steps = _pacing.Next(14, 28);
        for (var step = 1; step <= steps; step++)
        {
            var progress = (double)step / steps;
            var eased = 1 - Math.Pow(1 - progress, 3);
            var x = start.X + (int)((target.X - start.X) * eased) + _pacing.Jitter(1);
            var y = start.Y + (int)((target.Y - start.Y) * eased) + _pacing.Jitter(1);
            Mouse.Position = new Point(x, y);
            Thread.Sleep(_pacing.Next(7, 16));
        }

        _pacing.MouseSettle();
    }
}
