$s = New-Object System.Security.SecureString
'Admin'.ToCharArray() | ForEach-Object { $s.AppendChar($_) }
$guestCred = New-Object System.Management.Automation.PSCredential('Admin', $s)

Invoke-Command -VMName 'ai-agent-ui-win' -Credential $guestCred -ScriptBlock {
    $desktopLauncher = 'C:\Users\Admin\Desktop\Run AI UI Test.cmd'
    Copy-Item 'C:\Work\AI_agent\automation\ui\run_ui_test_in_vm.cmd' $desktopLauncher -Force

    $python = 'C:\Python\python.exe'
    $helpOut = & $python 'C:\Work\AI_agent\automation\ui\ui_1c_agent_test.py' --help 2>&1

    [pscustomobject]@{
        DesktopLauncher = Test-Path $desktopLauncher
        PythonHelpOk = [bool]($helpOut -match '--platform-exe')
        HelpSample = ($helpOut | Select-Object -First 5) -join [Environment]::NewLine
    }
}
