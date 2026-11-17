namespace FlaUI.UIA3.Automation.Tests;

public class RetryTests
{
    [Fact]
    public void Until_ReturnsValue_WhenConditionIsAlreadyMet()
    {
        var value = Retry.Until(
            () => 42,
            static v => v == 42,
            TimeSpan.FromSeconds(1),
            TimeSpan.FromMilliseconds(10));

        Assert.Equal(42, value);
    }

    [Fact]
    public void Until_RetriesUntilConditionMet()
    {
        var attempts = 0;

        var value = Retry.Until(
            () => ++attempts,
            static v => v >= 3,
            TimeSpan.FromSeconds(2),
            TimeSpan.FromMilliseconds(10));

        Assert.Equal(3, value);
    }

    [Fact]
    public void Until_RetriesTransientExceptions()
    {
        var attempts = 0;

        var value = Retry.Until(
            () =>
            {
                if (++attempts < 3)
                {
                    throw new InvalidOperationException("transient");
                }

                return attempts;
            },
            static v => v >= 3,
            TimeSpan.FromSeconds(2),
            TimeSpan.FromMilliseconds(10));

        Assert.Equal(3, value);
    }

    [Fact]
    public void Until_ThrowsTimeoutException_WhenConditionIsNeverMet()
    {
        var exception = Assert.Throws<TimeoutException>(() =>
            Retry.Until(
                static () => false,
                TimeSpan.FromMilliseconds(100),
                TimeSpan.FromMilliseconds(10)));

        Assert.Contains("未满足", exception.Message);
    }

    [Fact]
    public void Until_DoesNotSwallowException_WhenRetryFilterDeclines()
    {
        Assert.Throws<ArgumentException>(() =>
            Retry.Until<int>(
                () => throw new ArgumentException("fatal"),
                static _ => true,
                TimeSpan.FromSeconds(1),
                TimeSpan.FromMilliseconds(10),
                static ex => ex is not ArgumentException));
    }

    [Fact]
    public void Until_RejectsNonPositivePollInterval()
    {
        Assert.Throws<ArgumentOutOfRangeException>(() =>
            Retry.Until(
                static () => true,
                TimeSpan.FromSeconds(1),
                TimeSpan.Zero));
    }

    [Fact]
    public async Task UntilAsync_ReturnsValue()
    {
        var value = await Retry.UntilAsync(
            () => Task.FromResult(7),
            static v => v == 7,
            TimeSpan.FromSeconds(1),
            TimeSpan.FromMilliseconds(10));

        Assert.Equal(7, value);
    }

    [Fact]
    public async Task UntilAsync_HonorsCancellation()
    {
        using var cancellation = new CancellationTokenSource(TimeSpan.FromMilliseconds(50));

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            Retry.UntilAsync(
                static () => Task.FromResult(false),
                static v => v,
                TimeSpan.FromSeconds(5),
                TimeSpan.FromMilliseconds(10),
                cancellationToken: cancellation.Token));
    }
}
