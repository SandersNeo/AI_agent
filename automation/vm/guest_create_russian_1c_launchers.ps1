$s = New-Object System.Security.SecureString
'Admin'.ToCharArray() | ForEach-Object { $s.AppendChar($_) }
$guestCred = New-Object System.Management.Automation.PSCredential('Admin', $s)

Invoke-Command -VMName 'ai-agent-ui-win' -Credential $guestCred -ScriptBlock {
    $oneCExe = 'C:\Tools\1cv8\8.5.1.1150\bin\1cv8.exe'
    $desktopDir = 'C:\Users\Admin\Desktop'
    $wsh = New-Object -ComObject WScript.Shell

    $launcherCmd = @"
@echo off
start "" "C:\Tools\1cv8\8.5.1.1150\bin\1cv8.exe" /L ru
"@
    Set-Content -Path 'C:\Work\AI_agent\automation\vm\run_1c_russian.cmd' -Value $launcherCmd -Encoding ASCII

    $shortcut = $wsh.CreateShortcut((Join-Path $desktopDir '1C Russian.lnk'))
    $shortcut.TargetPath = $oneCExe
    $shortcut.Arguments = '/L ru'
    $shortcut.WorkingDirectory = Split-Path $oneCExe
    $shortcut.IconLocation = $oneCExe
    $shortcut.Save()

    $uiTestCmd = 'C:\Work\AI_agent\automation\ui\run_ui_test_in_vm.ps1'
    if (Test-Path $uiTestCmd) {
        $content = Get-Content $uiTestCmd -Raw
        if ($content -notmatch '/L ru') {
            $content = $content -replace "--platform-exe 'C:\\Tools\\1cv8\\8\.5\.1\.1150\\bin\\1cv8\.exe'", "--platform-exe 'C:\\Tools\\1cv8\\8.5.1.1150\\bin\\1cv8.exe' --startup-timeout-sec 120"
            Set-Content -Path $uiTestCmd -Value $content -Encoding UTF8
        }
    }

    [pscustomobject]@{
        OneCExe = Test-Path $oneCExe
        DesktopShortcut = Test-Path (Join-Path $desktopDir '1C Russian.lnk')
        RussianCmd = Test-Path 'C:\Work\AI_agent\automation\vm\run_1c_russian.cmd'
        UiTestCmd = Test-Path $uiTestCmd
    }
}
