using System.Drawing;
using FlaUI.Core.AutomationElements;
using FlaUI.Core.Definitions;
using FlaUI.Core.Input;
using FlaUI.Core.WindowsAPI;

namespace FlaUI.UIA3.Automation;

/// <summary>
/// 针对 https://api.x-survey.com/test/survey-test.html 的 9 步测试问卷，按固定的
/// “agent 答案”拟人化作答：随机停顿、带轨迹的鼠标移动、逐字符键盘输入。
/// 默认只填到最后一步，不提交；加 --submit 才提交。
/// </summary>
public sealed class SurveyTestAnswerer
{
    private static readonly string[] StepTitles =
    [
        "About You",
        "Your Organization",
        "Products & Your Role",
        "Valve Usage",
        "Application Technology",
        "Brand Perception",
        "Product Choice",
        "Your Views",
        "Ranking & Rating",
    ];

    private readonly AutomationOptions _options;
    private readonly Window _window;
    private readonly HumanPacing _pacing;
    private AutomationElement _page;

    public SurveyTestAnswerer(AutomationOptions options, Window window, AutomationElement page)
    {
        _options = options;
        _window = window;
        _page = page;
        _pacing = new HumanPacing(options.PaceMultiplier);
    }

    public void Run(bool submit)
    {
        Console.WriteLine("[survey] 开始按 agent 答案拟人化作答");
        EnsureStepOne();

        AnswerStep1();
        Next(StepTitles[1]);

        AnswerStep2();
        Next(StepTitles[2]);

        AnswerStep3();
        Next(StepTitles[3]);

        AnswerStep4();
        Next(StepTitles[4]);

        AnswerStep5();
        Next(StepTitles[5]);

        AnswerStep6();
        Next(StepTitles[6]);

        AnswerStep7();
        Next(StepTitles[7]);

        AnswerStep8();
        Next(StepTitles[8]);

        AnswerStep9();

        if (submit)
        {
            _pacing.ReadingPause();
            ClickElement(WaitForName("Submit"));
            WaitForText("Thank you!");
            Console.WriteLine("[survey] 已提交，页面显示 Thank you!");
        }
        else
        {
            Console.WriteLine("[survey] 已填到最后一步，未提交（默认）。");
        }
    }

    private void AnswerStep1()
    {
        Console.WriteLine($"[survey] 1/9 {StepTitles[0]}");
        _pacing.ReadingPause();

        ChooseRadio("25-34");
        _pacing.FieldGap();

        SelectCountry("China");
        _pacing.FieldGap();

        var edits = WaitForCount(ControlType.Edit, 2, "Step1 文本框");
        TypeHumanly(edits[0], "My family, my health, and a reliable internet connection.");
        TypeHumanly(edits[1],
            "Start with freshly roasted beans, grind them just before brewing, use water at about 93 C, " +
            "and keep a roughly 1:16 coffee-to-water ratio. A clean filter and a slow, even pour make the biggest difference.");
    }

    private void AnswerStep2()
    {
        Console.WriteLine($"[survey] 2/9 {StepTitles[1]}");
        _pacing.ReadingPause();

        ChooseRadio("Chemical");
        _pacing.FieldGap();
        ChooseRadio("Engineering");
    }

    private void AnswerStep3()
    {
        Console.WriteLine($"[survey] 3/9 {StepTitles[2]}");
        _pacing.ReadingPause();

        ChooseCheckbox("Control valves and actuators", true);
        _pacing.OptionGap();
        ChooseCheckbox("Pumps", true);
        _pacing.OptionGap();
        ChooseCheckbox("Flow meters", true);
        _pacing.FieldGap();

        ChooseRadio("I share the decision-making authority with someone else");
    }

    private void AnswerStep4()
    {
        Console.WriteLine($"[survey] 4/9 {StepTitles[3]}");
        _pacing.ReadingPause();

        ChooseCheckbox("Linear Valves (e.g., globe valves)", true);
        _pacing.OptionGap();
        ChooseCheckbox("Ball Valves", true);
        _pacing.OptionGap();
        ChooseCheckbox("Butterfly Valves", true);
        _pacing.FieldGap();

        var edits = WaitForCount(ControlType.Edit, 4, "Step4 分配输入框");
        var allocation = new[] { "40", "30", "20", "10" };
        for (var i = 0; i < allocation.Length; i++)
        {
            TypeHumanly(edits[i], allocation[i]);
        }

        WaitForTextContaining("Total: 100");
    }

    private void AnswerStep5()
    {
        Console.WriteLine($"[survey] 5/9 {StepTitles[4]}");
        _pacing.ReadingPause();

        var radios = WaitForCount(ControlType.RadioButton, 20, "Step5 矩阵单选");
        foreach (var index in new[] { 0, 6, 12, 16 })
        {
            ChooseRadioElement(radios[index]);
        }
    }

    private void AnswerStep6()
    {
        Console.WriteLine($"[survey] 6/9 {StepTitles[5]}");
        _pacing.ReadingPause();

        var radios = WaitForCount(ControlType.RadioButton, 32, "Step6 矩阵单选");
        foreach (var index in new[] { 0, 10, 21, 26 })
        {
            ChooseRadioElement(radios[index]);
        }
    }

    private void AnswerStep7()
    {
        Console.WriteLine($"[survey] 7/9 {StepTitles[6]}");
        _pacing.ReadingPause();

        var radios = WaitForCount(ControlType.RadioButton, 5, "Step7 选项");
        ChooseRadioElement(radios[3]);
    }

    private void AnswerStep8()
    {
        Console.WriteLine($"[survey] 8/9 {StepTitles[7]}");
        _pacing.ReadingPause();

        var edit = WaitForCount(ControlType.Edit, 1, "Step8 开放题")[0];
        TypeHumanly(edit,
            "The most important factor is total cost of ownership backed by dependable after-sales support: " +
            "consistent quality, fast spare-parts availability, and responsive technical service over the valve's full life cycle.");
    }

    private void AnswerStep9()
    {
        Console.WriteLine($"[survey] 9/9 {StepTitles[8]}");
        _pacing.ReadingPause();

        SetImportanceByClick(85);

        // Q15 为鼠标拖拽排序；保留页面默认顺序（提交不校验顺序）。
        Console.WriteLine("[survey] 排序题保留页面默认顺序");
    }

    private void SetImportanceByClick(int target)
    {
        var slider = WaitForControlType(ControlType.Slider, "Step9 重要性滑杆");
        EnsureVisible(slider);

        var rectangle = slider.BoundingRectangle;
        var ratio = Math.Clamp(target, 0, 100) / 100.0;
        var point = new Point(
            rectangle.Left + (int)(rectangle.Width * ratio),
            rectangle.Top + rectangle.Height / 2);

        MoveMouseHumanly(point);
        Mouse.Click(MouseButton.Left);
        _pacing.OptionGap();

        var value = slider.Patterns.RangeValue.PatternOrDefault?.Value.ValueOrDefault;
        if (value is null || Math.Abs(value.Value - target) > 2)
        {
            slider.Patterns.RangeValue.PatternOrDefault?.SetValue(target);
        }

        Console.WriteLine($"[survey] 重要性 ≈ {target}");
    }

    private void Next(string expectedTitle)
    {
        _pacing.ReadingPause();
        ClickElement(WaitForName("Next ›"));
        _pacing.AfterStep();
        WaitForText(expectedTitle);
        _pacing.AfterStep();
    }

    private void ChooseRadio(string optionName)
    {
        var element = WaitForName(optionName);
        ChooseRadioElement(element);
        Console.WriteLine($"  单选：{optionName}");
    }

    private void ChooseRadioElement(AutomationElement element)
    {
        _pacing.OptionGap();
        ClickElement(element);

        try
        {
            Retry.Until(
                () => VueControlHelper.TryGetChecked(element),
                static state => state == true,
                TimeSpan.FromSeconds(4),
                TimeSpan.FromMilliseconds(150));
        }
        catch (TimeoutException)
        {
            element.Patterns.SelectionItem.PatternOrDefault?.Select();
        }

        _pacing.OptionGap();
    }

    private void ChooseCheckbox(string optionName, bool desired)
    {
        var element = WaitForName(optionName);
        if (VueControlHelper.TryGetChecked(element) == desired)
        {
            Console.WriteLine($"  多选（已选中）：{optionName}");
            return;
        }

        _pacing.OptionGap();
        ClickElement(element);

        try
        {
            Retry.Until(
                () => VueControlHelper.TryGetChecked(element),
                state => state == desired,
                TimeSpan.FromSeconds(4),
                TimeSpan.FromMilliseconds(150));
        }
        catch (TimeoutException)
        {
            VueControlHelper.SetChecked(element, desired);
        }

        _pacing.OptionGap();
        Console.WriteLine($"  多选：{optionName}");
    }

    private void SelectCountry(string country)
    {
        var comboElement = WaitForControlType(ControlType.ComboBox, "国家下拉框");
        EnsureVisible(comboElement);

        _pacing.FieldGap();
        ClickElement(comboElement);
        _pacing.BeforeTyping();

        foreach (var character in country)
        {
            Keyboard.Type(character.ToString());
            _pacing.CharDelay();
        }

        _pacing.ActionGap();
        Keyboard.Press(VirtualKeyShort.ENTER);
        Keyboard.Release(VirtualKeyShort.ENTER);
        _pacing.OptionGap();

        // 原生下拉可能仍处于展开状态；先按 ESC 关闭，避免主页面 UIA 树被遮挡。
        Keyboard.Press(VirtualKeyShort.ESCAPE);
        Keyboard.Release(VirtualKeyShort.ESCAPE);
        _pacing.ActionGap();

        var confirmed = ComboShowsValue(comboElement, country)
                        || TryFindTextContaining("2/14", TimeSpan.FromSeconds(2)) is not null;

        if (!confirmed)
        {
            Console.WriteLine("  [warn] 键盘选择未确认，改用程序化选择");

            // 重新取页面根，避免原生弹层造成的元素失效。
            _page = VueControlHelper.FindPageRoot(_window, _options.Timeout, _options.PollInterval);
            var combo = comboElement.AsComboBox();
            combo.Expand();
            combo.Select(country);
            try
            {
                combo.Collapse();
            }
            catch
            {
                // 选择后下拉可能已关闭。
            }

            Keyboard.Press(VirtualKeyShort.ESCAPE);
            Keyboard.Release(VirtualKeyShort.ESCAPE);
            _pacing.ActionGap();
        }

        Console.WriteLine($"  下拉：{country}");
    }

    private static bool ComboShowsValue(AutomationElement combo, string value)
    {
        try
        {
            var direct = combo.Patterns.Value.PatternOrDefault?.Value.ValueOrDefault;
            if (direct is not null && direct.Contains(value, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        catch
        {
            // 继续尝试读取选中项。
        }

        try
        {
            var selected = combo.AsComboBox().SelectedItem?.Name;
            return selected is not null && selected.Contains(value, StringComparison.OrdinalIgnoreCase);
        }
        catch
        {
            return false;
        }
    }

    private void TypeHumanly(AutomationElement edit, string text)
    {
        _pacing.FieldGap();
        ClickElement(edit);
        _pacing.BeforeTyping();
        ClearField();

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

    private void ClearField()
    {
        Keyboard.Press(VirtualKeyShort.CONTROL);
        Keyboard.Press(VirtualKeyShort.KEY_A);
        Keyboard.Release(VirtualKeyShort.KEY_A);
        Keyboard.Release(VirtualKeyShort.CONTROL);
        _pacing.ActionGap();

        Keyboard.Press(VirtualKeyShort.DELETE);
        Keyboard.Release(VirtualKeyShort.DELETE);
        _pacing.ActionGap();
    }

    private void ClickElement(AutomationElement element)
    {
        EnsureVisible(element);

        var point = element.GetClickablePoint();
        point = new Point(point.X + _pacing.Jitter(3), point.Y + _pacing.Jitter(2));
        MoveMouseHumanly(point);

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

    private void EnsureVisible(AutomationElement element)
    {
        for (var attempt = 0; attempt < 10; attempt++)
        {
            if (IsOnScreen(element))
            {
                return;
            }

            try
            {
                element.Patterns.ScrollItem.PatternOrDefault?.ScrollIntoView();
            }
            catch
            {
                // 元素可能不支持 ScrollItem，改用页面滚动兜底。
            }

            _pacing.ActionGap();

            if (IsOnScreen(element))
            {
                return;
            }

            ScrollPageDown();
        }
    }

    private static bool IsOnScreen(AutomationElement element)
    {
        try
        {
            return !element.Properties.IsOffscreen.ValueOrDefault
                   && element.BoundingRectangle.Height > 0;
        }
        catch
        {
            return false;
        }
    }

    private void ScrollPageDown()
    {
        try
        {
            var rectangle = _page.BoundingRectangle;
            var center = new Point(rectangle.Left + rectangle.Width / 2, rectangle.Top + rectangle.Height / 3);
            MoveMouseHumanly(center);
            Mouse.Scroll(-3);
            _pacing.ActionGap();
        }
        catch
        {
            // 页面滚动失败时保持原状，交给后续重试。
        }
    }

    private void EnsureStepOne()
    {
        if (TryFindText("About You", TimeSpan.FromMilliseconds(1000)) is not null)
        {
            return;
        }

        Console.WriteLine("[survey] 页面不在第 1 步，按 F5 重置…");
        Reload();

        if (TryFindText("About You", TimeSpan.FromMilliseconds(2500)) is null)
        {
            throw new TimeoutException("刷新后仍未回到第 1 步（About You）。");
        }

        _pacing.AfterStep();
    }

    private void Reload()
    {
        try
        {
            _window.Focus();
        }
        catch
        {
            // 窗口可能已失去焦点，继续尝试按键。
        }

        _pacing.ActionGap();
        Keyboard.Press(VirtualKeyShort.F5);
        Keyboard.Release(VirtualKeyShort.F5);
        _pacing.AfterStep();
        Thread.Sleep(1000);
        _page = VueControlHelper.FindPageRoot(_window, _options.Timeout, _options.PollInterval);

        if (TryFindText("About You", TimeSpan.FromMilliseconds(1500)) is not null)
        {
            return;
        }

        foreach (var name in new[] { "Reload this page", "Reload", "重新加载此页", "重新加载" })
        {
            var button = TryFindInWindow(name);
            if (button is null)
            {
                continue;
            }

            ClickElement(button);
            _pacing.AfterStep();
            Thread.Sleep(1000);
            _page = VueControlHelper.FindPageRoot(_window, _options.Timeout, _options.PollInterval);
            return;
        }
    }

    private void WaitForText(string text) => WaitForName(text);

    private void WaitForTextContaining(string fragment)
    {
        Retry.Until(
            () => _page.FindAllDescendants(cf => cf.ByControlType(ControlType.Text))
                .Any(text => text.Name.Contains(fragment, StringComparison.OrdinalIgnoreCase)),
            static found => found,
            _options.Timeout,
            _options.PollInterval);
    }

    private AutomationElement? TryFindTextContaining(string fragment, TimeSpan timeout)
    {
        try
        {
            return Retry.Until(
                () => _page.FindAllDescendants(cf => cf.ByControlType(ControlType.Text))
                    .FirstOrDefault(text => text.Name.Contains(fragment, StringComparison.OrdinalIgnoreCase)),
                static found => found is not null,
                timeout,
                _options.PollInterval);
        }
        catch (TimeoutException)
        {
            return null;
        }
    }

    private AutomationElement? TryFindText(string text, TimeSpan timeout)
    {
        try
        {
            return Retry.Until(
                () => _page.FindFirstDescendant(cf => cf.ByName(text)),
                static found => found is not null,
                timeout,
                _options.PollInterval);
        }
        catch (TimeoutException)
        {
            return null;
        }
    }

    private AutomationElement? TryFindInWindow(string name)
    {
        try
        {
            return Retry.Until(
                () => _window.FindFirstDescendant(cf => cf.ByName(name)),
                static found => found is not null,
                TimeSpan.FromMilliseconds(600),
                _options.PollInterval);
        }
        catch (TimeoutException)
        {
            return null;
        }
    }

    private AutomationElement WaitForName(string name)
    {
        var element = Retry.Until(
            () => _page.FindFirstDescendant(cf => cf.ByName(name)),
            static found => found is not null,
            _options.Timeout,
            _options.PollInterval);

        return element ?? throw new TimeoutException($"未找到名为 “{name}” 的元素。");
    }

    private AutomationElement WaitForControlType(ControlType controlType, string label)
    {
        var element = Retry.Until(
            () => _page.FindFirstDescendant(cf => cf.ByControlType(controlType)),
            static found => found is not null,
            _options.Timeout,
            _options.PollInterval);

        return element ?? throw new TimeoutException($"未找到 {label}（{controlType}）。");
    }

    private AutomationElement[] WaitForCount(ControlType controlType, int minimumCount, string label)
    {
        try
        {
            return WaitForCountCore(controlType, minimumCount, label);
        }
        catch (TimeoutException)
        {
            // 原生弹层或页面重绘可能让旧 Document 元素失效，刷新根元素后重试一次。
            _page = VueControlHelper.FindPageRoot(_window, _options.Timeout, _options.PollInterval);
            return WaitForCountCore(controlType, minimumCount, label);
        }
    }

    private AutomationElement[] WaitForCountCore(ControlType controlType, int minimumCount, string label)
    {
        var elements = Retry.Until(
            () => _page.FindAllDescendants(cf => cf.ByControlType(controlType)),
            found => found.Length >= minimumCount,
            _options.Timeout,
            _options.PollInterval);

        if (elements.Length < minimumCount)
        {
            throw new TimeoutException($"{label} 数量不足：期望至少 {minimumCount}，实际 {elements.Length}。");
        }

        return elements;
    }
}
