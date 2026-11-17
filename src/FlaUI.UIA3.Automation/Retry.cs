using System.Diagnostics;

namespace FlaUI.UIA3.Automation;

/// <summary>
/// 面向 UI 自动化的重试：轮询直到条件满足或超时。
/// UI Automation 的元素查找/读取会因页面渲染、元素失效（ElementNotAvailable）而瞬时失败，
/// 因此默认吞掉单次异常继续轮询。
/// </summary>
public static class Retry
{
    public static T Until<T>(
        Func<T> probe,
        Func<T, bool> isDone,
        TimeSpan timeout,
        TimeSpan pollInterval,
        Func<Exception, bool>? shouldRetry = null)
    {
        ArgumentNullException.ThrowIfNull(probe);
        ArgumentNullException.ThrowIfNull(isDone);
        if (timeout < TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(timeout));
        }

        if (pollInterval <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(pollInterval));
        }

        var stopwatch = Stopwatch.StartNew();
        Exception? lastException = null;

        while (true)
        {
            try
            {
                var value = probe();
                if (isDone(value))
                {
                    return value;
                }

                lastException = null;
            }
            catch (Exception ex) when (shouldRetry?.Invoke(ex) ?? true)
            {
                lastException = ex;
            }

            if (stopwatch.Elapsed >= timeout)
            {
                throw new TimeoutException(
                    $"条件在 {timeout} 内未满足。最后一次异常：{lastException?.Message ?? "无"}",
                    lastException);
            }

            Thread.Sleep(pollInterval);
        }
    }

    public static void Until(
        Func<bool> condition,
        TimeSpan timeout,
        TimeSpan pollInterval,
        Func<Exception, bool>? shouldRetry = null)
    {
        ArgumentNullException.ThrowIfNull(condition);
        Until(
            probe: () => condition(),
            isDone: static value => value,
            timeout,
            pollInterval,
            shouldRetry);
    }

    public static async Task<T> UntilAsync<T>(
        Func<Task<T>> probe,
        Func<T, bool> isDone,
        TimeSpan timeout,
        TimeSpan pollInterval,
        Func<Exception, bool>? shouldRetry = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(probe);
        ArgumentNullException.ThrowIfNull(isDone);
        if (timeout < TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(timeout));
        }

        if (pollInterval <= TimeSpan.Zero)
        {
            throw new ArgumentOutOfRangeException(nameof(pollInterval));
        }

        var stopwatch = Stopwatch.StartNew();
        Exception? lastException = null;

        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();

            try
            {
                var value = await probe().ConfigureAwait(false);
                if (isDone(value))
                {
                    return value;
                }

                lastException = null;
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception ex) when (shouldRetry?.Invoke(ex) ?? true)
            {
                lastException = ex;
            }

            if (stopwatch.Elapsed >= timeout)
            {
                throw new TimeoutException(
                    $"条件在 {timeout} 内未满足。最后一次异常：{lastException?.Message ?? "无"}",
                    lastException);
            }

            await Task.Delay(pollInterval, cancellationToken).ConfigureAwait(false);
        }
    }
}
