using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using FlaUI.Core.AutomationElements;
using FlaUI.Core.Definitions;

namespace FlaUI.UIA3.Automation;

internal enum PageQuestionKind
{
    Text,
    Number,
    SingleChoice,
    MultiChoice,
    Dropdown,
    Rating,
}

internal sealed class PageChoice
{
    public required AutomationElement Element { get; init; }
    public required string Label { get; init; }
}

/// <summary>当前页面上的一组「题干 + 控件」，供通用逐页模式分析与作答。</summary>
internal sealed class PageQuestion
{
    public required string Id { get; init; }
    public required string Text { get; init; }
    public required PageQuestionKind Kind { get; init; }

    /// <summary>单选/多选/下拉的可选项；文本/数字/评分题不使用。</summary>
    public List<PageChoice> Choices { get; } = new();

    /// <summary>文本/数字/下拉/评分题对应的输入控件。</summary>
    public AutomationElement? Input { get; init; }

    public double? Minimum { get; init; }
    public double? Maximum { get; init; }

    public string TypeName => Kind switch
    {
        PageQuestionKind.Text => "text",
        PageQuestionKind.Number => "number",
        PageQuestionKind.SingleChoice => "single_choice",
        PageQuestionKind.MultiChoice => "multi_choice",
        PageQuestionKind.Dropdown => "dropdown",
        PageQuestionKind.Rating => "rating",
        _ => "unknown",
    };
}

/// <summary>
/// 无 CDP 时的页面快照：按 UIA 文档顺序收集题干文字与真实控件，
/// 再合成为标准 HTML 交给 Python Agent 解析。
/// </summary>
internal sealed class SurveyPageSnapshot
{
    private const int MaxOptionsPerQuestion = 80;

    private static readonly Regex NonPromptRegex = new(
        @"^(\d+\s*%\s*(complete|completed)?|page\s*\d+|\d+\s*(of|/)\s*\d+|loading|please wait|powered by.*)$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex SubmitRegex = new(
        @"\b(submit|finish|complete|done)\b",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex CompletionRegex = new(
        @"thank you for (trying|completing)|not able to complete|not eligible|"
        + @"screen(ed|ing)? ?out|screening in progress|disqualif|quota|"
        + @"survey (is )?closed|no longer accepting|did not match|not qualified|"
        + @"target audience",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public string Signature { get; private set; } = string.Empty;

    /// <summary>当前页可见文字（全部），用于识别结束页/筛除页。</summary>
    public List<string> Texts { get; } = new();

    public List<PageQuestion> Questions { get; } = new();

    public List<AutomationElement> NextButtons { get; } = new();

    public List<AutomationElement> SubmitButtons { get; } = new();

    public static bool IsSubmitLabel(string name)
        => SubmitRegex.IsMatch(name ?? string.Empty);

    /// <summary>识别“感谢参与 / 被筛除 / 配额已满”等结束页。</summary>
    public static bool LooksFinished(IEnumerable<string> texts)
        => texts.Any(CompletionRegex.IsMatch);

    public static bool IsNextLabel(string name)
    {
        var trimmed = (name ?? string.Empty).Trim();
        if (trimmed.Length == 0 || IsSubmitLabel(trimmed))
        {
            return false;
        }

        if (trimmed is "→" or "»" or ">")
        {
            return true;
        }

        return trimmed.StartsWith("next", StringComparison.OrdinalIgnoreCase)
               || trimmed.StartsWith("continue", StringComparison.OrdinalIgnoreCase)
               || trimmed.StartsWith("start", StringComparison.OrdinalIgnoreCase)
               || trimmed.StartsWith("begin", StringComparison.OrdinalIgnoreCase)
               || trimmed.Equals("ok", StringComparison.OrdinalIgnoreCase)
               || trimmed.StartsWith("agree", StringComparison.OrdinalIgnoreCase)
               || trimmed.StartsWith("i agree", StringComparison.OrdinalIgnoreCase)
               || trimmed.StartsWith("accept", StringComparison.OrdinalIgnoreCase);
    }

    public static SurveyPageSnapshot Capture(AutomationElement page, int pageNumber = 1)
    {
        var snapshot = new SurveyPageSnapshot();
        var signature = new StringBuilder();
        var prompt = string.Empty;
        var index = 0;
        PageQuestion? openChoice = null;
        var idPrefix = $"p{Math.Max(1, pageNumber)}";

        AutomationElement[] descendants;
        try
        {
            descendants = page.FindAllDescendants();
        }
        catch
        {
            descendants = Array.Empty<AutomationElement>();
        }

        foreach (var element in descendants)
        {
            ControlType controlType;
            string name;
            try
            {
                controlType = element.ControlType;
                name = (element.Name ?? string.Empty).Trim();
                if (element.Properties.IsOffscreen.ValueOrDefault)
                {
                    continue;
                }
            }
            catch
            {
                continue;
            }

            if (controlType == ControlType.Text)
            {
                if (name.Length >= 2)
                {
                    snapshot.Texts.Add(name);
                }

                if (!IsPromptLike(name))
                {
                    continue;
                }

                prompt = name;
                openChoice = null;
                signature.Append("T:").Append(name).Append(';');
                continue;
            }

            if (controlType == ControlType.Button)
            {
                if (name.Length == 0)
                {
                    continue;
                }

                if (IsSubmitLabel(name))
                {
                    snapshot.SubmitButtons.Add(element);
                }
                else if (IsNextLabel(name))
                {
                    snapshot.NextButtons.Add(element);
                }

                continue;
            }

            var kind = controlType switch
            {
                ControlType.RadioButton => PageQuestionKind.SingleChoice,
                ControlType.CheckBox => PageQuestionKind.MultiChoice,
                ControlType.ComboBox => PageQuestionKind.Dropdown,
                ControlType.Spinner => PageQuestionKind.Number,
                ControlType.Slider => PageQuestionKind.Rating,
                ControlType.Edit => PageQuestionKind.Text,
                _ => (PageQuestionKind?)null,
            };
            if (kind is null)
            {
                continue;
            }

            index++;
            var text = prompt.Length > 0
                ? prompt
                : $"Untitled question {index}";

            if (kind is PageQuestionKind.SingleChoice or PageQuestionKind.MultiChoice)
            {
                if (name.Length == 0)
                {
                    continue;
                }

                if (openChoice is null
                    || openChoice.Kind != kind
                    || !string.Equals(openChoice.Text, text, StringComparison.Ordinal))
                {
                    openChoice = new PageQuestion
                    {
                        Id = $"{idPrefix}q{index}",
                        Text = text,
                        Kind = kind.Value,
                    };
                    snapshot.Questions.Add(openChoice);
                }

                if (openChoice.Choices.Count < MaxOptionsPerQuestion)
                {
                    openChoice.Choices.Add(new PageChoice
                    {
                        Element = element,
                        Label = name,
                    });
                }

                signature.Append('C').Append(kind).Append(':').Append(name).Append('|');
                continue;
            }

            openChoice = null;
            var (minimum, maximum) = ReadRange(element);
            snapshot.Questions.Add(new PageQuestion
            {
                Id = $"{idPrefix}q{index}",
                Text = text,
                Kind = kind.Value,
                Input = element,
                Minimum = minimum,
                Maximum = maximum,
            });
            signature.Append('C').Append(kind).Append(':').Append(name).Append('|');
        }

        snapshot.Signature = signature.ToString();
        return snapshot;
    }

    public string ToHtml()
    {
        var builder = new StringBuilder(8192);
        builder.AppendLine("<html><head><meta charset=\"utf-8\"></head><body><form>");

        foreach (var question in Questions)
        {
            builder.Append("<div class=\"question\"><div class=\"qtitle\">")
                .Append(Escape(question.Text))
                .Append("</div>");

            switch (question.Kind)
            {
                case PageQuestionKind.Text:
                    builder.Append("<input type=\"text\" name=\"")
                        .Append(question.Id)
                        .Append("\">");
                    break;

                case PageQuestionKind.Number:
                    builder.Append("<input type=\"number\" name=\"")
                        .Append(question.Id)
                        .Append('"');
                    AppendRangeAttribute(builder, "min", question.Minimum);
                    AppendRangeAttribute(builder, "max", question.Maximum);
                    builder.Append('>');
                    break;

                case PageQuestionKind.Rating:
                    builder.Append("<input type=\"range\" name=\"")
                        .Append(question.Id)
                        .Append("\" min=\"")
                        .Append(Format(question.Minimum ?? 0))
                        .Append("\" max=\"")
                        .Append(Format(question.Maximum ?? 10))
                        .Append("\">");
                    break;

                case PageQuestionKind.Dropdown:
                    builder.Append("<select name=\"").Append(question.Id).Append("\">");
                    foreach (var choice in question.Choices)
                    {
                        builder.Append("<option value=\"")
                            .Append(Escape(choice.Label))
                            .Append("\">")
                            .Append(Escape(choice.Label))
                            .Append("</option>");
                    }

                    builder.Append("</select>");
                    break;

                case PageQuestionKind.SingleChoice:
                case PageQuestionKind.MultiChoice:
                    var inputType = question.Kind == PageQuestionKind.SingleChoice
                        ? "radio"
                        : "checkbox";
                    foreach (var choice in question.Choices)
                    {
                        builder.Append("<label><input type=\"")
                            .Append(inputType)
                            .Append("\" name=\"")
                            .Append(question.Id)
                            .Append("\" value=\"")
                            .Append(Escape(choice.Label))
                            .Append("\"> ")
                            .Append(Escape(choice.Label))
                            .Append("</label>");
                    }

                    break;
            }

            builder.Append("</div>");
        }

        builder.AppendLine("</form></body></html>");
        return builder.ToString();
    }

    private static bool IsPromptLike(string name)
    {
        if (name.Length < 2 || NonPromptRegex.IsMatch(name))
        {
            return false;
        }

        return !IsSubmitLabel(name) && !IsNextLabel(name);
    }

    private static (double? Minimum, double? Maximum) ReadRange(AutomationElement element)
    {
        var pattern = element.Patterns.RangeValue.PatternOrDefault;
        if (pattern is null)
        {
            return (null, null);
        }

        try
        {
            return (pattern.Minimum.ValueOrDefault, pattern.Maximum.ValueOrDefault);
        }
        catch
        {
            return (null, null);
        }
    }

    private static void AppendRangeAttribute(StringBuilder builder, string name, double? value)
    {
        if (value is { } number)
        {
            builder.Append(' ').Append(name).Append("=\"").Append(Format(number)).Append('"');
        }
    }

    private static string Format(double value)
        => value.ToString("0.##", CultureInfo.InvariantCulture);

    private static string Escape(string? value)
        => (value ?? string.Empty)
            .Replace("&", "&amp;", StringComparison.Ordinal)
            .Replace("<", "&lt;", StringComparison.Ordinal)
            .Replace(">", "&gt;", StringComparison.Ordinal)
            .Replace("\"", "&quot;", StringComparison.Ordinal);
}
