# Pushes RAM over the guardian's 85% trigger for the pressure scene, then frees it on exit.
#   powershell -File demo/hog.ps1                         # to 90%, held for 3 minutes
#   powershell -File demo/hog.ps1 -TargetPct 88 -HoldSeconds 60
# Run it on the demo machine only. MaxGB stops it taking the machine down.
param(
    [int]$TargetPct = 90,
    [int]$HoldSeconds = 180,
    [int]$ChunkMB = 100,
    [int]$MaxGB = 6
)

Add-Type -TypeDefinition @"
public static class Hog {
    // Pages only count as used once they are written.
    public static byte[] Take(int mb) {
        var b = new byte[mb * 1024 * 1024];
        for (int i = 0; i < b.Length; i += 4096) b[i] = 1;
        return b;
    }
}
"@

function Get-RamPct {
    $os = Get-CimInstance Win32_OperatingSystem
    [math]::Round(100 * (1 - $os.FreePhysicalMemory / $os.TotalVisibleMemorySize), 1)
}

$held = New-Object System.Collections.ArrayList
$takenMB = 0
try {
    while ((Get-RamPct) -lt $TargetPct -and $takenMB -lt $MaxGB * 1024) {
        [void]$held.Add([Hog]::Take($ChunkMB))
        $takenMB += $ChunkMB
    }
    Write-Host "Holding $takenMB MB. RAM is at $(Get-RamPct)%. Ctrl+C to release."
    $end = (Get-Date).AddSeconds($HoldSeconds)
    while ((Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
} finally {
    $held.Clear()
    [GC]::Collect()
    Write-Host "Released. RAM is at $(Get-RamPct)%."
}
