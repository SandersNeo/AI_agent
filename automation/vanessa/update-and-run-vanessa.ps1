[CmdletBinding()]
param(
    [string]$PlatformExe = 'C:\Program Files\1cv8\8.3.27.1859\bin\1cv8.exe',
    [string]$ConnectionString = '',
    [string]$UserName = '',
    [string]$Password = '',
    [string]$LogDir = "$PSScriptRoot\logs",
    [string]$VanessaRunnerEpf = "$PSScriptRoot\vanessa-automation-single.epf",
    [string]$VAExtensionCfe = "$PSScriptRoot\VAExtension.cfe",
    [string]$FeatureFile = "$PSScriptRoot\AddCatalog2TestEntry.feature",
    [string]$VAParamsPath = "$PSScriptRoot\VAParams.json",
    [switch]$SkipDbUpdate,
    [switch]$InstallVAExtension,
    [switch]$InstallVanessaExt
)

<# 
.SYNOPSIS
Обновляет конфигурацию БД через 1С:Предприятие и запускает сценарий Vanessa Automation,
который открывает Справочник2 и создает тестовую запись.

.EXAMPLE
.\update-and-run-vanessa.ps1 `
    -ConnectionString 'File="D:\EDT_base\test1";' `
    -UserName 'tech' -Password 'secret'

Скрипт предполагает, что все нужные артефакты (epf, feature, VAParams) лежат рядом в текущей папке.
#>

$ErrorActionPreference = 'Stop'

# Загрузка .env из корня проекта (если есть)
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$envPath = Join-Path $projectRoot '.env'
if (Test-Path -LiteralPath $envPath -PathType Leaf) {
    Get-Content -LiteralPath $envPath -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$' -and $matches[1] -notmatch '^\s*#') {
            [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
        }
    }
}

# Строка подключения: параметр → 1C_CONNECTION_STRING из .env/env → значение по умолчанию
if (-not $ConnectionString -and $env:1C_CONNECTION_STRING) { $ConnectionString = $env:1C_CONNECTION_STRING }
if (-not $ConnectionString) { $ConnectionString = 'File="D:\EDT_base\КонфигурацияТест";' }
$env:1C_CONNECTION_STRING = $ConnectionString

function Test-RequiredFile {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Файл $Description не найден: $Path"
    }
}

function Invoke-Platform {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [Parameter(Mandatory)]
        [string]$OperationName
    )

    Write-Host "==> $OperationName"
    Write-Host ("    1cv8.exe {0}" -f ($Arguments -join ' '))

    $process = Start-Process -FilePath $PlatformExe -ArgumentList $Arguments -PassThru -Wait
    if ($process.ExitCode -ne 0) {
        throw "Команда 1cv8 для операции '$OperationName' завершилась с кодом $($process.ExitCode)"
    }
}

function Invoke-VanessaFeatureRun {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [Parameter(Mandatory)]
        [string]$OperationName,
        [Parameter(Mandatory)]
        [string]$LogPath,
        [Parameter(Mandatory)]
        [string]$ConnectionStringValue,
        [Parameter(Mandatory)]
        [string]$RunnerPath
    )

    Write-Host "==> $OperationName"
    Write-Host ("    1cv8.exe {0}" -f ($Arguments -join ' '))

    if (Test-Path -LiteralPath $LogPath) {
        Remove-Item -LiteralPath $LogPath -Force -ErrorAction SilentlyContinue
    }

    $process = Start-Process -FilePath $PlatformExe -ArgumentList $Arguments -PassThru

    $deadline = (Get-Date).AddMinutes(15)
    $finishedMarker = 'Выполнение сценариев закончено.'

    try {
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 2

            if ($process.HasExited) {
                break
            }

            if (Test-Path -LiteralPath $LogPath) {
                try {
                    $content = Get-Content -LiteralPath $LogPath -Raw -ErrorAction Stop
                    if ($content -like "*$finishedMarker*") {
                        Stop-VanessaTestProcesses -ConnectionStringValue $ConnectionStringValue -RunnerPath $RunnerPath
                        $process.WaitForExit(15000) | Out-Null
                        break
                    }
                } catch {
                }
            }
        }

        if (-not $process.HasExited) {
            Stop-VanessaTestProcesses -ConnectionStringValue $ConnectionStringValue -RunnerPath $RunnerPath
            $process.WaitForExit(15000) | Out-Null
        }

        if (-not $process.HasExited) {
            throw "Превышено время ожидания завершения Vanessa Automation."
        }

        if ($process.ExitCode -ne 0) {
            throw "Команда 1cv8 для операции '$OperationName' завершилась с кодом $($process.ExitCode)"
        }
    } finally {
        Stop-VanessaTestProcesses -ConnectionStringValue $ConnectionStringValue -RunnerPath $RunnerPath
    }
}

function Stop-VanessaTestProcesses {
    param(
        [string]$ConnectionStringValue,
        [string]$RunnerPath
    )

    try {
        $targets = Get-CimInstance Win32_Process | Where-Object {
            ($_.Name -like '1cv8*.exe') -and
            $_.CommandLine -and
            (
                ($_.CommandLine -like '* /TESTCLIENT *') -or
                ($_.CommandLine -like '* /TESTMANAGER *') -or
                ($RunnerPath -and $_.CommandLine -like "*$RunnerPath*")
            )
        }

        foreach ($process in $targets) {
            try {
                & taskkill.exe /PID $process.ProcessId /T /F | Out-Null
            } catch {
            }
        }

        Start-Sleep -Seconds 2

        $leftovers = Get-CimInstance Win32_Process | Where-Object {
            ($_.Name -like '1cv8*.exe') -and
            $_.CommandLine -and
            (
                ($_.CommandLine -like '* /TESTCLIENT *') -or
                ($_.CommandLine -like '* /TESTMANAGER *') -or
                ($RunnerPath -and $_.CommandLine -like "*$RunnerPath*")
            )
        }

        foreach ($process in $leftovers) {
            try {
                Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            } catch {
            }
        }
    } catch {
        Write-Warning ("Не удалось завершить тестовые процессы 1С: {0}" -f $_.Exception.Message)
    }
}

function Install-VanessaExtQuietly {
    param(
        [string]$RunnerPath,
        [string]$ConnectionStringValue,
        [string]$User,
        [string]$Pass,
        [string]$LogPath
    )

    $installArgs = @(
        'ENTERPRISE',
        '/DisableStartupDialogs',
        '/DisableStartupMessages',
        '/TESTMANAGER',
        '/IBConnectionString', $ConnectionStringValue
    )

    if (-not [string]::IsNullOrWhiteSpace($User)) {
        $installArgs += '/N'
        $installArgs += $User
    }
    if (-not [string]::IsNullOrEmpty($Pass)) {
        $installArgs += '/P'
        $installArgs += $Pass
    }

    $installArgs += '/Execute'
    $installArgs += $RunnerPath
    $installArgs += '/Out'
    $installArgs += $LogPath
    $installArgs += '/C'
    $installArgs += 'QuietInstallVanessaExtAndClose=1'

    Invoke-Platform -Arguments $installArgs -OperationName 'Тихая установка VanessaExt'
}

function Ensure-VAExtensionCfe {
    param(
        [string]$TargetPath
    )

    if (Test-Path -LiteralPath $TargetPath -PathType Leaf) {
        return
    }

    $directory = Split-Path -Parent $TargetPath
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }

    Write-Host "==> Скачивание VAExtension.cfe"
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/Pr-Mex/vanessa-automation/releases/latest' -Headers @{ 'User-Agent' = 'Codex' }
    $asset = $release.assets | Where-Object { $_.name -like 'VAExtension*.cfe' } | Select-Object -First 1
    if ($null -eq $asset) {
        throw 'Не найден asset VAExtension*.cfe в latest release vanessa-automation.'
    }

    Invoke-WebRequest -Uri $asset.browser_download_url -Headers @{ 'User-Agent' = 'Codex' } -OutFile $TargetPath
}

function Install-VAExtensionInDatabase {
    param(
        [string]$CfePath,
        [string]$ConnectionStringValue,
        [string]$User,
        [string]$Pass,
        [string]$LogPath
    )

    $designerBaseArgs = @(
        'DESIGNER',
        '/DisableStartupDialogs',
        '/DisableStartupMessages',
        '/IBConnectionString', $ConnectionStringValue
    )

    if (-not [string]::IsNullOrWhiteSpace($User)) {
        $designerBaseArgs += '/N'
        $designerBaseArgs += $User
    }
    if (-not [string]::IsNullOrEmpty($Pass)) {
        $designerBaseArgs += '/P'
        $designerBaseArgs += $Pass
    }

    $loadArgs = @($designerBaseArgs)
    $loadArgs += '/Out'
    $loadArgs += $LogPath
    $loadArgs += '/LoadCfg'
    $loadArgs += $CfePath
    $loadArgs += '-Extension'
    $loadArgs += 'VAExtension'
    Invoke-Platform -Arguments $loadArgs -OperationName 'Загрузка расширения VAExtension в конфигурацию'

    $updateArgs = @($designerBaseArgs)
    $updateArgs += '/Out'
    $updateArgs += $LogPath
    $updateArgs += '/UpdateDBCfg'
    $updateArgs += '-Extension'
    $updateArgs += 'VAExtension'
    Invoke-Platform -Arguments $updateArgs -OperationName 'Обновление БД для расширения VAExtension'
}

function Initialize-VAParamsFile {
    param(
        [Parameter(Mandatory)]
        [string]$Path,
        [Parameter(Mandatory)]
        [string]$FeatureFilePath,
        [Parameter(Mandatory)]
        [string]$ConnectionStringValue
    )

    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory | Out-Null
    }

    $template = [ordered]@{
        Lang                  = 'ru'
        featurepath           = $FeatureFilePath
        'ВыполнитьСценарии'   = $true
        useaddin              = $true
        TestClient            = @{
            runtestclientwithmaximizedwindow = $true
            datatestclients = @(
                [ordered]@{
                    Name                 = 'LocalFileBase'
                    PathToInfobase       = $ConnectionStringValue
                    PortTestClient       = 48010
                    AddItionalParameters = ''
                    ClientType           = 'Thin'
                    ComputerName         = 'localhost'
                }
            )
        }
    }

    $json = $template | ConvertTo-Json -Depth 5
    $json | Set-Content -LiteralPath $Path -Encoding utf8
}

function Set-JsonPropertyValue {
    param(
        [Parameter(Mandatory)]
        $Object,
        [Parameter(Mandatory)]
        [string]$Name,
        $Value
    )

    $prop = $Object.PSObject.Properties[$Name]
    if ($prop) {
        $prop.Value = $Value
    } else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

Test-RequiredFile -Path $PlatformExe -Description 'платформы 1cv8'
Test-RequiredFile -Path $VanessaRunnerEpf -Description 'Vanessa Automation (epf)'
Test-RequiredFile -Path $FeatureFile -Description 'Vanessa Automation feature'

$vanessaRunnerEpfFullPath = (Resolve-Path -LiteralPath $VanessaRunnerEpf).Path
$featureFullPath = (Resolve-Path -LiteralPath $FeatureFile).Path
$vaExtensionCfeFullPath = [System.IO.Path]::GetFullPath($VAExtensionCfe)

if (-not (Test-Path -LiteralPath $VAParamsPath)) {
    Write-Host "Создаю файл VAParams.json по умолчанию: $VAParamsPath"
    Initialize-VAParamsFile -Path $VAParamsPath -FeatureFilePath $featureFullPath -ConnectionStringValue $ConnectionString
}

Test-RequiredFile -Path $VAParamsPath -Description 'VAParams.json'
$vaParamsFullPath = (Resolve-Path -LiteralPath $VAParamsPath).Path

try {
    $vaParams = Get-Content -LiteralPath $vaParamsFullPath -Raw -Encoding UTF8 | ConvertFrom-Json -ErrorAction Stop
} catch {
    throw "Не удалось прочитать VAParams.json: $($_.Exception.Message)"
}

if ($null -eq $vaParams) {
    throw "Не удалось загрузить структуру настроек из VAParams.json"
}

Set-JsonPropertyValue -Object $vaParams -Name 'featurepath' -Value $featureFullPath
Set-JsonPropertyValue -Object $vaParams -Name 'ВыполнитьСценарии' -Value $true
Set-JsonPropertyValue -Object $vaParams -Name 'useaddin' -Value $true

if ($null -eq $vaParams.TestClient) {
    $vaParams | Add-Member -NotePropertyName 'TestClient' -NotePropertyValue ([pscustomobject]@{})
}

$testClient = $vaParams.TestClient
Set-JsonPropertyValue -Object $testClient -Name 'runtestclientwithmaximizedwindow' -Value $true

if ($null -eq $testClient.datatestclients -or $testClient.datatestclients.Count -eq 0) {
    $testClient.datatestclients = @()
}

$clientSettings = [pscustomobject]@{
    Name                 = 'LocalFileBase'
    PathToInfobase       = $ConnectionString
    PortTestClient       = 48010
    AddItionalParameters = ''
    ClientType           = 'Thin'
    ComputerName         = 'localhost'
}

if ($testClient.datatestclients.Count -eq 0) {
    $testClient.datatestclients += $clientSettings
} else {
    $testClient.datatestclients[0] = $clientSettings
}

$vaParams | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $vaParamsFullPath -Encoding utf8

if (-not (Test-Path -LiteralPath $LogDir)) {
    Write-Host "Создаю каталог логов: $LogDir"
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$updateLog = Join-Path -Path $LogDir -ChildPath 'update-db.log'
$vanessaLog = Join-Path -Path $LogDir -ChildPath 'vanessa.log'
$installExtLog = Join-Path -Path $LogDir -ChildPath 'install-vanessa-ext.log'
$installVAExtensionLog = Join-Path -Path $LogDir -ChildPath 'install-vaextension.log'

if (-not $SkipDbUpdate) {
    $designerArgs = @(
        'DESIGNER',
        '/DisableStartupDialogs',
        '/DisableStartupMessages',
        '/IBConnectionString', $ConnectionString
    )

    if (-not [string]::IsNullOrWhiteSpace($UserName)) {
        $designerArgs += '/N'
        $designerArgs += $UserName
    }
    if (-not [string]::IsNullOrEmpty($Password)) {
        $designerArgs += '/P'
        $designerArgs += $Password
    }

    $designerArgs += '/Out'
    $designerArgs += $updateLog
    $designerArgs += '/UpdateDBCfg'

    Invoke-Platform -Arguments $designerArgs -OperationName 'Обновление конфигурации БД'
} else {
    Write-Host 'Пропускаю обновление БД (флаг -SkipDbUpdate).'
}

$vanessaCommand = "StartFeaturePlayer;FeatureFile=$featureFullPath;CloseTestClientBefore=1;StopOnError=1;ShowMainForm=0;LogDirectory=$LogDir;VAParams=$vaParamsFullPath;vanessarun=1;"

$vanessaArgs = @(
    'ENTERPRISE',
    '/DisableStartupDialogs',
    '/DisableStartupMessages',
    '/TESTMANAGER',
    '/IBConnectionString', $ConnectionString
)

if (-not [string]::IsNullOrWhiteSpace($UserName)) {
    $vanessaArgs += '/N'
    $vanessaArgs += $UserName
}
if (-not [string]::IsNullOrEmpty($Password)) {
    $vanessaArgs += '/P'
    $vanessaArgs += $Password
}

$vanessaArgs += '/Execute'
$vanessaArgs += $vanessaRunnerEpfFullPath
$vanessaArgs += '/Out'
$vanessaArgs += $vanessaLog
$vanessaArgs += '/C'
$vanessaArgs += $vanessaCommand

try {
    if ($InstallVAExtension) {
        Ensure-VAExtensionCfe -TargetPath $vaExtensionCfeFullPath
        Install-VAExtensionInDatabase -CfePath $vaExtensionCfeFullPath -ConnectionStringValue $ConnectionString -User $UserName -Pass $Password -LogPath $installVAExtensionLog
    }

    if ($InstallVanessaExt) {
        Install-VanessaExtQuietly -RunnerPath $vanessaRunnerEpfFullPath -ConnectionStringValue $ConnectionString -User $UserName -Pass $Password -LogPath $installExtLog
    }

    Invoke-VanessaFeatureRun -Arguments $vanessaArgs -OperationName 'Запуск сценария Vanessa Automation' -LogPath $vanessaLog -ConnectionStringValue $ConnectionString -RunnerPath $vanessaRunnerEpfFullPath
    Write-Host 'Выполнение завершено: обновление БД и сценарий Vanessa успешно отработали.'
}
finally {
    Stop-VanessaTestProcesses -ConnectionStringValue $ConnectionString -RunnerPath $vanessaRunnerEpfFullPath
}
