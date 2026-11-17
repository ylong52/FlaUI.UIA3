using System.Text.Json;

namespace FlaUI.UIA3.Automation;

internal sealed class AnalyzeRequestDto
{
    public string TaskId { get; set; } = string.Empty;
    public string PageId { get; set; } = "full-page";
    public string Html { get; set; } = string.Empty;
    public JsonElement RespondentProfile { get; set; }
    public AnalyzeOptionsDto Options { get; set; } = new();
}

internal sealed class AnalyzeOptionsDto
{
    public bool ReusePrevious { get; set; } = true;
    public bool IncludeQuestions { get; set; } = true;
    public int MaxQuestions { get; set; } = 500;
    public string PageAdapter { get; set; } = "survey_test";
}

internal sealed class AnalyzeResponseDto
{
    public string TaskId { get; set; } = string.Empty;
    public string PageId { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public List<AnswerDto> Answers { get; set; } = [];
    public List<QuestionDto> Questions { get; set; } = [];
    public UsageDto Usage { get; set; } = new();
    public List<string> Warnings { get; set; } = [];
}

internal sealed class AnswerDto
{
    public string QuestionId { get; set; } = string.Empty;
    public string QuestionType { get; set; } = string.Empty;
    public List<string> SelectedOptions { get; set; } = [];
    public string? AnswerText { get; set; }
    public Dictionary<string, string> MatrixSelections { get; set; } = new();
    public List<string> Ranking { get; set; } = [];
    public double? NumericValue { get; set; }
    public string Status { get; set; } = string.Empty;
    public string? Source { get; set; }
    public string? Notes { get; set; }
}

internal sealed class QuestionDto
{
    public string QuestionId { get; set; } = string.Empty;
    public string? Text { get; set; }
    public string QuestionType { get; set; } = string.Empty;
    public bool Required { get; set; }
    public List<OptionDto> Options { get; set; } = [];
    public MatrixDto? Matrix { get; set; }
    public NumericDto? Numeric { get; set; }
    public JsonElement Raw { get; set; }
}

internal sealed class OptionDto
{
    public string Id { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
}

internal sealed class MatrixDto
{
    public List<RowDto> Rows { get; set; } = [];
    public List<OptionDto> Columns { get; set; } = [];
}

internal sealed class RowDto
{
    public string Id { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
}

internal sealed class NumericDto
{
    public double? Min { get; set; }
    public double? Max { get; set; }
    public double? Step { get; set; }
}

internal sealed class UsageDto
{
    public string? Model { get; set; }
    public int PromptTokens { get; set; }
    public int CompletionTokens { get; set; }
    public int TotalTokens { get; set; }
}
