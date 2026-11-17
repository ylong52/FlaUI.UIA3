using FlaUI.Core.AutomationElements;

namespace FlaUI.UIA3.Automation;

/// <summary>
/// 导出 UI Automation 树，用于分析页面结构（只读，不执行任何页面脚本）。
/// 单个节点的属性读取失败（元素在渲染中被替换）时跳过该节点，不影响整体导出。
/// </summary>
public static class UiTreeDumper
{
    public static int Dump(AutomationElement root, int maxDepth, int maxNodes, TextWriter writer)
    {
        ArgumentNullException.ThrowIfNull(root);
        ArgumentNullException.ThrowIfNull(writer);

        var count = 0;

        void Walk(AutomationElement element, int depth)
        {
            if (count >= maxNodes)
            {
                return;
            }

            count++;
            writer.WriteLine(Format(element, depth));

            if (depth >= maxDepth)
            {
                return;
            }

            AutomationElement[] children;
            try
            {
                children = element.FindAllChildren();
            }
            catch
            {
                return;
            }

            foreach (var child in children)
            {
                if (count >= maxNodes)
                {
                    break;
                }

                Walk(child, depth + 1);
            }
        }

        Walk(root, 0);

        if (count >= maxNodes)
        {
            writer.WriteLine($"[已截断：达到节点上限 {maxNodes}]");
        }

        return count;
    }

    private static string Format(AutomationElement element, int depth)
    {
        string controlType;
        string name;
        string automationId;
        var offscreen = false;

        try
        {
            controlType = element.ControlType.ToString();
            name = element.Name;
            automationId = element.AutomationId;
            offscreen = element.IsOffscreen;
        }
        catch
        {
            return $"{new string(' ', depth * 2)}[不可读节点]";
        }

        return $"{new string(' ', depth * 2)}{controlType} | Name=\"{Escape(name)}\" | AutomationId=\"{Escape(automationId)}\"{(offscreen ? " [offscreen]" : string.Empty)}";
    }

    private static string Escape(string value) => value.ReplaceLineEndings(" ");
}
