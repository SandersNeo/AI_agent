param(
    [string]$HostUser,
    [string]$HostPassword
)

$s = New-Object System.Security.SecureString
'Admin'.ToCharArray() | ForEach-Object { $s.AppendChar($_) }
$guestCred = New-Object System.Management.Automation.PSCredential('Admin', $s)

Invoke-Command -VMName 'ai-agent-ui-win' -Credential $guestCred -ArgumentList $HostUser, $HostPassword -ScriptBlock {
    param($HostUser, $HostPassword)

    $hostPass = New-Object System.Security.SecureString
    $HostPassword.ToCharArray() | ForEach-Object { $hostPass.AppendChar($_) }
    $hostCred = New-Object System.Management.Automation.PSCredential($HostUser, $hostPass)

    if (Get-PSDrive -Name H -ErrorAction SilentlyContinue) {
        Remove-PSDrive -Name H -Force
    }
    New-PSDrive -Name H -PSProvider FileSystem -Root '\\DEV1\D' -Credential $hostCred -Scope Global | Out-Null

    $python = 'C:\Python\python.exe'
    if (-not (Test-Path $python)) {
        throw 'C:\Python\python.exe not found'
    }

    $baseDir = Get-ChildItem 'H:\bd' | Where-Object { $_.Name -like '*3013238*' } | Select-Object -First 1
    if (-not $baseDir) {
        throw 'Base directory matching *3013238* not found on H:\bd'
    }

    & $python -m ensurepip --upgrade
    & $python -m pip install --upgrade pip
    & $python -m pip install -r 'C:\Work\AI_agent\automation\ui\requirements-ui.txt'

    $launcherPs1 = @"
$env:PYTHONUTF8 = '1'
$env:PATH = 'C:\Python;' + $env:PATH
Set-Location -LiteralPath 'C:\Work\AI_agent'
& 'C:\Python\python.exe' -u 'automation\ui\ui_1c_agent_test.py' --platform-exe 'C:\Tools\1cv8\8.5.1.1150\bin\1cv8.exe' --base-path '$($baseDir.FullName)' --user 'Администратор'
"@

    Set-Content -Path 'C:\Work\AI_agent\automation\ui\run_ui_test_in_vm.ps1' -Value $launcherPs1 -Encoding UTF8
    Set-Content -Path 'C:\Work\AI_agent\automation\ui\run_ui_test_in_vm.cmd' -Value '@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Work\AI_agent\automation\ui\run_ui_test_in_vm.ps1"' -Encoding ASCII

    [pscustomobject]@{
        PythonVersion = (& $python --version 2>&1)
        PipVersion = (& $python -m pip --version 2>&1)
        BasePath = $baseDir.FullName
        LauncherPs1 = 'C:\Work\AI_agent\automation\ui\run_ui_test_in_vm.ps1'
        Launcher = 'C:\Work\AI_agent\automation\ui\run_ui_test_in_vm.cmd'
        OneCExists = Test-Path 'C:\Tools\1cv8\8.5.1.1150\bin\1cv8.exe'
        RepoExists = Test-Path 'C:\Work\AI_agent\automation\ui\ui_1c_agent_test.py'
    }
}
