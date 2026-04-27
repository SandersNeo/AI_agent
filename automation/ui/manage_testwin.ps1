param(
    [ValidateSet("status", "start", "stop", "reset", "agent", "console", "tunnel-start", "tunnel-stop", "tunnel-status", "sendkey", "heartbeat", "ready", "recover")]
    [string]$Action = "status",

    [int]$VmId = 102,
    [string]$Node = "pve2",
    [int]$UiPort = 58006,
    [string]$Keys = "",
    [int]$HeartbeatMaxAgeSec = 180,
    [int]$ReadyTimeoutSec = 600,
    [string]$JobsRoot = "D:\EDTApps\AI_agent\automation\logs\vm_ui_jobs"
)

$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

function Get-LogRoot {
    $repoRoot = Get-RepoRoot
    $path = Join-Path $repoRoot "automation\logs\testwin"
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    return $path
}

function Get-TunnelStatePath {
    return Join-Path (Get-LogRoot) "pve_ui_tunnel.json"
}

function Get-TunnelLogPath {
    return Join-Path (Get-LogRoot) "pve_ui_tunnel.log"
}

function Get-TunnelErrLogPath {
    return Join-Path (Get-LogRoot) "pve_ui_tunnel.err.log"
}

function Get-HeartbeatPath {
    return Join-Path $JobsRoot "guest_ui_agent_heartbeat.json"
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message"
}

function Invoke-Pve {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    & ssh $Node $Command
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed: $Command"
    }
}

function Get-VmStatus {
    $statusText = (& ssh $Node "qm status $VmId" 2>$null)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($statusText)) {
        throw "Не удалось получить статус VM $VmId на $Node."
    }
    if ($statusText -match "status:\s+(\w+)") {
        return $Matches[1]
    }
    return $statusText.Trim()
}

function Get-HeartbeatState {
    $heartbeatPath = Get-HeartbeatPath
    if (-not (Test-Path $heartbeatPath)) {
        return [pscustomobject]@{
            Exists = $false
            IsFresh = $false
            AgeSec = $null
            Path = $heartbeatPath
        }
    }

    $raw = Get-Content $heartbeatPath -Raw -ErrorAction Stop
    $json = $raw | ConvertFrom-Json
    $timestamp = [datetimeoffset]::Parse($json.timestamp_utc)
    $ageSec = [math]::Round(((Get-Date).ToUniversalTime() - $timestamp.UtcDateTime).TotalSeconds, 1)

    return [pscustomobject]@{
        Exists = $true
        IsFresh = ($ageSec -ge 0 -and $ageSec -le $HeartbeatMaxAgeSec)
        AgeSec = $ageSec
        TimestampUtc = $json.timestamp_utc
        JobsRoot = $json.jobs_root
        RepoRoot = $json.repo_root
        Pid = $json.pid
        Path = $heartbeatPath
    }
}

function Show-HeartbeatState {
    $state = Get-HeartbeatState
    if (-not $state.Exists) {
        Write-Warn "Heartbeat не найден: $($state.Path)"
        return $state
    }

    Write-Info ("Heartbeat: fresh={0}, ageSec={1}, pid={2}" -f $state.IsFresh, $state.AgeSec, $state.Pid)
    if ($state.AgeSec -lt 0) {
        Write-Warn "Heartbeat из будущего. Похоже, часы внутри VM или на хосте рассинхронизированы."
    }
    Write-Info ("Heartbeat timestamp UTC: {0}" -f $state.TimestampUtc)
    Write-Info ("Guest jobs root: {0}" -f $state.JobsRoot)
    Write-Info ("Guest repo root: {0}" -f $state.RepoRoot)
    return $state
}

function Wait-HeartbeatReady {
    param([int]$TimeoutSec)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $vmStatus = Get-VmStatus
        if ($vmStatus -ne "running") {
            Write-Info "VM status: $vmStatus"
            Start-Sleep -Seconds 5
            continue
        }

        $state = Get-HeartbeatState
        if ($state.Exists -and $state.IsFresh) {
            Write-Info "Guest UI agent heartbeat is fresh."
            return $state
        }

        if (-not $state.Exists) {
            Write-Info "Heartbeat ещё не появился."
        }
        else {
            Write-Info ("Heartbeat найден, но устарел: ageSec={0}" -f $state.AgeSec)
        }
        Start-Sleep -Seconds 5
    }

    throw "Не дождались свежего heartbeat от guest UI agent за $TimeoutSec сек."
}

function Recover-TestWin {
    Write-Info "Запускаю восстановление testwin через Proxmox."
    $status = Get-VmStatus
    Write-Info "Текущий статус VM: $status"

    if ($status -ne "running") {
        Invoke-Pve "qm start $VmId"
    }
    else {
        Invoke-Pve "qm reset $VmId"
    }

    Wait-HeartbeatReady -TimeoutSec $ReadyTimeoutSec | Out-Null
    Write-Info "testwin снова готов к UI-тестам."
}

function Test-LocalPortOpen {
    param([int]$Port)

    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne(1000, $false)
        if (-not $connected) {
            $client.Close()
            return $false
        }
        $client.EndConnect($async)
        $client.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Get-ExistingTunnelState {
    $statePath = Get-TunnelStatePath
    if (-not (Test-Path $statePath)) {
        return $null
    }

    try {
        $state = Get-Content $statePath -Raw | ConvertFrom-Json
        if ($state.Pid -and (Get-Process -Id $state.Pid -ErrorAction SilentlyContinue)) {
            return $state
        }
    }
    catch {
    }

    Remove-Item $statePath -Force -ErrorAction SilentlyContinue
    return $null
}

function Start-UiTunnel {
    $existing = Get-ExistingTunnelState
    if ($existing -and (Test-LocalPortOpen -Port $UiPort)) {
        Write-Info "SSH tunnel already running on 127.0.0.1:$UiPort (PID $($existing.Pid))."
        return $existing
    }

    $args = @(
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-N",
        "-L", "127.0.0.1:$UiPort`:127.0.0.1:8006",
        $Node
    )
    $logPath = Get-TunnelLogPath
    $errLogPath = Get-TunnelErrLogPath
    $escapedArgs = ($args | ForEach-Object {
        if ($_ -match '\s') {
            '"' + $_.Replace('"', '\"') + '"'
        }
        else {
            $_
        }
    }) -join " "
    $command = "ssh $escapedArgs 1>> `"$logPath`" 2>> `"$errLogPath`""
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $command) `
        -PassThru `
        -WindowStyle Hidden
    Start-Sleep -Seconds 2

    if ($process.HasExited -or -not (Test-LocalPortOpen -Port $UiPort)) {
        $details = ""
        if (Test-Path $logPath) {
            $details = Get-Content $logPath -Raw
        }
        if (Test-Path $errLogPath) {
            $details = ($details + "`n" + (Get-Content $errLogPath -Raw)).Trim()
        }
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        catch {
        }
        throw ("Failed to start SSH tunnel on 127.0.0.1:{0}. {1}" -f $UiPort, $details.Trim())
    }

    $state = [pscustomobject]@{
        Pid = $process.Id
        Port = $UiPort
        Node = $Node
        LogPath = $logPath
        ErrLogPath = $errLogPath
        CreatedAt = (Get-Date).ToString("s")
    }
    $state | ConvertTo-Json | Set-Content -Path (Get-TunnelStatePath) -Encoding UTF8
    Write-Info "SSH tunnel started: https://127.0.0.1:$UiPort/"
    return $state
}

function Stop-UiTunnel {
    $state = Get-ExistingTunnelState
    if (-not $state) {
        Write-Info "No active SSH tunnel found."
        return
    }

    try {
        Stop-Process -Id $state.Pid -Force -ErrorAction Stop
        Write-Info "SSH tunnel stopped (PID $($state.Pid))."
    }
    finally {
        Remove-Item (Get-TunnelStatePath) -Force -ErrorAction SilentlyContinue
    }
}

function Show-TunnelStatus {
    $state = Get-ExistingTunnelState
    if (-not $state) {
        Write-Info "SSH tunnel is not running."
        return
    }

    $isOpen = Test-LocalPortOpen -Port ([int]$state.Port)
    Write-Info ("Tunnel PID={0}, port={1}, node={2}, open={3}" -f $state.Pid, $state.Port, $state.Node, $isOpen)
    Write-Info ("UI URL: https://127.0.0.1:{0}/" -f $state.Port)
    if ($state.LogPath) {
        Write-Info ("Tunnel log: {0}" -f $state.LogPath)
    }
    if ($state.ErrLogPath) {
        Write-Info ("Tunnel err log: {0}" -f $state.ErrLogPath)
    }
}

function Open-ProxmoxConsole {
    $null = Start-UiTunnel
    $url = "https://127.0.0.1:$UiPort/"
    Write-Info "Opening Proxmox UI. After login, open VM $Node / $VmId (testwin)."
    Start-Process $url | Out-Null
}

switch ($Action) {
    "status" {
        Invoke-Pve "qm status $VmId && qm config $VmId | sed -n '1,40p'"
    }
    "start" {
        Invoke-Pve "qm start $VmId"
    }
    "stop" {
        Invoke-Pve "qm stop $VmId"
    }
    "reset" {
        Invoke-Pve "qm reset $VmId"
    }
    "agent" {
        Invoke-Pve "qm agent $VmId ping"
    }
    "heartbeat" {
        Show-HeartbeatState | Out-Null
    }
    "ready" {
        Wait-HeartbeatReady -TimeoutSec $ReadyTimeoutSec | Out-Null
    }
    "recover" {
        Recover-TestWin
    }
    "console" {
        Open-ProxmoxConsole
    }
    "tunnel-start" {
        $null = Start-UiTunnel
    }
    "tunnel-stop" {
        Stop-UiTunnel
    }
    "tunnel-status" {
        Show-TunnelStatus
    }
    "sendkey" {
        if ([string]::IsNullOrWhiteSpace($Keys)) {
            throw "For sendkey, specify -Keys, for example: -Keys ctrl-alt-delete"
        }
        Invoke-Pve "qm sendkey $VmId $Keys"
    }
}
