param(
    [string]$Source,
    [string]$Target,
    [string]$OwnerFile,
    [switch]$CleanupOnly
)
$ErrorActionPreference = 'Stop'

if ($CleanupOnly) {
    if (Test-Path -LiteralPath $OwnerFile) {
        $owner = Get-Content -LiteralPath $OwnerFile -Raw | ConvertFrom-Json
        $ownedProcess = Get-Process -Id $owner.processId -ErrorAction SilentlyContinue
        if ($ownedProcess -and $ownedProcess.ProcessName -eq 'EXCEL' -and
            $ownedProcess.StartTime.ToUniversalTime().Ticks.ToString() -eq $owner.startTicks) {
            Stop-Process -Id $ownedProcess.Id -Force
        }
    }
    exit 0
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ExcelProcessIdentity {
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
}
'@

$excel = $null
$workbook = $null
$control = $null
$books = $null
$ownsExcel = $false
$resultCode = 1
$existingExcelIds = @(Get-Process -Name EXCEL -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
try {
    try { $excel = New-Object -ComObject Excel.Application }
    catch { $resultCode = 3; throw }
    [uint32]$excelProcessId = 0
    [void][ExcelProcessIdentity]::GetWindowThreadProcessId([IntPtr]$excel.Hwnd, [ref]$excelProcessId)
    if ($excelProcessId -eq 0 -or $existingExcelIds -contains [int]$excelProcessId) {
        throw 'Cannot isolate Excel instance'
    }
    $ownsExcel = $true
    $ownedProcess = Get-Process -Id $excelProcessId
    @{ processId = $excelProcessId; startTicks = $ownedProcess.StartTime.ToUniversalTime().Ticks.ToString() } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $OwnerFile -Encoding UTF8
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    $excel.AskToUpdateLinks = $false
    $books = $excel.Workbooks
    $control = $books.Add()
    $excel.Calculation = -4135
    $excel.CalculateBeforeSave = $false
    # Never update links, calculate formulas, run macros, or write the uploaded source.
    $workbook = $books.Open($Source, 0, $true, [Type]::Missing, '', '', $true,
        [Type]::Missing, [Type]::Missing, $false, $false, [Type]::Missing, $false)
    if ($workbook.HasVBProject) { throw 'Macro template refused' }
    $workbook.CheckCompatibility = $false
    $workbook.SaveAs($Target, 51)
    $resultCode = 0
} catch {
    # Do not echo COM exceptions: they can contain workbook data or local paths.
} finally {
    if ($ownsExcel) {
        if ($workbook) { try { $workbook.Close($false) } catch {} }
        if ($control) { try { $control.Close($false) } catch {} }
        if ($excel) { try { $excel.Quit() } catch {} }
    }
    foreach ($wrapper in @($workbook, $control, $books, $excel)) {
        if ($wrapper) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wrapper) }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
exit $resultCode
