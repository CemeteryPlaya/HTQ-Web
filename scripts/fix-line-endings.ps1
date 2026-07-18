$files = @(
    "d:\HTQWeb1\backend\entrypoint.sh",
    "d:\HTQWeb1\services\hr\entrypoint.sh",
    "d:\HTQWeb1\services\task\entrypoint.sh"
)

foreach ($file in $files) {
    if (Test-Path $file) {
        $content = [System.IO.File]::ReadAllText($file)
        $content = $content.Replace("`r`n", "`n")
        $utf8NoBOM = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($file, $content, $utf8NoBOM)
        Write-Host "Fixed line endings: $file"
    } else {
        Write-Host "Not found: $file"
    }
}
