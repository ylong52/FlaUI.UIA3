namespace FlaUI.UIA3.Automation.Tests;

public class AutomationOptionsTests
{
    [Fact]
    public void Parse_ReturnsDefaults()
    {
        var options = AutomationOptions.Parse([]);

        Assert.Equal(BrowserKind.Chrome, options.Browser);
        Assert.Equal("about:blank", options.Url);
        Assert.Null(options.AttachProcessId);
        Assert.Empty(options.CheckAutomationIds);
        Assert.False(options.Toggle);
        Assert.False(options.ListChoices);
        Assert.Equal(TimeSpan.FromSeconds(15), options.Timeout);
        Assert.True(options.ForceRendererAccessibility);
    }

    [Fact]
    public void Parse_ReadsBrowserUrlAndRepeatedCheckIds()
    {
        var options = AutomationOptions.Parse(
            ["--browser", "edge", "--url", "https://example.com", "--check", "a", "--check", "b"]);

        Assert.Equal(BrowserKind.Edge, options.Browser);
        Assert.Equal("https://example.com", options.Url);
        Assert.Equal(new[] { "a", "b" }, options.CheckAutomationIds);
    }

    [Fact]
    public void Parse_ReadsAttachPid()
    {
        var options = AutomationOptions.Parse(["--attach", "1234"]);

        Assert.Equal(1234, options.AttachProcessId);
    }

    [Fact]
    public void Parse_ReadsToggleAndListFlags()
    {
        var options = AutomationOptions.Parse(["--toggle", "--list"]);

        Assert.True(options.Toggle);
        Assert.True(options.ListChoices);
    }

    [Fact]
    public void Parse_DisablesForceAccessibility()
    {
        var options = AutomationOptions.Parse(["--no-force-accessibility"]);

        Assert.False(options.ForceRendererAccessibility);
    }

    [Fact]
    public void Parse_ReadsHelp()
    {
        Assert.True(AutomationOptions.Parse(["--help"]).ShowHelp);
    }

    [Theory]
    [InlineData("firefox")]
    [InlineData("")]
    public void Parse_RejectsUnknownBrowser(string browser)
    {
        Assert.Throws<ArgumentException>(() => AutomationOptions.Parse(["--browser", browser]));
    }

    [Fact]
    public void Parse_RejectsMissingValue()
    {
        Assert.Throws<ArgumentException>(() => AutomationOptions.Parse(["--url"]));
    }

    [Fact]
    public void Parse_RejectsInvalidPid()
    {
        Assert.Throws<ArgumentException>(() => AutomationOptions.Parse(["--attach", "abc"]));
    }

    [Theory]
    [InlineData("0")]
    [InlineData("-1")]
    [InlineData("abc")]
    public void Parse_RejectsInvalidTimeout(string timeout)
    {
        Assert.Throws<ArgumentException>(() => AutomationOptions.Parse(["--timeout", timeout]));
    }

    [Fact]
    public void Parse_RejectsUnknownArgument()
    {
        Assert.Throws<ArgumentException>(() => AutomationOptions.Parse(["--nope"]));
    }

    [Fact]
    public void Parse_SurveyTestDefaultsToNotSubmitting()
    {
        var options = AutomationOptions.Parse(["--survey-test"]);

        Assert.True(options.SurveyTest);
        Assert.False(options.SubmitSurvey);
        Assert.Equal(1.0, options.PaceMultiplier);
    }

    [Fact]
    public void Parse_ReadsSubmitAndPace()
    {
        var options = AutomationOptions.Parse(["--survey-test", "--submit", "--pace", "slow"]);

        Assert.True(options.SubmitSurvey);
        Assert.Equal(1.6, options.PaceMultiplier);
    }

    [Theory]
    [InlineData("weird")]
    [InlineData("-1")]
    [InlineData("0")]
    public void Parse_RejectsInvalidPace(string pace)
    {
        Assert.Throws<ArgumentException>(() => AutomationOptions.Parse(["--pace", pace]));
    }
}
