param(
    [string]$Command,

    [string]$ExecutablePath,

    [string]$ExecutableArguments,

    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [string]$FfmpegPath,
    [int]$Framerate = 12,
    [int]$Width = 0,
    [int]$Height = 0,
    [int]$FixedDurationSec = 0,
    [string]$StartMarkerPath = "",
    [int]$StartMarkerTimeoutSec = 180,
    [switch]$WindowsCompatible
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($Command) -and [string]::IsNullOrWhiteSpace($ExecutablePath)) {
    throw "Specify either -Command or -ExecutablePath."
}

function Resolve-FfmpegPath {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (Test-Path $ExplicitPath) {
            return (Resolve-Path $ExplicitPath).Path
        }
        throw "ffmpeg not found: $ExplicitPath"
    }

    $fromPath = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    $candidates = @(
        "C:\Tools\ffmpeg\bin\ffmpeg.exe",
        "C:\ffmpeg\bin\ffmpeg.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-*\bin\ffmpeg.exe"
    )
    foreach ($candidate in $candidates) {
        $resolved = Get-ChildItem -Path $candidate -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($resolved) {
            return $resolved.FullName
        }
    }

    throw "ffmpeg not found. Install it or pass -FfmpegPath."
}

function Quote-Arg {
    param([string]$Value)
    if ($Value -match '[\s"]') {
        return '"' + $Value.Replace('"', '\"') + '"'
    }
    return $Value
}

$FfmpegPath = Resolve-FfmpegPath -ExplicitPath $FfmpegPath

$videoDir = Split-Path -Parent $VideoPath
if ($videoDir) {
    New-Item -ItemType Directory -Force -Path $videoDir | Out-Null
}
$ffmpegLogPath = "$VideoPath.ffmpeg.log"
$videoExtension = [System.IO.Path]::GetExtension($VideoPath).ToLowerInvariant()
$useWindowsProfile = $WindowsCompatible.IsPresent -or $videoExtension -eq ".wmv"

$desktopArgs = @(
    "-y",
    "-loglevel", "error",
    "-f", "gdigrab",
    "-framerate", $Framerate.ToString(),
    "-draw_mouse", "1"
)

if ($FixedDurationSec -gt 0) {
    $desktopArgs = @("-nostdin") + $desktopArgs
}

if ($Width -gt 0 -and $Height -gt 0) {
    $desktopArgs += @("-video_size", "$Width`x$Height")
}

$desktopArgs += @("-i", "desktop")

$encodeArgs = if ($useWindowsProfile) {
    $args = @(
        "-c:v", "wmv2",
        "-pix_fmt", "yuv420p",
        "-qscale:v", "3"
    )
    if ($FixedDurationSec -gt 0) {
        $args += @("-t", $FixedDurationSec.ToString())
    }
    $args += @($VideoPath)
    $args
}
else {
    $args = @(
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart"
    )
    if ($FixedDurationSec -gt 0) {
        $args += @("-t", $FixedDurationSec.ToString())
    }
    $args += @($VideoPath)
    $args
}

$ffmpegArgs = @(
    $desktopArgs + $encodeArgs
) | ForEach-Object { $_ }

$recorder = $null
$runnerProcess = $null
try {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FfmpegPath
    $psi.Arguments = ($ffmpegArgs | ForEach-Object { Quote-Arg ([string]$_) }) -join " "
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = ($FixedDurationSec -le 0)
    $psi.RedirectStandardError = ($FixedDurationSec -le 0)
    $psi.RedirectStandardOutput = ($FixedDurationSec -le 0)
    $psi.CreateNoWindow = $true

    $runnerPsi = New-Object System.Diagnostics.ProcessStartInfo
    if (-not [string]::IsNullOrWhiteSpace($ExecutablePath)) {
        $runnerPsi.FileName = $ExecutablePath
        $runnerPsi.Arguments = $ExecutableArguments
    }
    else {
        $runnerPsi.FileName = "cmd.exe"
        $runnerPsi.Arguments = "/c $Command"
    }
    $runnerPsi.UseShellExecute = $false
    $runnerPsi.CreateNoWindow = $true

    if (-not [string]::IsNullOrWhiteSpace($StartMarkerPath)) {
        Remove-Item -LiteralPath $StartMarkerPath -Force -ErrorAction SilentlyContinue
        $runnerProcess = [System.Diagnostics.Process]::Start($runnerPsi)
        $deadline = (Get-Date).AddSeconds($StartMarkerTimeoutSec)
        while (-not (Test-Path -LiteralPath $StartMarkerPath)) {
            if ($runnerProcess.HasExited) {
                $global:LASTEXITCODE = $runnerProcess.ExitCode
                throw "test command exited before recording start marker appeared."
            }
            if ((Get-Date) -gt $deadline) {
                throw "recording start marker timeout: $StartMarkerPath"
            }
            Start-Sleep -Milliseconds 200
        }
    }

    $recorder = New-Object System.Diagnostics.Process
    $recorder.StartInfo = $psi
    $null = $recorder.Start()
    Start-Sleep -Milliseconds 500

    if ($recorder.HasExited) {
        $earlyOutput = ""
        if ($FixedDurationSec -le 0) {
            $earlyOutput = ($recorder.StandardOutput.ReadToEnd() + [Environment]::NewLine + $recorder.StandardError.ReadToEnd()).Trim()
        }
        if ($earlyOutput) {
            Set-Content -Path $ffmpegLogPath -Value $earlyOutput -Encoding UTF8
        }
        throw "ffmpeg exited before test command started."
    }

    if ($null -eq $runnerProcess) {
        $runnerProcess = [System.Diagnostics.Process]::Start($runnerPsi)
    }
    $runnerProcess.WaitForExit()
    $global:LASTEXITCODE = $runnerProcess.ExitCode
}
finally {
    if ($recorder -and -not $recorder.HasExited) {
        try {
            if ($FixedDurationSec -gt 0) {
                $waitMs = ($FixedDurationSec * 1000) + 30000
                if (-not $recorder.WaitForExit($waitMs)) {
                    $recorder.Kill()
                    $null = $recorder.WaitForExit(5000)
                }
            }
            else {
                $recorder.StandardInput.WriteLine("q")
                $recorder.StandardInput.Flush()
                $recorder.StandardInput.Close()
                if (-not $recorder.WaitForExit(30000)) {
                    $recorder.Kill()
                    $null = $recorder.WaitForExit(5000)
                }
            }
            if ($FixedDurationSec -le 0) {
                $finalOutput = ($recorder.StandardOutput.ReadToEnd() + [Environment]::NewLine + $recorder.StandardError.ReadToEnd()).Trim()
                if ($finalOutput) {
                    Set-Content -Path $ffmpegLogPath -Value $finalOutput -Encoding UTF8
                }
            }
        }
        catch {
            try {
                $recorder.Kill()
            }
            catch {
            }
        }
    }
}

exit $global:LASTEXITCODE
