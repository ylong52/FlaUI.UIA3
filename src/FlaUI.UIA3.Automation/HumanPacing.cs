namespace FlaUI.UIA3.Automation;

/// <summary>
/// 拟人节奏：随机化的停顿、鼠标轨迹与键盘节奏，避免固定间隔的机械行为。
/// 所有区间在乘以 <see cref="PaceMultiplier"/> 后生效。
/// </summary>
public sealed class HumanPacing
{
    private readonly Random _random = new();
    private readonly double _scale;

    public HumanPacing(double scale = 1.0)
        => _scale = Math.Clamp(scale, 0.1, 5.0);

    /// <summary>普通动作之间的短停顿。</summary>
    public void ActionGap() => Sleep(350, 900);

    /// <summary>字段之间的停顿，模拟输入前的思考。</summary>
    public void FieldGap() => Sleep(900, 2200);

    /// <summary>选项之间的停顿。</summary>
    public void OptionGap() => Sleep(400, 1100);

    /// <summary>读完一屏再继续。</summary>
    public void ReadingPause() => Sleep(1500, 3600);

    /// <summary>步骤切换后的停顿。</summary>
    public void AfterStep() => Sleep(1100, 2400);

    /// <summary>开始输入前的停顿。</summary>
    public void BeforeTyping() => Sleep(400, 1000);

    /// <summary>单个字符的输入间隔。</summary>
    public void CharDelay() => Sleep(45, 115);

    /// <summary>标点后的额外停顿。</summary>
    public void PunctuationPause() => Sleep(140, 380);

    /// <summary>鼠标移动前后的停顿。</summary>
    public void MouseTravel() => Sleep(120, 300);

    public void MouseSettle() => Sleep(70, 190);

    public int Next(int minimumInclusive, int maximumInclusive)
        => _random.Next(minimumInclusive, maximumInclusive + 1);

    public int Jitter(int range)
        => _random.Next(-range, range + 1);

    private void Sleep(int minimumInclusive, int maximumInclusive)
    {
        var milliseconds = (int)(_random.Next(minimumInclusive, maximumInclusive + 1) * _scale);
        Thread.Sleep(Math.Max(0, milliseconds));
    }
}
