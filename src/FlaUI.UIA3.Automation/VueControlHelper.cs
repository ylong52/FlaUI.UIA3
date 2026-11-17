using FlaUI.Core.AutomationElements;
using FlaUI.Core.Definitions;

namespace FlaUI.UIA3.Automation;

/// <summary>
/// 针对 Vue 自定义单选/多选组件的 UIA 辅助方法。
/// Vue 组件常见的可访问性形态不一定是标准 CheckBox/RadioButton：
/// 优先使用 Toggle 模式，其次 SelectionItem，最后 Invoke，避免只依赖 ControlType。
/// </summary>
public static class VueControlHelper
{
    /// <summary>按 AutomationId 查找；超时返回 null。</summary>
    public static AutomationElement? TryFindByAutomationId(
        AutomationElement root,
        string automationId,
        TimeSpan timeout,
        TimeSpan pollInterval)
    {
        ArgumentNullException.ThrowIfNull(root);
        ArgumentException.ThrowIfNullOrWhiteSpace(automationId);

        try
        {
            return Retry.Until(
                () => root.FindFirstDescendant(cf => cf.ByAutomationId(automationId)),
                static element => element is not null,
                timeout,
                pollInterval);
        }
        catch (TimeoutException)
        {
            return null;
        }
    }

    /// <summary>按 Name 查找；超时返回 null。</summary>
    public static AutomationElement? TryFindByName(
        AutomationElement root,
        string name,
        TimeSpan timeout,
        TimeSpan pollInterval)
    {
        ArgumentNullException.ThrowIfNull(root);
        ArgumentException.ThrowIfNullOrWhiteSpace(name);

        try
        {
            return Retry.Until(
                () => root.FindFirstDescendant(cf => cf.ByName(name)),
                static element => element is not null,
                timeout,
                pollInterval);
        }
        catch (TimeoutException)
        {
            return null;
        }
    }

    /// <summary>寻找浏览器窗口中的页面主体（Document）；找不到时回退到窗口本身。</summary>
    public static AutomationElement FindPageRoot(
        AutomationElement window,
        TimeSpan timeout,
        TimeSpan pollInterval)
    {
        ArgumentNullException.ThrowIfNull(window);

        try
        {
            return Retry.Until(
                () => window.FindFirstDescendant(cf => cf.ByControlType(ControlType.Document)),
                static document => document is not null,
                timeout,
                pollInterval) ?? window;
        }
        catch (TimeoutException)
        {
            return window;
        }
    }

    /// <summary>列出页面中的标准复选/单选控件（ControlType 维度）。</summary>
    public static AutomationElement[] FindChoices(AutomationElement root)
    {
        ArgumentNullException.ThrowIfNull(root);

        var checkboxes = root.FindAllDescendants(cf => cf.ByControlType(ControlType.CheckBox));
        var radios = root.FindAllDescendants(cf => cf.ByControlType(ControlType.RadioButton));

        return checkboxes.Concat(radios).ToArray();
    }

    /// <summary>
    /// 直接读取勾选状态：
    /// Toggle 模式优先，其次 SelectionItem；两者都不支持时返回 null（未知）。
    /// </summary>
    public static bool? TryGetChecked(AutomationElement element)
    {
        ArgumentNullException.ThrowIfNull(element);

        var toggle = element.Patterns.Toggle.PatternOrDefault;
        if (toggle is not null)
        {
            return toggle.ToggleState.ValueOrDefault switch
            {
                ToggleState.On => true,
                ToggleState.Off => false,
                _ => null,
            };
        }

        var selection = element.Patterns.SelectionItem.PatternOrDefault;
        return selection?.IsSelected;
    }

    /// <summary>
    /// 把控件设置为期望的勾选状态。
    /// 若已经是目标状态则不做任何操作；否则按可用模式切换，切换后立即校验。
    /// </summary>
    public static void SetChecked(AutomationElement element, bool desired)
    {
        ArgumentNullException.ThrowIfNull(element);

        var current = TryGetChecked(element);
        if (current == desired)
        {
            return;
        }

        var toggle = element.Patterns.Toggle.PatternOrDefault;
        if (toggle is not null)
        {
            toggle.Toggle();
            return;
        }

        var selection = element.Patterns.SelectionItem.PatternOrDefault;
        if (selection is not null)
        {
            if (desired)
            {
                selection.Select();
            }
            else
            {
                selection.RemoveFromSelection();
            }

            return;
        }

        var invoke = element.Patterns.Invoke.PatternOrDefault;
        if (invoke is not null)
        {
            invoke.Invoke();
            return;
        }

        throw new InvalidOperationException(
            $"控件不支持 Toggle/SelectionItem/Invoke，无法切换状态：{Describe(element)}");
    }

    /// <summary>轮询等待控件达到期望勾选状态；超时返回 false。</summary>
    public static bool WaitForChecked(
        AutomationElement element,
        bool expected,
        TimeSpan timeout,
        TimeSpan pollInterval)
    {
        ArgumentNullException.ThrowIfNull(element);

        try
        {
            var state = Retry.Until(
                () => TryGetChecked(element),
                value => value == expected,
                timeout,
                pollInterval);
            return state == expected;
        }
        catch (TimeoutException)
        {
            return false;
        }
    }

    /// <summary>生成便于日志/断言的可读描述。</summary>
    public static string Describe(AutomationElement element)
    {
        ArgumentNullException.ThrowIfNull(element);

        var checkedState = TryGetChecked(element) switch
        {
            true => "已选中",
            false => "未选中",
            null => "状态未知",
        };

        var offscreen = element.IsOffscreen ? "（离屏）" : string.Empty;
        return $"Name=\"{element.Name}\" ControlType={element.ControlType} AutomationId=\"{element.AutomationId}\" {checkedState}{offscreen}";
    }
}
