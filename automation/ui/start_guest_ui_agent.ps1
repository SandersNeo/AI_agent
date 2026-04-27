$ErrorActionPreference = "Stop"

function Resolve-PythonCommand {
    $candidates = @()

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return @($py.Source, "-3")
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return @($python.Source)
    }

    $pythonExe = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python" -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($pythonExe) {
        return @($pythonExe.FullName)
    }

    if (Test-Path "C:\Python\python.exe") {
        return @("C:\Python\python.exe")
    }

    throw "Python executable not found in guest VM."
}

function Ensure-StartupLauncher {
    param(
        [string]$ScriptPath
    )

    $startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
    $startupCmd = Join-Path $startupDir "Guest UI Agent.cmd"
    $content = @(
        "@echo off",
        "powershell -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    ) -join "`r`n"
    Set-Content -Path $startupCmd -Value $content -Encoding ASCII
    return $startupCmd
}

function Ensure-ScheduledTaskLauncher {
    param(
        [string]$ScriptPath
    )

    $taskName = "AI Guest UI Agent"
    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $taskCommand = "`"$psExe`" -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

    try {
        schtasks.exe /Create /TN $taskName /SC ONSTART /RU SYSTEM /RL HIGHEST /TR $taskCommand /F | Out-Null
        schtasks.exe /Create /TN "${taskName} (Logon)" /SC ONLOGON /RU SYSTEM /RL HIGHEST /TR $taskCommand /F | Out-Null
        return @($taskName, "${taskName} (Logon)")
    }
    catch {
        throw "Не удалось зарегистрировать Scheduled Task для guest UI agent: $($_.Exception.Message)"
    }
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$jobsRoot = Join-Path $repoRoot "automation\logs\vm_ui_jobs"
$launcherLog = Join-Path $jobsRoot "guest_ui_agent_launcher.log"

New-Item -ItemType Directory -Force -Path $jobsRoot | Out-Null

try {
    $agentScript = Join-Path $PSScriptRoot "guest_ui_agent.py"
    $pythonCommand = Resolve-PythonCommand
    $pythonExe = $pythonCommand[0]
    $pythonArgs = @()
    if ($pythonCommand.Length -gt 1) {
        $pythonArgs = $pythonCommand[1..($pythonCommand.Length - 1)]
    }

    $startupCmd = Ensure-StartupLauncher -ScriptPath $PSCommandPath
    $taskNames = Ensure-ScheduledTaskLauncher -ScriptPath $PSCommandPath
    @(
        "[INFO] Startup launcher ensured: $startupCmd"
        "[INFO] Scheduled tasks ensured: $($taskNames -join ', ')"
        "[INFO] Python: $pythonExe"
        "[INFO] Jobs root: $jobsRoot"
        "[INFO] Agent script: $agentScript"
    ) | Out-File -FilePath $launcherLog -Encoding utf8 -Append

    & $pythonExe @pythonArgs $agentScript --jobs-root $jobsRoot 2>&1 |
        Tee-Object -FilePath $launcherLog -Append
    exit $LASTEXITCODE
}
catch {
    $_ | Out-String | Out-File -FilePath $launcherLog -Encoding utf8 -Append
    throw
}
