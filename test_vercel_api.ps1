$wc = New-Object System.Net.WebClient
$wc.Encoding = [System.Text.Encoding]::UTF8
try {
    $res = $wc.DownloadString('https://nexusbi-attmdv86b-duckanh.vercel.app/api/sheet/files')
    Write-Host "Files response:" $res
} catch {
    Write-Host "Error:" $_.Exception.Message
}
