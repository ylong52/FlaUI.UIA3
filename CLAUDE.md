# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Architecture, ASCII flow/sequence diagrams, and the answering rationale are documented (in Chinese)
in `开发文档.md` — read it first before changing the survey pipeline.

## What this project is

A C# automation scaffold built on **FlaUI.UIA3 5.0.0** for driving **Chrome/Edge** pages that
use **Vue custom radio / checkbox components**. Interaction and assertions go through the
Windows UI Automation (UIA) tree — **no screenshots, no CDP, no JS injection**.

Design goals (from `README.md`): fast development, querying complex Vue controls, state
verification, long-term maintainability, and recovery from transient UI failures.

## Python subproject: `survey_ai_agent/`

An independent Python service (PydanticAI + DeepSeek + FastAPI + MySQL) lives in
`survey_ai_agent/`. See `survey_ai_agent/README.md` for install/run/tests. It shares the
`survey_bg_manage` MariaDB database (SQL database name only) and creates `ai_agent_*` tables.
It is unrelated to the C# FlaUI code except for location.

Portable MariaDB is maintained inside this repo: binaries in `tools/mariadb/`, data directory
in `tools/mariadb-data/`. `start.cmd` step `[1/5]` boots it on `127.0.0.1:3306` with
`root` / empty password. The old external `survey_bg_manage` source tree is no longer needed.

## Local run config: `survey.conf`

`start.cmd` reads the survey address from `survey.conf` in the repo root instead of hardcoding
it. Format is one `KEY=VALUE` per line, `#` starts a comment:

```
SURVEY_URL=https://api.x-survey.com/test/survey-test.html
```

Edit that file to point at another survey; the value is used for both the Chrome window and the
`--url` argument of the executor. A missing file or missing key aborts immediately with
`[ERROR] SURVEY_URL is missing`.

## Reading `README.md`

`README.md` is **GBK-encoded**, not UTF-8 (despite the `.md` extension). Decode explicitly:

```sh
iconv -f GBK -t UTF-8 README.md
```

Reading it with a UTF-8 tool produces mojibake.

## Environment

- .NET SDK **10.0.403** is installed at `C:\Program Files\dotnet`.
- Projects target **`net8.0-windows`** (FlaUI's supported TFM) and set `<RollForward>Major</RollForward>`,
  so they build with SDK 10 and run on the installed .NET 10 runtime. Only the .NET 10 runtime
  is present; do not target `net8.0-windows` without `RollForward` unless you install the .NET 8
  desktop runtime.
- NuGet source is pinned in `nuget.config` (nuget.org); the machine had no global sources.
- In a shell started before installation, `dotnet` may not be on `PATH` yet. Use the full path
  `"C:\Program Files\dotnet\dotnet.exe"` or restart the terminal.

## Commands

```sh
# restore / build
dotnet restore FlaUI.UIA3.Automation.sln
dotnet build FlaUI.UIA3.Automation.sln -c Debug

# all tests
dotnet test FlaUI.UIA3.Automation.sln -c Debug

# a single test class or test
dotnet test FlaUI.UIA3.Automation.sln --filter "FullyQualifiedName~RetryTests"
dotnet test FlaUI.UIA3.Automation.sln --filter "FullyQualifiedName~AutomationOptionsTests.Parse_ReturnsDefaults"

# run the CLI
dotnet run --project src/FlaUI.UIA3.Automation -- --help
dotnet run --project src/FlaUI.UIA3.Automation -- --browser edge --url https://example.com --list
dotnet run --project src/FlaUI.UIA3.Automation -- --attach <pid> --check <automationId> --toggle
```

The E2E test is opt-in: set `FLAUI_E2E_PID` to a running Chrome/Edge PID before `dotnet test`.
Without it the test returns early.

## Architecture

```
FlaUI.UIA3.Automation.sln          classic .sln (SDK 10 defaults to .slnx; this is intentionally .sln)
src/FlaUI.UIA3.Automation/         console host + reusable automation code
  Program.cs                       CLI entry: parse args, attach/launch, list/inspect/toggle
  AutomationOptions.cs             argument parsing + tunables; pure C#, unit-tested
  BrowserSession.cs                wraps FlaUI.Core.Application + UIA3Automation; launch/attach,
                                   resolve chrome.exe/msedge.exe, GetMainWindow
  VueControlHelper.cs              locate by AutomationId/Name; read/set checked state;
                                   wait for state; human-readable Describe()
  Retry.cs                         polling helper that tolerates transient UIA exceptions
tests/FlaUI.UIA3.Automation.Tests/ xUnit
  RetryTests.cs                    retry/timeout/cancellation behavior
  AutomationOptionsTests.cs        parser coverage
  BrowserIntegrationTests.cs      E2E, gated by FLAUI_E2E_PID
```

Data flow: `AutomationOptions.Parse` → `BrowserSession.AttachOrLaunch` → `GetMainWindow` →
`VueControlHelper` find/read/toggle → `Retry` polling for verification.

Key design rules:

- **UIA only.** Do not add CDP calls, `ExecuteScript`, or screenshot-based flows. The
  `--force-renderer-accessibility` launch flag in `BrowserSession` is a Chromium startup switch
  (not CDP/JS injection) and exists to expose web content reliably to UIA.
- **Prefer patterns over ControlType.** Vue widgets may surface as `Custom`/`Group`/`ListItem`
  rather than `CheckBox`/`RadioButton`. `VueControlHelper.TryGetChecked`/`SetChecked` try
  Toggle → SelectionItem → Invoke. Extend `FindChoices` or add a pattern-scanning finder when
  `ControlType` filtering misses a widget.
- **Retry everything transient.** UIA raises `ElementNotAvailable`/COM errors while the page is
  rendering or re-rendering; go through `Retry` instead of one-shot reads.
- **Verify after acting.** After toggling, poll the observable state via `WaitForChecked`; do not
  assume the click landed.

## Survey test page mode

`--survey-test` runs `SurveyTestAnswerer.cs`, a fixed-answer walkthrough of
`https://api.x-survey.com/test/survey-test.html` (9 steps, 16 questions). It **stops at step 9
and does not submit by default**; add `--submit` to click Submit. The answers live in the
`AnswerStepN` methods.

The walkthrough is deliberately human-paced (`HumanPacing.cs`): randomized pauses, eased mouse
trajectories with real clicks, and character-by-character keyboard typing instead of UIA
selection/value writes. `--pace fast|normal|slow|<multiplier>` scales the pauses (default
`normal`). If the page is already submitted, the answerer presses F5 to reset to step 1 first.

Page-specific facts that make this work:

- Question titles (`.qtitle`/`.qsub`) are replaced client-side with PNG `<img>`s with empty alt,
  so they do **not** appear in the UIA tree. Answer by option text and control order instead.
- Option labels and step titles remain real text.
- Matrices (Q11/Q12) are radio inputs with no accessible names; select by document-order index
  (`row * columnCount + column`).
- Q10 allocation is four `Edit`s in row order; values must sum to 100.
- Q15 ranking is mouse drag-and-drop; the script keeps the page's default order.
- Q16 importance is a `Slider` using the RangeValue pattern.

## Generic per-page mode (third-party surveys)

`--survey-ai` chooses the execution strategy from the live page:

- If `Step N of 9` text exists → legacy 9-step flow for the built-in test survey.
- Otherwise → generic per-page flow, which works for arbitrary surveys (Qualtrics-style,
  Angular Material, etc.).

Generic flow, once per page:

1. Snapshot the UIA tree (visible texts + real controls) — no CDP, no JS injection.
2. Synthesize standard HTML (`div.question` + `qtitle` + `input/select/label`) so the existing
   Python extractor applies unchanged. Question ids are `p<page>q<n>` to keep reused answers
   from colliding across pages.
3. POST to `/api/v1/agent/analyze` with `page_id=page-N` and `page_adapter=html`.
4. Fill only `status=ready` answers via real controls (radio/checkbox/edit/spinner/combo/slider).
5. Wait until the `Next`/`Continue` button is enabled, click it, wait for the page signature to
   change, then repeat.

Safety rules: `Submit`/`Finish`/`Done` buttons are **never** clicked; if `Next` stays disabled the
runner stops and reports which facts are missing from the profile. Screened-out / thank-you pages
(`not able to complete`, `did not match the target audience`, `screening in progress`, …) end the
run with exit code 0.

Exit codes: `7` = Next disabled or page did not change, `8` = no questions recognized on a page
(and the page is not a known end page). For debugging a specific page, dump its synthesized HTML:

```sh
dotnet run --project src/FlaUI.UIA3.Automation -- --attach <pid> --dump-page page.html
```

Missing personal facts (zip code, income, …) are intentionally not invented: the rule engine marks
them `needs_review`, the LLM is asked only for questions it can justify from the profile, and the
runner stops instead of guessing.

## Launching the original Chrome

`Application.Launch` can capture a short-lived launcher process: Chrome then re-executes and the
real browser process (which owns the window) has a different PID. If `GetMainWindow` reports
`Could not find process with id`, find the Chrome process with `MainWindowTitle` set and use
`--attach <pid>` instead. Example with an isolated profile so it does not join an already-running
Chromium:

```sh
dotnet run --project src/FlaUI.UIA3.Automation -- \
  --browser chrome --url "https://api.x-survey.com/test/survey-test.html" \
  --extra-arg "--user-data-dir=%TEMP%\flaui-chrome-profile" \
  --extra-arg "--no-first-run" --extra-arg "--no-default-browser-check"
```

## FlaUI 5 gotchas

- `Application` is ambiguous with `System.Windows.Forms.Application` because `UseWindowsForms`
  brings in WinForms implicit usings. `BrowserSession.cs` aliases
  `using Application = FlaUI.Core.Application;`.
- Pattern properties return `AutomationProperty<T>`, not raw values: use
  `toggle.ToggleState.ValueOrDefault` (see `VueControlHelper`).
- `Application.GetMainWindow` returns `Window?`; `BrowserSession.GetMainWindow` converts a null
  result into a `TimeoutException`.
