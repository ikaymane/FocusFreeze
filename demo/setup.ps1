# Opens the demo desk on the 4 GB machine. Apps that are not installed are skipped and listed.
#   powershell -File demo/setup.ps1
param(
    [string]$Project = (Split-Path $PSScriptRoot -Parent),
    [string]$ReferencePdf = "$PSScriptRoot\oauth-spec.pdf"
)

$missing = @()

function Open-App($name, $file, $arguments) {
    try {
        if ($arguments) { Start-Process $file -ArgumentList $arguments -ErrorAction Stop }
        else { Start-Process $file -ErrorAction Stop }
        Write-Host "opened  $name"
    } catch {
        $script:missing += $name
    }
}

Open-App "VS Code" "code" "`"$Project`""
Open-App "Terminal" "wt"

# 14 ordinary tabs plus the injection tab = the 15 tabs from the script.
$tabs = @(
    "https://en.wikipedia.org/wiki/OAuth", "https://en.wikipedia.org/wiki/Random-access_memory",
    "https://www.bbc.com/news", "https://www.reddit.com", "https://www.youtube.com",
    "https://github.com/trending", "https://news.ycombinator.com", "https://www.amazon.com",
    "https://www.imdb.com", "https://stackoverflow.com/questions", "https://www.theverge.com",
    "https://www.nytimes.com", "https://www.twitch.tv", "https://www.espn.com"
)
$injection = "file:///" + ("$PSScriptRoot\injection.html" -replace '\\', '/')
Open-App "Chrome (15 tabs)" "chrome" (($tabs + $injection) -join " ")

foreach ($app in @(
    @("Discord", "$env:LOCALAPPDATA\Discord\Update.exe", "--processStart Discord.exe"),
    @("Teams", "ms-teams:", $null),
    @("Spotify", "spotify:", $null),
    @("Steam", "steam:", $null)
)) { Open-App $app[0] $app[1] $app[2] }

if (Test-Path $ReferencePdf) { Open-App "PDF reader" $ReferencePdf }
else { $missing += "PDF reader (put a reference PDF at $ReferencePdf)" }

# The unsaved document: its survival is the payoff of the "I'm done" scene.
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $true
    $doc = $word.Documents.Add()
    $word.Selection.TypeText("Focus Freeze demo. This text was never saved. Typed at $(Get-Date -Format HH:mm:ss).")
    Write-Host "opened  Word, with an unsaved document"
} catch {
    $missing += "Word"
}

if ($missing) { Write-Host "`nNOT OPENED: $($missing -join ', ')" -ForegroundColor Yellow }
Write-Host "`nWait 40 minutes before filming so the PDF is really idle, or leave it unfocused from now on."
