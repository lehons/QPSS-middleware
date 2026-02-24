# run_remote.ps1 — Execute QPSS middleware on IS-APP-19 via PowerShell Remoting
#
# Usage:
#   powershell -File run_remote.ps1 --flow1
#   powershell -File run_remote.ps1 --flow2
#   powershell -File run_remote.ps1 --flow1 --dry-run
#   powershell -File run_remote.ps1 --list-stores
#   powershell -File run_remote.ps1 --cleanup-pending 90
#
# All arguments are forwarded to qpss_middleware.py on the remote server.

param(
    [Parameter(Position=0, ValueFromRemainingArguments=$true)]
    [string[]]$QpssArgs
)

$Server = "IS-APP-19"
$QpssPath = "C:\QPSS-middleware"
$ArgString = ($QpssArgs -join " ")

try {
    # Create a persistent session to the server
    $session = New-PSSession -ComputerName $Server -ErrorAction Stop
    Write-Host "Connected to $Server" -ForegroundColor Green
    Write-Host ""

    # Run the middleware command remotely
    # Using Invoke-Command with -Session for the remote execution
    Invoke-Command -Session $session -ScriptBlock {
        param($path, $args_str)
        Set-Location $path
        $cmd = "python qpss_middleware.py $args_str"
        cmd /c $cmd
    } -ArgumentList $QpssPath, $ArgString

} catch [System.Management.Automation.Remoting.PSRemotingTransportException] {
    Write-Host ""
    Write-Host "ERROR: Cannot connect to $Server" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible causes:" -ForegroundColor Yellow
    Write-Host "  - $Server is not reachable on the network"
    Write-Host "  - Your account does not have remote execution permission"
    Write-Host "  - WinRM service is not running on $Server"
    Write-Host ""
    Write-Host "To test connectivity, run:" -ForegroundColor Yellow
    Write-Host "  Test-WSMan -ComputerName $Server"
    exit 1

} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1

} finally {
    # Clean up the remote session
    if ($session) {
        Remove-PSSession -Session $session -ErrorAction SilentlyContinue
    }
}
